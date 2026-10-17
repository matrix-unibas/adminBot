"""!help [<command> [<sub>]] and !whoami."""
from __future__ import annotations

from dataclasses import dataclass

from maubot import MessageEvent

from ..authz import Role
from ..parsing import split_args
from ..strings import t
from .base import CommandGroup, CommandSpec, command

# Sections of the !help overview: (strings key of the heading, command names).
AREAS = [
    ("help.area.basics", ["help", "whoami", "confirm", "cancel"]),
    ("help.area.courses", ["course", "room"]),
    ("help.area.people", ["invite", "roster", "signup"]),
    ("help.area.groups", ["groups"]),
    ("help.area.templates", ["template"]),
    ("help.area.bots", ["bot"]),
    ("help.area.admin", ["admin"]),
]
ROLE_KEYS = {
    Role.ADMIN: "help.role.admin",
    Role.PROFESSOR: "help.role.professor",
    Role.TA: "help.role.ta",
}


@dataclass
class Viewer:
    """The sender's roles, looked up once per !help (not once per listed command)."""
    admin: bool
    professor: bool
    staff: bool

    def sees(self, role: Role | None) -> bool:
        if role is None or self.admin:
            return True
        if role == Role.ADMIN:
            return False
        if role == Role.PROFESSOR:
            return self.professor
        return self.professor or self.staff


class HelpCommands(CommandGroup):
    async def viewer(self, sender: str) -> Viewer:
        store = self.bot.store
        return Viewer(
            admin=self.bot.authz.is_admin(sender),
            professor=await store.is_professor(sender),
            staff=await store.is_staff_anywhere(sender),
        )

    @command("help", usage="usage.help", role=None, needs=())
    async def help(self, evt: MessageEvent, args: str) -> None:
        """No arguments: overview of the commands the sender's roles allow.
        `<command>`: that command's subcommands (or its full help if it has none).
        `<command> <sub>`: full help with arguments, example and next steps."""
        viewer = await self.viewer(evt.sender)
        words = [w.lower().lstrip("!") for w in split_args(args).positionals]
        if not words:
            await self.reply_text(evt, self.overview(viewer))
            return
        name, sub = words[0], (words[1] if len(words) > 1 else None)
        specs = [s for s in self.bot.router.specs if s.name == name]
        if not specs:
            await self.reply(evt, "msg.help_unknown", name=name)
            return
        if sub is not None:
            match = [s for s in specs if s.sub == sub]
            if not match:
                await self.reply_text(evt, self.bot.router.missing_subcommand(name, sub))
                return
            specs = match
        visible = [s for s in specs if viewer.sees(s.role)]
        if not visible:
            await self.reply(evt, "msg.help_not_for_you", command=specs[0].label if sub else name,
                             role=t(ROLE_KEYS.get(specs[0].role, "help.role.any")))
            return
        if len(visible) == 1:
            await self.reply_text(evt, self.details(visible[0]))
        else:
            await self.reply_text(evt, self.group(name, visible))

    def overview(self, viewer: Viewer) -> str:
        lines = [t("msg.help_header")]
        for heading, names in AREAS:
            specs = [s for s in self.bot.router.specs if s.name in names and viewer.sees(s.role)]
            if not specs:
                continue
            lines.append(f"\n**{t(heading)}**")
            lines.extend(f"- {t(s.usage)}" for s in specs)
        lines.append("\n" + t("msg.help_footer"))
        return "\n".join(lines)

    def group(self, name: str, specs: list[CommandSpec]) -> str:
        lines = [t(f"help.group.{name}"), ""]
        lines.extend(f"- {t(s.usage)}" for s in specs)
        lines.append("\n" + t("msg.help_group_footer", name=name, example=specs[0].sub or ""))
        return "\n".join(lines)

    @staticmethod
    def details(spec: CommandSpec) -> str:
        return f"{t(spec.usage)}\n\n{t(spec.help_key)}"

    @command("whoami", usage="usage.whoami", role=None, needs=())
    async def whoami(self, evt: MessageEvent, args: str) -> None:
        roles = await self.bot.authz.roles(evt.sender)
        await self.reply(
            evt, "msg.whoami", user_id=evt.sender,
            roles=", ".join(roles["global"]) or "-",
            courses=", ".join(roles["courses"]) or "-",
        )
