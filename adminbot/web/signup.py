"""Signup, password-reset and recover pages (plan §4)."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import TYPE_CHECKING

from aiohttp.web import Request, Response
from maubot.handlers import web

from ..errors import ValidationError
from ..identity import user_id_for_login
from ..signups import TokenKind, check_password, hash_reset_code, hash_token
from ..strings import t
from . import pages
from .ratelimit import FailureCounter, RateLimiter, client_ip, parse_networks

if TYPE_CHECKING:
    from ..bot import AdminBot

log = logging.getLogger("maubot.adminbot.web")

# How long a /recover form stays valid (its CSRF nonce carries the time it was issued).
RECOVER_FORM_TTL = 3600
# How long the "save your reset code" steps stay usable after the code was shown.
CODE_STEPS_TTL = 3600
# What the reset-code steps follow: the final page differs.
CODE_STEPS_AFTER = ("signup", "reset")

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class SignupWeb:
    def __init__(self, bot: AdminBot) -> None:
        self.bot = bot
        self.limiter = RateLimiter(
            bot.config["signup.rate_limit.per_ip_per_hour"], bot.config["signup.rate_limit.global_per_hour"]
        )
        self.trusted = parse_networks(bot.config["signup.trusted_proxies"])
        self.nonce_key = secrets.token_bytes(32)
        self.code_failures = FailureCounter(bot.config["password.max_code_attempts"])

    @property
    def min_length(self) -> int:
        return self.bot.config["signup.min_password_length"]

    def nonce_for(self, token_hash: str) -> str:
        """HMAC of the token hash with a per-start random key (CSRF protection)."""
        return hmac.new(self.nonce_key, token_hash.encode(), hashlib.sha256).hexdigest()[:32]

    def recover_nonce(self, issued: int | None = None) -> str:
        """'<issued>.<hmac>': /recover has no token to bind a nonce to, so it is bound to the time."""
        issued = int(time.time()) if issued is None else issued
        sig = hmac.new(self.nonce_key, f"recover:{issued}".encode(), hashlib.sha256).hexdigest()[:32]
        return f"{issued}.{sig}"

    def recover_nonce_valid(self, nonce: str) -> bool:
        issued = self._issued(nonce, RECOVER_FORM_TTL)
        return issued is not None and hmac.compare_digest(nonce, self.recover_nonce(issued))

    def code_nonce(self, user_id: str, after: str, code_hash: str, issued: int | None = None) -> str:
        """'<issued>.<hmac>' bound to the account, the step's context and the reset code shown.
        Only the browser that just set the password has it. The steps keep the first issue time,
        so the page dies CODE_STEPS_TTL after the code was first shown, however often it is
        used; and any other code change (!password code, /recover) makes it invalid at once."""
        issued = int(time.time()) if issued is None else issued
        msg = f"code:{after}:{user_id}:{issued}:{code_hash}".encode()
        return f"{issued}.{hmac.new(self.nonce_key, msg, hashlib.sha256).hexdigest()[:32]}"

    def code_nonce_issued(self, nonce: str, user_id: str, after: str, code_hash: str | None) -> int | None:
        """The nonce's issue time if it is valid for the user's current code, else None."""
        issued = self._issued(nonce, CODE_STEPS_TTL)
        if issued is None or code_hash is None:
            return None
        return issued if hmac.compare_digest(nonce, self.code_nonce(user_id, after, code_hash, issued)) else None

    @staticmethod
    def _issued(nonce: str, ttl: int) -> int | None:
        """The time in a '<issued>.<hmac>' nonce, if it is no older than ttl seconds."""
        try:
            issued = int(nonce.partition(".")[0])
        except ValueError:
            return None
        return issued if 0 <= time.time() - issued <= ttl else None

    @staticmethod
    def html(body: str, status: int = 200) -> Response:
        return Response(text=body, status=status, content_type="text/html", charset="utf-8",
                         headers=SECURITY_HEADERS)

    def _limited(self, request: Request) -> Response | None:
        if not self.limiter.allow(client_ip(request, self.trusted)):
            return self.html(pages.error_page("web.error.rate_limited"), 429)
        return None

    async def _form(self, request: Request, kind: TokenKind) -> Response:
        limited = self._limited(request)
        if limited:
            return limited
        raw = request.query.get("t", "")
        token = await self.bot.signups.lookup(raw, kind)
        if token is None:
            return self.html(pages.error_page("web.error.invalid"), 400)
        nonce = self.nonce_for(token.token_hash)
        if kind == TokenKind.SIGNUP:
            return self.html(pages.signup_form(token.user_id, raw, nonce, self.min_length))
        return self.html(pages.reset_form(token.user_id, raw, nonce, self.min_length,
                                          self_service=self.bot.signups.is_self_reset(token)))

    async def _submit(self, request: Request, kind: TokenKind) -> Response:
        limited = self._limited(request)
        if limited:
            return limited
        form = await request.post()
        raw = str(form.get("t", ""))
        token = await self.bot.signups.lookup(raw, kind)
        if token is None or not hmac.compare_digest(str(form.get("nonce", "")), self.nonce_for(hash_token(raw))):
            return self.html(pages.error_page("web.error.invalid"), 400)
        password, confirm = str(form.get("password", "")), str(form.get("confirm", ""))
        displayname = str(form.get("displayname", ""))[:100]
        error_key = check_password(password, confirm, self.min_length)
        nonce = self.nonce_for(token.token_hash)
        if error_key:
            error = t(error_key, n=self.min_length)
            if kind == TokenKind.SIGNUP:
                body = pages.signup_form(token.user_id, raw, nonce, self.min_length, error, displayname)
            else:
                body = pages.reset_form(token.user_id, raw, nonce, self.min_length, error,
                                        self_service=self.bot.signups.is_self_reset(token))
            return self.html(body, 400)
        login_url = self.bot.config["signup.login_url"]
        try:
            if kind == TokenKind.SIGNUP:
                user_id = await self.bot.signups.redeem_signup(raw, displayname, password)
                code = await self._new_code(user_id)
                if code:
                    nonce = self.code_nonce(user_id, "signup", hash_reset_code(code))
                    return self.html(pages.show_code(user_id, code, nonce, "signup"))
                return self.html(self.final_page(user_id, "signup"))
            self_reset = self.bot.signups.is_self_reset(token)
            user_id = await self.bot.signups.redeem_reset(raw, password)
            return self.html(pages.done(user_id, login_url, "web.done_reset",
                                        note_key=None if self_reset else "web.done_verify"))
        except ValidationError as e:
            log.info(f"{kind.value} for {token.user_id} refused: {e.key}")
            return self.html(pages.error_page("web.error.invalid"), 400)
        except Exception:
            log.exception(f"{kind.value} for {token.user_id} failed")
            return self.html(pages.error_page("web.error.generic"), 500)

    async def _new_code(self, user_id: str) -> str | None:
        """The first reset code, shown on the signup success page. A failure only costs the code
        (the user can get one with `!password code`), not the account."""
        if not self.bot.config["password.reset_codes"]:
            return None
        try:
            return await self.bot.signups.issue_reset_code(user_id)
        except Exception:
            log.exception(f"Couldn't create a reset code for {user_id}")
            return None

    def _recover_disabled(self) -> Response | None:
        if not self.bot.config["password.reset_codes"]:
            return self.html(pages.error_page("web.error.recover_disabled"), 404)
        return None

    @web.get("/recover")
    async def recover_form(self, request: Request) -> Response:
        blocked = self._recover_disabled() or self._limited(request)
        if blocked:
            return blocked
        return self.html(pages.recover_form(self.recover_nonce(), self.min_length))

    @web.post("/recover")
    async def recover_submit(self, request: Request) -> Response:
        """Order: rate limit, CSRF, account lock, password rules, then the code. Wrong code,
        unknown user and locked account all get the same answer."""
        blocked = self._recover_disabled() or self._limited(request)
        if blocked:
            return blocked
        form = await request.post()
        if not self.recover_nonce_valid(str(form.get("nonce", ""))):
            return self.html(pages.error_page("web.error.recover_expired"), 400)
        username = str(form.get("username", ""))[:255]
        nonce = self.recover_nonce()

        def again(error_key: str, status: int = 400) -> Response:
            error = t(error_key, n=self.min_length)
            return self.html(pages.recover_form(nonce, self.min_length, error, username), status)

        user_id = user_id_for_login(username, self.bot.server_name, self.bot.config["identity.allowed_domains"])
        if user_id is None or self.code_failures.locked(user_id):
            return again("web.error.recover_invalid")
        password, confirm = str(form.get("password", "")), str(form.get("confirm", ""))
        error_key = check_password(password, confirm, self.min_length)
        if error_key:
            return again(error_key)
        try:
            new_code = await self.bot.signups.recover(user_id, str(form.get("code", ""))[:64], password)
        except ValidationError:
            self.code_failures.fail(user_id)
            log.info(f"Wrong reset code for {user_id}")
            return again("web.error.recover_invalid")
        except Exception:
            log.exception(f"Recover for {user_id} failed")
            return self.html(pages.error_page("web.error.generic"), 500)
        nonce = self.code_nonce(user_id, "reset", hash_reset_code(new_code))
        return self.html(pages.show_code(user_id, new_code, nonce, "reset"))

    def final_page(self, user_id: str, after: str) -> str:
        login_url = self.bot.config["signup.login_url"]
        if after == "signup":
            return pages.done(user_id, login_url, note_key="web.done_recovery_key")
        return pages.done(user_id, login_url, "web.done_reset", note_key="web.done_verify")

    @web.post("/code")
    async def code_submit(self, request: Request) -> Response:
        """The steps after a reset code was shown (signup, /recover), so nobody clicks past it:
        action 'ask' shows the field to type the saved code back in, 'check' compares it (and
        then shows the final page), 'new' replaces the code and shows it again."""
        blocked = self._recover_disabled() or self._limited(request)
        if blocked:
            return blocked
        form = await request.post()
        user_id, after = str(form.get("user", ""))[:255], str(form.get("after", ""))
        nonce = str(form.get("nonce", ""))
        issued = None
        if after in CODE_STEPS_AFTER:
            stored = await self.bot.store.get_reset_code(user_id)
            issued = self.code_nonce_issued(nonce, user_id, after, stored)
        if issued is None:
            return self.html(pages.error_page("web.error.code_expired"), 400)
        action = str(form.get("action", ""))
        if action == "new":
            code = await self.bot.signups.issue_reset_code(user_id)
            await self.bot.audit.log(user_id, "password.code", target_count=1)
            # Same issue time: a new code doesn't extend the page's life.
            nonce = self.code_nonce(user_id, after, hash_reset_code(code), issued)
            return self.html(pages.show_code(user_id, code, nonce, after))
        if action == "check":
            if await self.bot.signups.reset_code_matches(user_id, str(form.get("code", ""))[:64]):
                return self.html(self.final_page(user_id, after))
            return self.html(pages.confirm_code(user_id, nonce, after, t("web.error.code_mismatch")), 400)
        return self.html(pages.confirm_code(user_id, nonce, after))

    @web.get("/signup")
    async def signup_form(self, request: Request) -> Response:
        return await self._form(request, TokenKind.SIGNUP)

    @web.post("/signup")
    async def signup_submit(self, request: Request) -> Response:
        return await self._submit(request, TokenKind.SIGNUP)

    @web.get("/reset")
    async def reset_form(self, request: Request) -> Response:
        return await self._form(request, TokenKind.RESET)

    @web.post("/reset")
    async def reset_submit(self, request: Request) -> Response:
        return await self._submit(request, TokenKind.RESET)
