"""!password and !password code: self-service for every user of the server (plan §4, v7).

Public commands: students can use them too. A command in the DM proves the sender holds a
logged-in session of the account, which is all a reset for their *own* account needs.
"""
from __future__ import annotations

from maubot import MessageEvent

from ..errors import ValidationError
from ..identity import is_bot_account
from .base import CommandGroup, command


class PasswordCommands(CommandGroup):
    def _check(self, evt: MessageEvent, setting: str, disabled_key: str) -> None:
        if not self.bot.config[setting]:
            raise ValidationError(disabled_key)
        if is_bot_account(evt.sender):
            # A professor bot's password is random and nobody needs it (plan §10).
            raise ValidationError("err.password_bot")

    @command("password", usage="usage.password", role=None, public=True)
    async def link(self, evt: MessageEvent, args: str) -> None:
        """A reset link for the sender's own account. Sessions stay logged in."""
        if args.strip():
            await self.reply_text(evt, self.bot.router.missing_subcommand("password", args.split()[0].lower()))
            return
        self._check(evt, "password.self_service", "err.password_self_disabled")
        link = await self.bot.signups.create_self_reset(evt.sender)
        await self.reply(evt, "msg.password_link_self", user_id=evt.sender, link=link.link,
                         minutes=self.bot.config["password.self_ttl_minutes"])

    @command("password", "code", usage="usage.password.code", role=None, public=True)
    async def code(self, evt: MessageEvent, args: str) -> None:
        """A new reset code; the old one stops working."""
        self._check(evt, "password.reset_codes", "err.reset_codes_disabled")
        url = self.bot.signups.recover_url
        code = await self.bot.signups.issue_reset_code(evt.sender)
        await self.bot.audit.log(evt.sender, "password.code", target_count=1)
        await self.reply(evt, "msg.reset_code", code=code, url=url, user_id=evt.sender)
