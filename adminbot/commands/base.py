"""Command plumbing: the @command decorator, the shared CommandGroup helpers and the router.

maubot's own command decorators answer with usage help to anyone, in any room, before a handler
can check permissions. The bot is a member of every course room, so a single router handles
all messages instead: unknown senders and non-DM rooms are dealt with before anything is said.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from maubot import MessageEvent
from maubot.handlers import event
from mautrix.errors import MatrixRequestError
from mautrix.types import EventID, EventType, MessageType, RoomID, UserID

from ..attachments import Upload, UploadHandler, download, file_from_reply, is_file_message, send_file
from ..authz import Role
from ..db import Course
from ..errors import AdminBotError, NotFound, ValidationError
from ..parsing import ArgError
from ..identity import IdentityError, is_local_user, normalize_email, user_id_for_email
from ..strings import t

if TYPE_CHECKING:
    from ..bot import AdminBot

log = logging.getLogger("maubot.adminbot.commands")

COMMAND_RE = re.compile(r"^!(\S+)\s*(.*)$", re.DOTALL)
WORD_RE = re.compile(r"^(\S+)\s*(.*)$", re.DOTALL)
HELP_FLAG_RE = re.compile(r"(?:^|\s)--help(?:\s|$)")
# Reaction on every accepted command (and processed upload), sent before any real work, so the
# sender sees right away that the bot has the message.
ACK_REACTION = "\U0001F916"

Handler = Callable[[MessageEvent, str], Awaitable[None]]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    sub: str | None
    usage: str  # strings key, shown in !help and on errors
    role: Role | None  # who sees it in !help (None = every known user); handlers check for real
    needs: tuple[str, ...]  # startup checks the command depends on

    @property
    def label(self) -> str:
        """'course create', 'invite'."""
        return f"{self.name} {self.sub}" if self.sub else self.name

    @property
    def help_key(self) -> str:
        """Detailed help text: usage.course.create -> help.course.create."""
        return "help." + self.usage.removeprefix("usage.")


def command(name: str, sub: str | None = None, *, usage: str, role: Role | None,
            needs: tuple[str, ...] = ("admin",)) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        func.__adminbot_command__ = CommandSpec(name, sub, usage, role, needs)
        return func

    return decorator


class CommandGroup:
    def __init__(self, bot: AdminBot) -> None:
        self.bot = bot

    # --- replies ------------------------------------------------------------------------
    async def reply(self, evt: MessageEvent, key: str, **params: object) -> EventID:
        return await self.bot.ops.send(evt.room_id, t(key, **params))

    async def reply_text(self, evt: MessageEvent, text: str) -> EventID:
        return await self.bot.ops.send(evt.room_id, text)

    async def reply_file(self, evt: MessageEvent, filename: str, data: bytes, mimetype: str) -> EventID:
        return await send_file_to(self.bot, evt.room_id, filename, data, mimetype)

    # --- permissions and lookups -----------------------------------------------------------
    async def require(self, evt: MessageEvent, role: Role | None, course: str | None = None) -> None:
        await self.bot.authz.require(evt.sender, role, course)

    async def course(self, code: str | None) -> Course:
        course = await self.bot.store.get_course((code or "").upper())
        if course is None:
            raise NotFound("err.unknown_course", code=code or "")
        return course

    async def require_course(self, evt: MessageEvent, code: str | None, role: Role) -> Course:
        course = await self.course(code)
        await self.require(evt, role, course.code)
        return course

    def user_arg(self, value: str | None) -> UserID:
        """A local Matrix ID like @max.muster:server."""
        if not value or not is_local_user(value, self.bot.server_name):
            raise ValidationError("err.bad_user", value=value or "", server=self.bot.server_name)
        return UserID(value)

    def email_to_user(self, value: str) -> tuple[UserID, str]:
        """(user ID, normalised email) for an allowed university address."""
        try:
            email = normalize_email(value)
            return user_id_for_email(email, self.bot.server_name, self.bot.config["identity.allowed_domains"]), email
        except IdentityError as e:
            raise ValidationError(e.key, value=e.value,
                                  domains=", ".join(self.bot.config["identity.allowed_domains"])) from e

    def identifier_to_user(self, value: str) -> UserID:
        """Email or Matrix ID."""
        value = value.strip()
        return self.user_arg(value) if value.startswith("@") else self.email_to_user(value)[0]

    @property
    def levels(self) -> dict[str, int]:
        return {"owner": self.bot.config["power_levels.owner"], "ta": self.bot.config["power_levels.ta"]}

    # --- confirm and files -----------------------------------------------------------------
    async def propose(self, evt: MessageEvent, kind: str, summary: str, items: list[dict[str, Any]],
                      context: dict[str, Any], dry_run: bool) -> None:
        if dry_run:
            await self.reply(evt, "msg.dry_run", summary=summary)
            return
        plan = await self.bot.confirm.propose(evt.sender, evt.room_id, kind, summary, items, context)
        await self.reply(evt, "msg.plan", summary=summary, code=plan.code,
                         minutes=self.bot.config["confirm.ttl_minutes"])

    @property
    def max_upload(self) -> int:
        return self.bot.config["uploads.max_size_mb"] * 1024 * 1024

    async def with_file(self, evt: MessageEvent, handler: UploadHandler, context: dict[str, Any],
                        what: str) -> None:
        """Use the file the command replies to, or wait for the next upload in this DM.
        `what` is a strings key naming the expected file (msg.file_*), used in the prompts."""
        context = {**context, "_what": what}
        upload = await file_from_reply(self.bot.client, evt, self.max_upload)
        if upload is not None:
            await run_upload(self.bot, evt, handler, upload, context)
            return
        self.bot.uploads.expect(evt.room_id, evt.sender, handler, context)
        await self.reply(evt, "msg.waiting_for_file", what=t(what), minutes=self.bot.config["uploads.wait_minutes"])


async def run_upload(bot: AdminBot, evt: MessageEvent, handler: UploadHandler, upload: Upload,
                     context: dict[str, Any]) -> None:
    """Run an upload handler. If it rejects the file (ValidationError: wrong format, invalid
    package, no usable rows ...), wait for a corrected file with the same command context, so
    the sender only has to send the file again, not the whole command."""
    try:
        await handler(evt, upload, context)
    except ValidationError as e:
        bot.uploads.expect(evt.room_id, evt.sender, handler, context)
        what = t(context.get("_what") or "msg.file_generic")
        raise RetryUpload(e, what, bot.config["uploads.wait_minutes"]) from e


class RetryUpload(AdminBotError):
    """A rejected upload: the original error plus how to send a corrected file."""

    def __init__(self, error: AdminBotError, what: str, minutes: int) -> None:
        super().__init__("msg.retry_file", what=what, minutes=minutes)
        self.error = error

    def __str__(self) -> str:
        return f"{self.error}\n\n{super().__str__()}"


async def send_file_to(bot: AdminBot, room_id: RoomID, filename: str, data: bytes, mimetype: str) -> EventID:
    return await send_file(bot.client, room_id, filename, data, mimetype, await bot.ops.is_encrypted(room_id))


def describe(e: Exception, spec: CommandSpec | None = None) -> str:
    if isinstance(e, AdminBotError):
        text = str(e)
        if isinstance(e, ArgError) and spec is not None:
            text += "\n" + t("msg.help_hint", command=spec.label)
        return text
    if isinstance(e, MatrixRequestError):
        return t("err.matrix", detail=getattr(e, "message", None) or str(e))
    return t("err.internal")


class CommandRouter:
    """The only Matrix event handler: routes `!command sub args` and uploaded files."""

    ORDER = ["help", "whoami", "confirm", "cancel", "course", "room", "invite", "roster", "groups",
             "template", "signup", "bot", "admin"]

    def __init__(self, bot: AdminBot, groups: list[CommandGroup]) -> None:
        self.bot = bot
        self.handlers: dict[tuple[str, str | None], tuple[CommandSpec, Handler]] = {}
        self.specs: list[CommandSpec] = []
        for group in groups:
            # vars() keeps the definition order, so subcommands are listed in the order they are
            # written in their class (create before archive), not alphabetically.
            for attr, value in vars(type(group)).items():
                spec = getattr(value, "__adminbot_command__", None)
                if spec is not None:
                    self.handlers[(spec.name, spec.sub)] = (spec, getattr(group, attr))
                    self.specs.append(spec)
        order = {name: i for i, name in enumerate(self.ORDER)}
        self.specs.sort(key=lambda s: order.get(s.name, 99))
        self.names = {spec.name for spec in self.specs}

    def subcommands(self, name: str) -> list[str]:
        return [s.sub for s in self.specs if s.name == name and s.sub]

    async def _allowed_sender(self, sender: UserID) -> bool:
        return (
            sender != self.bot.client.mxid
            and is_local_user(sender, self.bot.server_name)
            and await self.bot.authz.is_known(sender)
        )

    async def _in_dm(self, evt: MessageEvent) -> bool:
        if evt.room_id == self.bot.config["audit_room"]:
            return False
        return await self.bot.ops.is_dm(evt.room_id, evt.sender)

    async def _ack(self, evt: MessageEvent) -> None:
        """React with ACK_REACTION. Never fails the command."""
        try:
            await self.bot.client.react(evt.room_id, evt.event_id, ACK_REACTION)
        except Exception as e:
            log.warning(f"Couldn't react to {evt.event_id}: {e}")

    @event.on(EventType.ROOM_MESSAGE)
    async def on_message(self, evt: MessageEvent) -> None:
        if evt.sender == self.bot.client.mxid:
            return
        if is_file_message(evt.content):
            await self.on_file(evt)
            return
        if evt.content.msgtype != MessageType.TEXT or not evt.content.body:
            return
        evt.content.trim_reply_fallback()
        match = COMMAND_RE.match(evt.content.body.strip())
        if not match:
            return
        name, rest = match.group(1).lower(), match.group(2)
        # The bot is in every course room, where other bots' !commands are normal: unknown
        # names are only answered in a DM, and only to known users.
        known_name = name in self.names
        if not await self._allowed_sender(evt.sender):
            return
        in_dm = await self._in_dm(evt)
        if not known_name:
            if in_dm:
                await self.bot.ops.send(evt.room_id, self.unknown_command(name))
            return
        if not in_dm:
            await self.bot.ops.send(evt.room_id, t("err.not_dm", bot=self.bot.client.mxid))
            return
        await self._ack(evt)
        try:
            await self.bot.ops.remember_dm(evt.sender, evt.room_id)
        except Exception as e:
            log.warning(f"Couldn't record DM of {evt.sender}: {e}")
        sub_match = WORD_RE.match(rest)
        sub = sub_match.group(1).lower() if sub_match else None
        help_handler = self.handlers[("help", None)]
        if name != "help" and sub == "help":
            # "!course help [create]"
            await self._run(evt, help_handler[1](evt, f"{name} {sub_match.group(2)}"), help_handler[0])
            return
        if name != "help" and HELP_FLAG_RE.search(rest.partition("\n")[0]):
            # "!course create --help", "!invite --help"
            topic = sub if sub is not None and (name, sub) in self.handlers else ""
            await self._run(evt, help_handler[1](evt, f"{name} {topic}"), help_handler[0])
            return
        if sub is not None and (name, sub) in self.handlers:
            spec, handler = self.handlers[(name, sub)]
            args = sub_match.group(2)
        elif (name, None) in self.handlers:
            spec, handler = self.handlers[(name, None)]
            args = rest
        else:
            await self.bot.ops.send(evt.room_id, self.missing_subcommand(name, sub))
            return
        failed = [check for check in spec.needs if check in self.bot.failed_checks]
        if failed:
            await self.bot.ops.send(evt.room_id, t("err.check_failed", check=", ".join(failed)))
            return
        await self._run(evt, handler(evt, args), spec)

    def unknown_command(self, name: str) -> str:
        close = difflib.get_close_matches(name, sorted(self.names), n=1)
        hint = t("msg.did_you_mean", command=f"!{close[0]}") if close else ""
        return t("msg.unknown_command", name=name, hint=hint)

    def missing_subcommand(self, name: str, sub: str | None) -> str:
        subs = self.subcommands(name)
        usages = "\n".join(f"- {t(s.usage)}" for s in self.specs if s.name == name)
        if sub is None:
            return t("msg.subcommands", name=name, usages=usages, example=subs[0] if subs else "")
        close = difflib.get_close_matches(sub, subs, n=1)
        hint = t("msg.did_you_mean", command=f"!{name} {close[0]}") if close else ""
        return t("msg.unknown_subcommand", name=name, sub=sub, hint=hint, usages=usages,
                 example=subs[0] if subs else "")

    async def on_file(self, evt: MessageEvent) -> None:
        if not self.bot.uploads.is_waiting(evt.room_id, evt.sender):
            return
        if not await self._allowed_sender(evt.sender) or not await self._in_dm(evt):
            return
        waiting = self.bot.uploads.take(evt.room_id, evt.sender)
        if waiting is None:
            return
        await self._ack(evt)

        async def process() -> None:
            upload: Upload = await download(self.bot.client, evt.content, self.bot.config["uploads.max_size_mb"] * 1024 * 1024)
            await run_upload(self.bot, evt, waiting.handler, upload, waiting.context)

        await self._run(evt, process(), None)

    async def _run(self, evt: MessageEvent, coro: Awaitable[None], spec: CommandSpec | None) -> None:
        """Run a handler and turn errors into replies. Logs how long the server took to deliver
        the message (lag) and how long the handler took, to tell slow syncs from slow commands."""
        label = spec.label if spec else "upload"
        started = time.monotonic()
        lag_ms = int(time.time() * 1000) - evt.timestamp if evt.timestamp else -1
        try:
            await coro
        except AdminBotError as e:
            await self.bot.ops.send(evt.room_id, describe(e, spec))
        except MatrixRequestError as e:
            log.warning(f"Matrix error in {label}: {e}")
            await self.bot.ops.send(evt.room_id, describe(e, spec))
        except Exception:
            log.exception(f"Command {label} failed")
            await self.bot.ops.send(evt.room_id, t("err.internal"))
        finally:
            took_ms = int((time.monotonic() - started) * 1000)
            log.info(f"!{label} from {evt.sender}: reached the bot {lag_ms} ms after it was sent, "
                     f"handled in {took_ms} ms")
