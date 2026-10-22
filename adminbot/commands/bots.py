"""!bot: professor-owned bots (plan §10). Every handler needs the 'userbots' startup check."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maubot import MessageEvent
from mautrix.types import UserID

from ..attachments import Upload, file_from_reply
from ..authz import Role
from ..db import UserBot
from ..errors import Forbidden, ValidationError
from ..jobs import JobKind
from ..parsing import Args, decode_text, split_args
from ..strings import t
from ..userbots import BotManager
from .base import CommandGroup, command

if TYPE_CHECKING:
    from ..bot import AdminBot

NEEDS = ("admin", "userbots")


class BotCommands(CommandGroup):
    def __init__(self, bot: AdminBot) -> None:
        super().__init__(bot)
        bot.jobs.register(JobKind.BOT_PROVISION, self.provision_item, audit_action="bot.provision")
        bot.jobs.register(JobKind.BOT_DELETE, self.delete_item, audit_action="bot.delete")

    @property
    def manager(self) -> BotManager:
        if self.bot.bots is None:
            raise ValidationError("err.bots_disabled")
        return self.bot.bots

    async def provision_item(self, job, item) -> None:
        await self.manager.provision_item(job, item)

    async def delete_item(self, job, item) -> None:
        await self.manager.delete_item(job, item)

    async def target(self, evt: MessageEvent, a: Args, usage: str) -> UserBot:
        """`<name>` (own bot; admins: any bot with that name, if only one owner has it),
        `<@owner> <name>` or the bot's account `@bot.<owner>.<name>:server`. Bots of other
        owners: admins only."""
        await self.require(evt, Role.PROFESSOR)
        admin = self.bot.authz.is_admin(evt.sender)
        first = a.require(1, usage)[0]
        if not first.startswith("@"):
            return await self.manager.resolve(evt.sender, BotManager.check_name(first), admin)
        user = self.user_arg(first)
        if a.get(1) is None:
            bot = await self.manager.by_user_id(user)
        else:
            if user != evt.sender and not admin:
                raise Forbidden("err.forbidden_bot")
            bot = await self.manager.get(user, BotManager.check_name(a.get(1)))
        if bot.owner != evt.sender and not admin:
            raise Forbidden("err.forbidden_bot")
        return bot

    def owner_filter(self, evt: MessageEvent, value: str | None) -> UserID | None:
        """Whose bots `list`/`delete all` mean: an explicit `@owner` (others: admins only), else
        all bots for admins (None) and the sender's own for professors."""
        admin = self.bot.authz.is_admin(evt.sender)
        if not value:
            return None if admin else evt.sender
        owner = self.user_arg(value)
        if owner != evt.sender and not admin:
            raise Forbidden("err.forbidden_bot")
        return owner

    @command("bot", "create", usage="usage.bot.create", role=Role.PROFESSOR, needs=NEEDS)
    async def create(self, evt: MessageEvent, args: str) -> None:
        usage = t("usage.bot.create")
        await self.require(evt, Role.PROFESSOR)
        name = BotManager.check_name(split_args(args, usage=usage).require(1, usage)[0])
        # Checked again when the file arrives; here so nobody uploads a file in vain.
        await self.manager.check_can_create(evt.sender, name)
        await self.with_file(evt, self.on_mbp, {"action": "create", "owner": evt.sender, "name": name},
                             "msg.file_mbp")

    @command("bot", "update", usage="usage.bot.update", role=Role.PROFESSOR, needs=NEEDS)
    async def update(self, evt: MessageEvent, args: str) -> None:
        usage = t("usage.bot.update")
        bot = await self.target(evt, split_args(args, usage=usage), usage)
        await self.with_file(evt, self.on_mbp, {"action": "update", "owner": bot.owner, "name": bot.name},
                             "msg.file_mbp")

    async def on_mbp(self, evt: MessageEvent, upload: Upload, context: dict[str, Any]) -> None:
        await self.require(evt, Role.PROFESSOR)
        request = await self.manager.request(context["owner"], context["name"], upload.data, context["action"],
                                             evt.sender)
        if request.state == "pending":
            await self.reply(evt, "msg.bot_requested", name=request.name, id=request.id)
        else:
            await self.reply(evt, "msg.bot_provisioning", name=request.name)

    @command("bot", "list", usage="usage.bot.list", role=Role.PROFESSOR, needs=NEEDS)
    async def list_(self, evt: MessageEvent, args: str) -> None:
        usage = t("usage.bot.list")
        await self.require(evt, Role.PROFESSOR)
        owner = self.owner_filter(evt, split_args(args, usage=usage).get(0))
        bots = await self.manager.list_for(owner)
        lines = [f"- `{b.name}` ({b.owner}): {b.user_id}, {b.plugin_id}, {b.state}" for b in bots]
        await self.reply(evt, "msg.bot_list_all" if owner is None else "msg.bot_list",
                         bots="\n".join(lines) or "-", count=len(bots), owner=owner or "")

    @command("bot", "info", usage="usage.bot.info", role=Role.PROFESSOR, needs=NEEDS)
    async def info(self, evt: MessageEvent, args: str) -> None:
        usage = t("usage.bot.info")
        bot = await self.target(evt, split_args(args, usage=usage), usage)
        info = await self.manager.info(bot.owner, bot.name)
        verified = t("msg.bot_verified") if info.pop("verified") else t("msg.bot_not_verified")
        await self.reply(evt, "msg.bot_info", **info, verified=verified,
                         status=t("msg.bot_running") if info["started"] else t("msg.bot_stopped"))

    @command("bot", "config", usage="usage.bot.config", role=Role.PROFESSOR, needs=NEEDS)
    async def config(self, evt: MessageEvent, args: str) -> None:
        """Without a replied-to file: send the config. Replying to a .yaml: replace it."""
        usage = t("usage.bot.config")
        bot = await self.target(evt, split_args(args, usage=usage), usage)
        upload = await file_from_reply(self.bot.client, evt, self.max_upload)
        if upload is None:
            text = await self.manager.get_config(bot.owner, bot.name)
            await self.reply_file(evt, f"{bot.name}-config.yaml", text.encode("utf-8"), "application/yaml")
            return
        await self.manager.set_config(bot.owner, bot.name, decode_text(upload.data))
        await self.bot.audit.log(evt.sender, "bot.config", bot=bot.name)
        await self.reply(evt, "msg.bot_config_saved", name=bot.name)

    async def _set_started(self, evt: MessageEvent, args: str, started: bool, usage_key: str) -> None:
        usage = t(usage_key)
        bot = await self.target(evt, split_args(args, usage=usage), usage)
        await self.manager.set_started(bot.owner, bot.name, started)
        await self.bot.audit.log(evt.sender, "bot.start" if started else "bot.stop", bot=bot.name)
        await self.reply(evt, "msg.bot_started" if started else "msg.bot_stopped_now", name=bot.name)

    @command("bot", "start", usage="usage.bot.start", role=Role.PROFESSOR, needs=NEEDS)
    async def start(self, evt: MessageEvent, args: str) -> None:
        await self._set_started(evt, args, True, "usage.bot.start")

    @command("bot", "stop", usage="usage.bot.stop", role=Role.PROFESSOR, needs=NEEDS)
    async def stop(self, evt: MessageEvent, args: str) -> None:
        await self._set_started(evt, args, False, "usage.bot.stop")

    @command("bot", "delete", usage="usage.bot.delete", role=Role.PROFESSOR, needs=NEEDS)
    async def delete(self, evt: MessageEvent, args: str) -> None:
        usage = t("usage.bot.delete")
        a = split_args(args, usage=usage)
        if (a.get(0) or "").lower() == "all":
            await self.delete_all(evt, a.get(1))
            return
        bot = await self.target(evt, a, usage)
        summary = t("msg.bot_delete_plan", name=bot.name, user_id=bot.user_id)
        items = [{"owner": bot.owner, "name": bot.name, "label": bot.name}]
        await self.propose(evt, JobKind.BOT_DELETE.value, summary, items,
                           {"bot": bot.name, "role": Role.PROFESSOR.value}, dry_run=False)

    async def delete_all(self, evt: MessageEvent, owner_arg: str | None) -> None:
        """`!bot delete all [@owner]`: every professor bot (admins) or all of one owner's. The
        admin bot itself is never a professor bot, so it can't be in the list."""
        await self.require(evt, Role.PROFESSOR)
        owner = self.owner_filter(evt, owner_arg)
        bots = await self.manager.list_for(owner)
        if not bots:
            await self.reply(evt, "msg.bot_delete_none")
            return
        lines = "\n".join(f"- `{b.name}` ({b.owner}): {b.user_id}" for b in bots)
        summary = t("msg.bot_delete_all_plan", count=len(bots), bots=lines)
        items = [{"owner": b.owner, "name": b.name, "label": f"{b.name} ({b.owner})"} for b in bots]
        role = Role.PROFESSOR if owner == evt.sender else Role.ADMIN
        await self.propose(evt, JobKind.BOT_DELETE.value, summary, items,
                           {"bot": "all", "role": role.value}, dry_run=False)
