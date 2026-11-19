"""!admin: professor allowlist, audit, professor-bot approval, pinned identities. Admins only."""
from __future__ import annotations

from maubot import MessageEvent
from mautrix.types import UserID

from ..audit import format_entry
from ..authz import Role
from ..errors import NotFound, ValidationError
from ..parsing import ArgError, split_args
from ..sessions import fingerprint
from ..strings import t
from .base import CommandGroup, command


class AdminCommands(CommandGroup):
    @command("admin", "prof", usage="usage.admin.prof", role=Role.ADMIN)
    async def prof(self, evt: MessageEvent, args: str) -> None:
        await self.require(evt, Role.ADMIN)
        usage = t("usage.admin.prof")
        a = split_args(args, usage=usage)
        action = (a.get(0) or "list").lower()
        if action == "list":
            profs = await self.bot.store.list_professors()
            await self.reply(evt, "msg.prof_list", users="\n".join(f"- {p}" for p in profs) or "-")
            return
        if action not in ("add", "remove"):
            raise ArgError("err.bad_args", usage=usage)
        user = self.user_arg(a.get(1))
        if action == "add":
            if not await self.bot.synapse.user_exists(user):
                raise NotFound("err.user_not_found", user_id=user)
            added = await self.bot.store.add_professor(user, evt.sender)
            if added:
                await self.bot.audit.log(evt.sender, "professor.add", target_count=1)
            await self.reply(evt, "msg.prof_added" if added else "msg.prof_already", user_id=user)
            if added:
                await self.bot.notices.tell(user, evt.sender, "msg.notice.prof_added")
        else:
            removed = await self.bot.store.remove_professor(user)
            if removed:
                await self.bot.audit.log(evt.sender, "professor.remove", target_count=1)
            key = "msg.prof_removed" if removed else "msg.prof_not_listed"
            await self.reply(evt, key, user_id=user)
            if user in (self.bot.config["professors"] or []):
                await self.reply(evt, "msg.prof_in_config", user_id=user)
            if removed:
                await self.bot.notices.tell(user, evt.sender, "msg.notice.prof_removed")

    @command("admin", "audit", usage="usage.admin.audit", role=Role.ADMIN, needs=())
    async def audit(self, evt: MessageEvent, args: str) -> None:
        await self.require(evt, Role.ADMIN)
        a = split_args(args, usage=t("usage.admin.audit"))
        try:
            n = max(1, min(100, int(a.get(0) or 20)))
        except ValueError as e:
            raise ArgError("err.bad_args", usage=t("usage.admin.audit")) from e
        entries = await self.bot.audit.recent(n)
        lines = [f"- {e.ts:%Y-%m-%d %H:%M} {format_entry(e)}" for e in entries]
        await self.reply(evt, "msg.audit_list", entries="\n".join(lines) or "-")

    @command("admin", "bots", usage="usage.admin.bots", role=Role.ADMIN, needs=("admin", "userbots"))
    async def bots(self, evt: MessageEvent, args: str) -> None:
        await self.require(evt, Role.ADMIN)
        if self.bot.bots is None:
            raise ValidationError("err.bots_disabled")
        usage = t("usage.admin.bots")
        a = split_args(args, usage=usage)
        action = (a.get(0) or "pending").lower()
        if action == "pending":
            requests = await self.bot.store.pending_bot_requests()
            lines = [
                t("msg.bot_request_line", id=r.id, owner=r.owner, name=r.name, action=r.action,
                  plugin_id=r.plugin_id, version=r.version)
                for r in requests
            ]
            await self.reply(evt, "msg.bot_requests", requests="\n".join(lines) or "-")
        elif action == "show":
            try:
                request_id = int(a.get(1) or "")
            except ValueError as e:
                raise ArgError("err.bad_args", usage=usage) from e
            request, findings, changes = await self.bot.bots.show(request_id)
            await self.reply_file(evt, f"{request.plugin_id}-v{request.version}.mbp", request.mbp, "application/zip")
            if changes:
                await self.reply_file(evt, changes[0], changes[1].encode("utf-8"), "text/x-diff")
            await self.reply(evt, "msg.bot_review_full", id=request.id, name=request.name, owner=request.owner,
                             version=request.version, findings=findings,
                             diff=t("msg.bot_review_diff_sent") if changes else "")
        elif action in ("approve", "reject"):
            try:
                request_id = int(a.get(1) or "")
            except ValueError as e:
                raise ArgError("err.bad_args", usage=usage) from e
            if action == "approve":
                job_id = await self.bot.bots.approve(request_id, evt.sender)
                await self.reply(evt, "msg.bot_approved", id=request_id, job=job_id)
            else:
                reason = " ".join(a.positionals[2:]) or None
                await self.bot.bots.reject(request_id, evt.sender, reason)
                await self.reply(evt, "msg.bot_rejected_admin", id=request_id)
        elif action == "disable-all":
            running: dict[UserID, list[str]] = {}
            for b in await self.bot.store.list_user_bots():
                if b.state == "running":
                    running.setdefault(b.owner, []).append(f"`{b.name}`")
            count = await self.bot.bots.disable_all()
            await self.bot.audit.log(evt.sender, "bot.disable_all", target_count=count)
            await self.reply(evt, "msg.bots_disabled_all", count=count)
            for owner, names in running.items():
                await self.bot.notices.tell(owner, evt.sender, "msg.notice.bots_disabled_all",
                                            bots=", ".join(names))
        else:
            raise ArgError("err.bad_args", usage=usage)

    @command("admin", "identity", usage="usage.admin.identity", role=Role.ADMIN, needs=())
    async def identity(self, evt: MessageEvent, args: str) -> None:
        """Staff commands are accepted from one identity per user (sessions.py). After a
        legitimate "Reset identity" an admin accepts the new one, having checked with the
        person (in person or by phone) that they reset it themselves."""
        await self.require(evt, Role.ADMIN)
        usage = t("usage.admin.identity")
        a = split_args(args, usage=usage)
        accept = (a.get(0) or "").lower() == "accept"
        user = self.user_arg(a.get(1) if accept else a.get(0))
        pinned = await self.bot.store.get_identity(user)
        current = await self.bot.sessions.current_master_key(user)
        if not accept:
            if current is None:
                state = t("msg.identity_state_none")
            elif pinned is None:
                state = t("msg.identity_state_unpinned")
            elif pinned == current:
                state = t("msg.identity_state_ok")
            else:
                state = t("msg.identity_state_changed", user_id=user)
            await self.reply(evt, "msg.identity_show", user_id=user, pinned=fingerprint(pinned),
                             current=fingerprint(current), state=state)
            return
        if current is None:
            raise ValidationError("err.identity_none", user_id=user)
        if current == pinned:
            await self.reply(evt, "msg.identity_already", user_id=user)
            return
        await self.bot.store.pin_identity(user, current, evt.sender)
        await self.bot.audit.log(evt.sender, "identity.accept", target_count=1)
        await self.bot.audit.post(t("msg.identity_accepted_audit", user_id=user, actor=evt.sender,
                                    fingerprint=fingerprint(current)))
        await self.reply(evt, "msg.identity_accepted", user_id=user, fingerprint=fingerprint(current))
        await self.bot.notices.tell(user, evt.sender, "msg.notice.identity_accepted")
