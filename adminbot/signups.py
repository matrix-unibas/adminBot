"""Signup and password-reset links, and reset codes (plan §4). Shared by the !signup/!invite/
!password commands and the webapp.

Tokens: 32 random bytes, URL-safe; only the SHA-256 hash is stored; single use.
Signup links expire after signup.token_ttl_days, reset links from an admin after
signup.reset_ttl_hours, reset links a user asked for themselves (!password) after
password.self_ttl_minutes. A user may have several open signup links (e.g. from two
professors); the first one used creates the account, applies ALL pending invites and
invalidates the others.

Reset codes: one per account, 20 Crockford base32 characters (100 bits), only the SHA-256 is
stored. Shown once at signup or by `!password code`; with it, the /recover page sets a new
password without anyone else being involved, and then shows a new code.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import hmac
import logging
import re
import secrets

from mautrix.types import UserID

from .audit import Audit
from .config import Config
from .db import PendingInvite, SignupToken, Store
from .delivery import SignupLink
from .errors import NotFound, ValidationError
from .matrix_ops import MatrixOps
from .notices import Notices
from .strings import t
from .synapse_admin import SynapseAdmin

log = logging.getLogger("maubot.adminbot.signups")


# Crockford base32: no I, L, O, U, so codes read aloud or copied by hand stay unambiguous.
RESET_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
RESET_CODE_LENGTH = 20
RESET_CODE_GROUP = 4
_CODE_LOOKALIKES = str.maketrans("ILO", "110")


class TokenKind(str, Enum):
    SIGNUP = "signup"
    RESET = "reset"


def new_token() -> tuple[str, str]:
    """(raw token for the link, sha256 hex for the DB)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_reset_code() -> str:
    """'7KQ2-M9XD-...' (5 groups of 4)."""
    chars = "".join(secrets.choice(RESET_CODE_ALPHABET) for _ in range(RESET_CODE_LENGTH))
    return "-".join(chars[i:i + RESET_CODE_GROUP] for i in range(0, RESET_CODE_LENGTH, RESET_CODE_GROUP))


def normalize_reset_code(raw: str) -> str:
    """Ignore case, spaces and dashes; read I/L as 1 and O as 0."""
    return re.sub(r"[\s-]", "", raw).upper().translate(_CODE_LOOKALIKES)


def hash_reset_code(raw: str) -> str:
    return hash_token(normalize_reset_code(raw))


def check_password(password: str, confirm: str, min_length: int) -> str | None:
    """None if fine, otherwise a strings key. The admin API skips Synapse's password policy,
    so this is the only check."""
    if password != confirm:
        return "web.error.password_mismatch"
    if len(password) < min_length:
        return "web.error.password_short"
    return None


class SignupService:
    def __init__(self, store: Store, synapse: SynapseAdmin, ops: MatrixOps, audit: Audit, config: Config,
                 notices: Notices) -> None:
        self.store = store
        self.synapse = synapse
        self.ops = ops
        self.audit = audit
        self.config = config
        self.notices = notices

    def link_for(self, raw_token: str, kind: TokenKind) -> str:
        base = (self.config["signup.public_base_url"] or "").rstrip("/")
        if not base:
            raise ValidationError("err.no_public_url")
        return f"{base}/{kind.value}?t={raw_token}"

    @property
    def recover_url(self) -> str:
        """The page where a reset code is used."""
        base = (self.config["signup.public_base_url"] or "").rstrip("/")
        if not base:
            raise ValidationError("err.no_public_url")
        return f"{base}/recover"

    async def _issue(self, kind: TokenKind, user_id: UserID, emails: list[str], created_by: UserID,
                     course: str | None, ttl: timedelta) -> SignupLink:
        raw, token_hash = new_token()
        now = datetime.now(timezone.utc)
        link = self.link_for(raw, kind)
        await self.store.add_token(SignupToken(
            token_hash=token_hash, kind=kind.value, user_id=user_id, emails=emails, course=course,
            created_by=created_by, created_at=now, expires_at=now + ttl, used_at=None,
        ))
        return SignupLink(email=", ".join(emails), user_id=user_id, link=link, course=course, kind=kind.value)

    @property
    def signup_ttl(self) -> timedelta:
        return timedelta(days=self.config["signup.token_ttl_days"])

    async def create(self, user_id: UserID, emails: list[str], created_by: UserID,
                     course: str | None = None) -> SignupLink:
        """New signup link plus a pending invite for `course`. Fails if the account exists."""
        if await self.synapse.user_exists(user_id):
            raise ValidationError("err.account_exists", user_id=user_id)
        if course:
            await self.store.add_pending_invite(PendingInvite(
                user_id=user_id, course=course, mode=self.config["invites.mode_new"], created_by=created_by,
            ))
        return await self._issue(TokenKind.SIGNUP, user_id, emails, created_by, course, self.signup_ttl)

    async def renew(self, user_id: UserID, by: UserID) -> SignupLink:
        """New link, old ones invalid; keeps emails (merged) and course of the newest."""
        tokens = await self.store.tokens_for(user_id, TokenKind.SIGNUP.value)
        if not tokens:
            raise NotFound("err.no_open_link", user_id=user_id)
        emails: list[str] = []
        for token in tokens:
            emails.extend(e for e in token.emails if e not in emails)
        await self.store.delete_tokens_for(user_id, TokenKind.SIGNUP.value)
        link = await self._issue(TokenKind.SIGNUP, user_id, emails, by, tokens[-1].course, self.signup_ttl)
        await self.audit.log(by, "signup.renew", course=tokens[-1].course, target_count=1)
        return link

    async def revoke(self, user_id: UserID, by: UserID) -> int:
        """Delete all open signup links and pending invites of the user."""
        count = await self.store.delete_tokens_for(user_id, TokenKind.SIGNUP.value)
        await self.store.delete_pending_invites(user_id)
        if count:
            await self.audit.log(by, "signup.revoke", target_count=1)
        return count

    async def open_tokens(self, user_id: UserID) -> list[SignupToken]:
        return await self.store.tokens_for(user_id, TokenKind.SIGNUP.value)

    async def list_open(self, course: str | None = None) -> list[SignupToken]:
        return await self.store.list_open_tokens(TokenKind.SIGNUP.value, course)

    async def create_reset(self, user_id: UserID, by: UserID) -> SignupLink:
        """Admins only (checked by the command). The account must exist. Audited."""
        if not await self.synapse.user_exists(user_id):
            raise NotFound("err.user_not_found", user_id=user_id)
        await self.store.delete_tokens_for(user_id, TokenKind.RESET.value)
        ttl = timedelta(hours=self.config["signup.reset_ttl_hours"])
        link = await self._issue(TokenKind.RESET, user_id, [], by, None, ttl)
        await self.audit.log(by, "reset.create", target_count=1)
        return link

    async def create_self_reset(self, user_id: UserID) -> SignupLink:
        """!password: a reset link for the sender's own account. created_by == user_id marks it as
        self-issued, so redeeming it keeps the user's sessions (they proved they hold one)."""
        await self.store.delete_tokens_for(user_id, TokenKind.RESET.value)
        ttl = timedelta(minutes=self.config["password.self_ttl_minutes"])
        link = await self._issue(TokenKind.RESET, user_id, [], user_id, None, ttl)
        await self.audit.log(user_id, "password.self", target_count=1)
        return link

    async def issue_reset_code(self, user_id: UserID) -> str:
        """A new reset code for user_id; any earlier one stops working. Returns the code (shown once)."""
        code = new_reset_code()
        await self.store.set_reset_code(user_id, hash_reset_code(code))
        return code

    async def recover(self, user_id: UserID, code: str, password: str) -> str:
        """/recover: check the code, set the password (all sessions logged out), issue a new code.
        Raises ValidationError("web.error.recover_invalid") for a wrong code or unknown user, without
        telling which. Returns the new code."""
        stored = await self.store.get_reset_code(user_id)
        if stored is None or not hmac.compare_digest(stored, hash_reset_code(code)):
            raise ValidationError("web.error.recover_invalid")
        if not await self.store.burn_reset_code(user_id, stored):
            raise ValidationError("web.error.recover_invalid")
        try:
            await self.synapse.reset_password(user_id, password, logout_devices=True)
        except Exception:
            await self.store.set_reset_code(user_id, stored)
            raise
        await self.store.delete_tokens_for(user_id, TokenKind.RESET.value)
        new_code = await self.issue_reset_code(user_id)
        await self.audit.log(user_id, "reset.recover", target_count=1)
        await self.notices.send(user_id, "msg.password_recovered_notice")
        return new_code

    async def lookup(self, raw_token: str, kind: TokenKind) -> SignupToken | None:
        """Valid = right kind, unused, not expired."""
        if not raw_token or len(raw_token) > 100:
            return None
        token = await self.store.get_token(hash_token(raw_token))
        if (
            token is None
            or token.kind != kind.value
            or token.used_at is not None
            or token.expires_at <= datetime.now(timezone.utc)
        ):
            return None
        return token

    async def redeem_signup(self, raw_token: str, displayname: str, password: str) -> UserID:
        """1. burn token (atomic) 2. create user (+threepids) 3. apply pending invites 4. audit.
        If creating the user fails, the token is un-burned so the link keeps working."""
        token = await self.lookup(raw_token, TokenKind.SIGNUP)
        if token is None or not await self.store.burn_token(token.token_hash):
            raise ValidationError("web.error.invalid")
        try:
            emails = token.emails if self.config["identity.bind_threepids"] else None
            await self.synapse.create_user(token.user_id, password, displayname.strip() or None, emails)
        except Exception:
            await self.store.unburn_token(token.token_hash)
            raise
        await self.store.delete_tokens_for(token.user_id, TokenKind.SIGNUP.value)
        await self.audit.log(token.user_id, "signup.redeem", course=token.course, target_count=1)
        try:
            await self.apply_pending_invites(token.user_id)
        except Exception:
            log.exception(f"Applying pending invites for {token.user_id} failed")
        await self.notices.send(token.user_id, "msg.welcome", **self.welcome_params())
        return token.user_id

    def welcome_params(self) -> dict[str, str]:
        if not self.config["password.reset_codes"]:
            return {"reset_code_hint": ""}
        try:
            return {"reset_code_hint": t("msg.welcome_reset_code", url=self.recover_url)}
        except ValidationError:
            return {"reset_code_hint": ""}

    @staticmethod
    def is_self_reset(token: SignupToken) -> bool:
        """A link the user asked for with !password (not one an admin created for them)."""
        return token.created_by == token.user_id

    async def redeem_reset(self, raw_token: str, password: str) -> UserID:
        """Admin links log all sessions out (the person may have lost them); links from !password
        keep them, so the session that asked keeps its encryption keys."""
        token = await self.lookup(raw_token, TokenKind.RESET)
        if token is None or not await self.store.burn_token(token.token_hash):
            raise ValidationError("web.error.invalid")
        self_reset = self.is_self_reset(token)
        try:
            await self.synapse.reset_password(token.user_id, password, logout_devices=not self_reset)
        except Exception:
            await self.store.unburn_token(token.token_hash)
            raise
        await self.store.delete_tokens_for(token.user_id, TokenKind.RESET.value)
        await self.audit.log(token.created_by, "reset.redeem", target_count=1)
        if self_reset:
            await self.notices.send(token.user_id, "msg.password_self_notice")
        else:
            await self.notices.send(token.user_id, "msg.password_reset_notice", admin=token.created_by)
        return token.user_id

    async def apply_pending_invites(self, user_id: UserID) -> None:
        """force_join: into the space and every non-staff, non-group room.
        invite: an invitation to the space (restricted rooms open after accepting)."""
        for invite in await self.store.pending_invites(user_id):
            course = await self.store.get_course(invite.course)
            if course is None or course.archived:
                continue
            if invite.mode == "force_join":
                await self.synapse.force_join(user_id, course.space_id)
                for room_id in await self.ops.children(course.space_id):
                    tag = await self.ops.tag(room_id) or {}
                    if tag.get("kind") == "room" and tag.get("members", "all") == "all":
                        try:
                            await self.synapse.force_join(user_id, room_id)
                        except Exception as e:
                            log.warning(f"Force-join of {user_id} into {room_id} failed: {e}")
            else:
                await self.ops.invite(course.space_id, user_id)
        await self.store.delete_pending_invites(user_id)

    async def expire(self) -> int:
        return await self.store.expire_tokens()
