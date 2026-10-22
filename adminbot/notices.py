"""Messages to users who may have no device yet (plan §4, v7).

The bot's DMs are encrypted. A message sent while the user has no device (right after signup,
or after a password reset logged all sessions out) is encrypted for nobody and can never be
read. So these notices are stored and sent once the user has a device with uploaded keys:
right away if they already have one, otherwise from the cleanup loop.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from mautrix.types import UserID

from .db import Store
from .matrix_ops import MatrixOps
from .strings import t

log = logging.getLogger("maubot.adminbot.notices")


class Notices:
    def __init__(self, store: Store, ops: MatrixOps, max_age_days: int) -> None:
        self.store = store
        self.ops = ops
        self.max_age = timedelta(days=max_age_days)

    @staticmethod
    def render(key: str, params: dict[str, Any]) -> str:
        """Every notice may use {verify_hint} (what to do when Element asks to verify)."""
        return t(key, verify_hint=t("msg.verify_hint"), **params)

    async def send(self, user_id: UserID, key: str, **params: Any) -> None:
        """Queue a notice and deliver it at once if the user has a device. Never raises: the
        action the notice is about has already happened."""
        try:
            await self.store.add_notice(user_id, key, params)
        except Exception:
            log.exception(f"Couldn't queue notice {key} for {user_id}")
            return
        await self.deliver(user_id)

    async def deliver(self, user_id: UserID | None = None) -> int:
        """Send the held notices (of one user, or of everyone). Never raises; returns how many
        were sent. Notices older than notices.max_age_days are dropped unsent."""
        sent = 0
        ready: dict[UserID, bool] = {}
        cutoff = datetime.now(timezone.utc) - self.max_age
        try:
            notices = await self.store.pending_notices(user_id)
        except Exception:
            log.exception("Couldn't read held notices")
            return 0
        for notice in notices:
            try:
                if notice.created_at < cutoff:
                    log.info(f"Dropping notice {notice.key} for {notice.user_id}: no device after {self.max_age.days} days")
                    await self.store.delete_notice(notice.id)
                    continue
                if notice.user_id not in ready:
                    ready[notice.user_id] = await self.ops.has_device_keys(notice.user_id)
                if not ready[notice.user_id]:
                    continue
                room_id = await self.ops.open_dm(notice.user_id)
                await self.ops.send(room_id, self.render(notice.key, notice.params))
                await self.store.delete_notice(notice.id)
                sent += 1
            except Exception as e:
                log.warning(f"Couldn't send notice {notice.key} to {notice.user_id}: {e}")
        return sent
