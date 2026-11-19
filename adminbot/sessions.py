"""Staff commands only from verified sessions (plan §3, 1.2.0).

A password alone is enough to log in a new session, and also enough to *Reset identity* in
Element (Synapse asks for the password before it accepts new cross-signing keys). Two checks
together make a stolen password useless for commanding the bot:

1. The command came encrypted, from a session that is cross-signed by its owner's current
   identity (mautrix trust state CROSS_SIGNED_*). A new session gets that only by verifying
   with an existing session or the recovery key.
2. That identity (the master cross-signing key) is the one the bot pinned when it first saw
   this user. An identity reset gives a new master key, so the commands stop until an admin
   accepts the new identity with `!admin identity accept @user`.

maubot wraps every message in a MaubotMessageEvent and drops mautrix's per-event trust
information on the way, so the check fetches the event again and decrypts it once more.
Decrypting the same event twice is allowed (same event ID, same message index); it relies
on mautrix not ratcheting or deleting keys on decrypt (`ratchet_keys_on_decrypt` and friends,
off in maubot 0.6.0). Public commands (!help, !password) are not checked.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from mautrix.client.api.events import EventMethods
from mautrix.types import CrossSigningUsage, EncryptedEvent, EventID, RoomID, TrustState, UserID

from .errors import ValidationError
from .strings import t

if TYPE_CHECKING:
    from .bot import AdminBot

log = logging.getLogger("maubot.adminbot.sessions")


@dataclass(frozen=True)
class SenderSession:
    encrypted: bool
    trust: TrustState | None = None
    master_key: str | None = None  # the sender's current master cross-signing key


def fingerprint(key: str | None) -> str:
    """Groups of four, like Element shows keys: `abcd efgh ...`."""
    if not key:
        return "-"
    return " ".join(key[i:i + 4] for i in range(0, len(key), 4))


class SessionCheck:
    def __init__(self, bot: AdminBot) -> None:
        self.bot = bot
        self._warned: dict[UserID, str] = {}  # last changed key reported per user (no audit spam)

    @property
    def enabled(self) -> bool:
        return bool(self.bot.config["security.verified_sessions"])

    async def inspect(self, room_id: RoomID, event_id: EventID, sender: UserID) -> SenderSession:
        crypto = self.bot.client.crypto
        if crypto is None:
            return SenderSession(encrypted=False)
        # The plain client method: maubot's override decrypts and wraps again.
        evt = await EventMethods.get_event(self.bot.client, room_id, event_id)
        if not isinstance(evt, EncryptedEvent):
            return SenderSession(encrypted=False)
        try:
            decrypted = await crypto.decrypt_megolm_event(evt)
            trust = TrustState(decrypted["mautrix"]["trust_state"])
        except Exception as e:
            log.warning(f"Couldn't check the session of {sender} ({event_id}): {e}")
            return SenderSession(encrypted=True, trust=TrustState.UNVERIFIED)
        keys = await crypto.crypto_store.get_cross_signing_keys(sender)
        master = keys.get(CrossSigningUsage.MASTER)
        return SenderSession(encrypted=True, trust=trust, master_key=str(master.key) if master else None)

    async def require(self, room_id: RoomID, event_id: EventID, sender: UserID) -> None:
        """Raises ValidationError with what the sender has to do."""
        if not self.enabled:
            return
        session = await self.inspect(room_id, event_id, sender)
        if not session.encrypted:
            raise ValidationError("err.session_unencrypted")
        trust = session.trust or TrustState.UNVERIFIED
        if trust < TrustState.CROSS_SIGNED_UNTRUSTED:
            raise ValidationError("err.session_unverified")
        if session.master_key is None:
            # VERIFIED without cross-signing keys: verified by the bot's own device directly.
            if trust >= TrustState.VERIFIED:
                return
            raise ValidationError("err.session_unverified")
        pinned = await self.bot.store.get_identity(sender)
        if pinned is None:
            await self.bot.store.pin_identity(sender, session.master_key, None)
            await self.bot.audit.log(sender, "identity.pin", target_count=1)
            return
        if pinned == session.master_key:
            return
        if self._warned.get(sender) != session.master_key:
            self._warned[sender] = session.master_key
            await self.bot.audit.post(t("msg.identity_changed_audit", user_id=sender,
                                        old=fingerprint(pinned), new=fingerprint(session.master_key)))
        raise ValidationError("err.identity_changed")

    async def current_master_key(self, user_id: UserID) -> str | None:
        crypto = self.bot.client.crypto
        if crypto is None:
            return None
        keys = await crypto.crypto_store.get_cross_signing_keys(user_id)
        master = keys.get(CrossSigningUsage.MASTER)
        return str(master.key) if master else None
