"""Signup service, store details and the signup web pages."""
from datetime import datetime, timedelta, timezone
import re
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from adminbot.db import Course, SignupToken
from adminbot.errors import ValidationError
from adminbot.signups import TokenKind, hash_reset_code, hash_token
from adminbot.web.signup import SignupWeb

from .conftest import ADMIN, PROF, SERVER, STUDENT

NEW = f"@new:{SERVER}"
BASE = "https://example.com/_matrix/maubot/plugin/adminbot"


def raw_token(link) -> str:
    return parse_qs(urlparse(link.link).query)["t"][0]


async def make_course(bot):
    await bot.store.create_course(Course("CS101", "Intro", "HS26", f"!space:{SERVER}", PROF, False,
                                         datetime.now(timezone.utc)))


async def test_redeem_creates_account_and_applies_invites(bot):
    await make_course(bot)
    bot.synapse.user_exists = AsyncMock(return_value=False)
    bot.ops.children = AsyncMock(return_value=[f"!general:{SERVER}", f"!staff:{SERVER}"])
    bot.ops.tag = AsyncMock(side_effect=lambda room: {"kind": "room", "members": "staff" if "staff" in room else "all"})
    first = await bot.signups.create(NEW, ["new@unibas.ch"], PROF, "CS101")
    second = await bot.signups.create(NEW, ["new@stud.unibas.ch"], PROF, None)

    user_id = await bot.signups.redeem_signup(raw_token(first), "New Person", "correct horse battery")
    assert user_id == NEW
    bot.synapse.create_user.assert_awaited_once_with(NEW, "correct horse battery", "New Person", ["new@unibas.ch"])
    joined = [call.args for call in bot.synapse.force_join.await_args_list]
    assert joined == [(NEW, f"!space:{SERVER}"), (NEW, f"!general:{SERVER}")]
    # Single use, and the other open link for the same person is gone too.
    with pytest.raises(ValidationError):
        await bot.signups.redeem_signup(raw_token(first), "x", "correct horse battery")
    assert await bot.signups.lookup(raw_token(second), TokenKind.SIGNUP) is None
    assert await bot.store.pending_invites(NEW) == []


async def test_failed_account_creation_keeps_link_usable(bot):
    bot.synapse.user_exists = AsyncMock(return_value=False)
    link = await bot.signups.create(NEW, ["new@unibas.ch"], PROF)
    bot.synapse.create_user = AsyncMock(side_effect=RuntimeError("synapse down"))
    with pytest.raises(RuntimeError):
        await bot.signups.redeem_signup(raw_token(link), "", "correct horse battery")
    assert await bot.signups.lookup(raw_token(link), TokenKind.SIGNUP) is not None


async def test_reset_link_wrong_kind_and_expiry(bot):
    bot.synapse.reset_password = AsyncMock()
    link = await bot.signups.create_reset(NEW, PROF)
    assert await bot.signups.lookup(raw_token(link), TokenKind.SIGNUP) is None
    assert await bot.signups.redeem_reset(raw_token(link), "correct horse battery") == NEW
    bot.synapse.reset_password.assert_awaited_once_with(NEW, "correct horse battery", logout_devices=True)


def sent_texts(maubot_test_bot) -> list[str]:
    return [r.content.body for r in maubot_test_bot.responded if hasattr(r.content, "body")]


async def test_self_reset_keeps_sessions(bot, maubot_test_bot):
    bot.synapse.reset_password = AsyncMock()
    link = await bot.signups.create_self_reset(STUDENT)
    token = await bot.signups.lookup(raw_token(link), TokenKind.RESET)
    assert bot.signups.is_self_reset(token)
    assert token.expires_at - token.created_at == timedelta(minutes=60)
    await bot.signups.redeem_reset(raw_token(link), "correct horse battery")
    bot.synapse.reset_password.assert_awaited_once_with(STUDENT, "correct horse battery", logout_devices=False)
    assert any("a link you asked me for" in text for text in sent_texts(maubot_test_bot))


async def test_reset_notice_waits_for_a_device(bot, maubot_test_bot):
    """After an admin reset all devices are gone: the notice is held until one exists."""
    bot.synapse.reset_password = AsyncMock()
    bot.ops.has_device_keys = AsyncMock(return_value=False)
    link = await bot.signups.create_reset(STUDENT, ADMIN)
    await bot.signups.redeem_reset(raw_token(link), "correct horse battery")
    assert not any("was reset" in text for text in sent_texts(maubot_test_bot))
    assert [n.key for n in await bot.store.pending_notices()] == ["msg.password_reset_notice"]

    assert await bot.notices.deliver() == 0
    bot.ops.has_device_keys = AsyncMock(return_value=True)
    assert await bot.notices.deliver() == 1
    [text] = [t for t in sent_texts(maubot_test_bot) if "was reset" in t]
    assert ADMIN in text and "Reset identity" in text
    assert await bot.store.pending_notices() == []


async def test_old_notices_are_dropped(bot):
    bot.ops.has_device_keys = AsyncMock(return_value=False)
    await bot.notices.send(STUDENT, "msg.password_self_notice")
    await bot.store.db.execute("UPDATE pending_notice SET created_at=0")
    assert await bot.notices.deliver() == 0
    assert await bot.store.pending_notices() == []


async def test_signup_queues_welcome(bot, maubot_test_bot):
    bot.synapse.user_exists = AsyncMock(return_value=False)
    bot.ops.has_device_keys = AsyncMock(return_value=False)
    link = await bot.signups.create(NEW, ["new@unibas.ch"], PROF)
    await bot.signups.redeem_signup(raw_token(link), "", "correct horse battery")
    [notice] = await bot.store.pending_notices(NEW)
    assert notice.key == "msg.welcome"
    bot.ops.has_device_keys = AsyncMock(return_value=True)
    await bot.notices.deliver()
    [welcome] = [t for t in sent_texts(maubot_test_bot) if "Welcome" in t]
    assert "recovery key" in welcome and f"{BASE}/recover" in welcome and "!password code" in welcome


async def test_recover_with_reset_code(bot):
    bot.synapse.reset_password = AsyncMock()
    code = await bot.signups.issue_reset_code(STUDENT)
    with pytest.raises(ValidationError):
        await bot.signups.recover(STUDENT, "0000-0000-0000-0000-0000", "correct horse battery")
    with pytest.raises(ValidationError):
        await bot.signups.recover(NEW, code, "correct horse battery")
    # Case, spaces and dashes don't matter.
    new_code = await bot.signups.recover(STUDENT, code.lower().replace("-", " "), "correct horse battery")
    bot.synapse.reset_password.assert_awaited_once_with(STUDENT, "correct horse battery", logout_devices=True)
    assert new_code != code
    with pytest.raises(ValidationError):
        await bot.signups.recover(STUDENT, code, "correct horse battery")
    assert (await bot.store.recent_audit(1))[0].action == "reset.recover"
    assert [n.key for n in await bot.store.pending_notices()] == []  # device present: sent at once


async def test_recover_keeps_code_if_synapse_fails(bot):
    bot.synapse.reset_password = AsyncMock(side_effect=RuntimeError("synapse down"))
    code = await bot.signups.issue_reset_code(STUDENT)
    with pytest.raises(RuntimeError):
        await bot.signups.recover(STUDENT, code, "correct horse battery")
    bot.synapse.reset_password = AsyncMock()
    await bot.signups.recover(STUDENT, code, "correct horse battery")


async def test_expire_deletes_tokens_and_orphaned_invites(bot):
    await make_course(bot)
    bot.synapse.user_exists = AsyncMock(return_value=False)
    await bot.signups.create(NEW, ["new@unibas.ch"], PROF, "CS101")
    past = datetime.now(timezone.utc) - timedelta(days=1)
    await bot.store.add_token(SignupToken("h", "signup", f"@old:{SERVER}", ["old@unibas.ch"], None, PROF,
                                          past, past, None))
    assert await bot.signups.expire() == 1
    assert await bot.store.get_token("h") is None
    assert len(await bot.store.pending_invites(NEW)) == 1


async def test_store_rename_course(bot):
    await make_course(bot)
    await bot.store.add_staff("CS101", PROF, "owner")
    await bot.store.rename_course("CS101", "CS101-HS26")
    assert await bot.store.get_course("CS101") is None
    assert await bot.store.staff_role("CS101-HS26", PROF) == "owner"


@pytest.fixture
async def web_client(bot):
    pages = SignupWeb(bot)
    app = web.Application()
    app.router.add_get("/signup", pages.signup_form)
    app.router.add_post("/signup", pages.signup_submit)
    app.router.add_get("/reset", pages.reset_form)
    app.router.add_get("/recover", pages.recover_form)
    app.router.add_post("/recover", pages.recover_submit)
    app.router.add_post("/code", pages.code_submit)
    async with TestClient(TestServer(app)) as client:
        yield client, pages


async def test_signup_pages(bot, web_client):
    client, pages = web_client
    bot.synapse.user_exists = AsyncMock(return_value=False)
    raw = raw_token(await bot.signups.create(NEW, ["new@unibas.ch"], PROF))

    resp = await client.get(f"/signup?t={raw}")
    assert resp.status == 200 and NEW in await resp.text()
    assert resp.headers["Referrer-Policy"] == "no-referrer"

    nonce = pages.nonce_for(hash_token(raw))
    form = {"t": raw, "nonce": nonce, "displayname": "N", "password": "a" * 12, "confirm": "b" * 12}
    resp = await client.post(f"/signup?t={raw}", data=form)
    assert resp.status == 400 and "don&#x27;t match" in await resp.text()

    resp = await client.post(f"/signup?t={raw}", data={**form, "nonce": "forged", "confirm": "a" * 12})
    assert resp.status == 400 and "invalid" in await resp.text()

    resp = await client.post(f"/signup?t={raw}", data={**form, "confirm": "a" * 12})
    text = await resp.text()
    assert resp.status == 200 and "account is created" in text and "Step 1 of 2" in text
    bot.synapse.create_user.assert_awaited_once()
    # The first reset code is shown once; the account is only "ready" after it was typed back in.
    code = shown_code(text)
    assert await bot.store.get_reset_code(NEW) == hash_reset_code(code)
    assert "not Element&#x27;s recovery key" in text
    text = await walk_code_steps(client, pages, NEW, "signup", code)
    assert "ready" in text and "set up recovery" in text

    resp = await client.get(f"/signup?t={raw}")
    assert resp.status == 400


async def test_signup_page_rate_limit(bot, web_client):
    client, pages = web_client
    pages.limiter.per_ip_per_hour = 2
    statuses = [(await client.get("/signup?t=nope")).status for _ in range(3)]
    assert statuses == [400, 400, 429]


async def test_reset_page_warning_depends_on_who_asked(bot, web_client):
    client, _ = web_client
    own = raw_token(await bot.signups.create_self_reset(STUDENT))
    assert "stay logged in" in await (await client.get(f"/reset?t={own}")).text()
    by_admin = raw_token(await bot.signups.create_reset(STUDENT, ADMIN))
    assert "will be logged out" in await (await client.get(f"/reset?t={by_admin}")).text()


def shown_code(html: str) -> str:
    return re.search(r'class="code">([0-9A-Z-]{24})<', html).group(1)


async def walk_code_steps(client, pages, user_id, after, code) -> str:
    """Step 1 'I saved it' -> step 2 type the code in -> the final page (returned)."""
    fields = {"user": user_id, "after": after, "nonce": pages.code_nonce(user_id, after, hash_reset_code(code))}
    resp = await client.post("/code", data={**fields, "action": "ask"})
    assert resp.status == 200 and "Step 2 of 2" in await resp.text()
    resp = await client.post("/code", data={**fields, "action": "check", "code": code.lower().replace("-", "")})
    assert resp.status == 200
    return await resp.text()


async def test_reset_code_must_be_typed_back_in(bot, web_client):
    client, pages = web_client
    code = await bot.signups.issue_reset_code(NEW)
    first = pages.code_nonce(NEW, "signup", hash_reset_code(code))
    fields = {"user": NEW, "after": "signup", "nonce": first}

    resp = await client.post("/code", data={**fields, "action": "check", "code": "WRONG"})
    text = await resp.text()
    assert resp.status == 400 and "not the code" in text and "Step 2 of 2" in text

    # Didn't save it: a new code replaces the old one, back to step 1.
    resp = await client.post("/code", data={**fields, "action": "new"})
    text = await resp.text()
    new_code = shown_code(text)
    assert resp.status == 200 and "Step 1 of 2" in text and new_code != code
    assert not await bot.signups.reset_code_matches(NEW, code)
    # The new page keeps the first issue time: using the steps never extends their life.
    renewed = re.search(r'name="nonce" value="([^"]+)"', text).group(1)
    assert renewed.split(".")[0] == first.split(".")[0] and renewed != first
    # The page from before the new code is dead (it was bound to the old code).
    resp = await client.post("/code", data={**fields, "action": "new"})
    assert resp.status == 400 and "expired" in await resp.text()
    assert "ready" in await walk_code_steps(client, pages, NEW, "signup", new_code)

    # Only for the account and context the nonce was made for, and only for a while.
    fields["nonce"] = renewed
    current = hash_reset_code(new_code)
    for forged in ({**fields, "user": STUDENT}, {**fields, "after": "reset"}, {**fields, "nonce": "1.forged"},
                   {**fields, "nonce": pages.code_nonce(NEW, "signup", current, issued=0)}):
        resp = await client.post("/code", data={**forged, "action": "new"})
        assert resp.status == 400 and "expired" in await resp.text()
    assert await bot.signups.reset_code_matches(NEW, new_code)

    # A code change elsewhere (here: !password code) kills the page too.
    await bot.signups.issue_reset_code(NEW)
    resp = await client.post("/code", data={**fields, "action": "ask"})
    assert resp.status == 400


def recover_form(pages, username, code, password="correct horse battery"):
    return {"nonce": pages.recover_nonce(), "username": username, "code": code,
            "password": password, "confirm": password}


async def test_recover_page(bot, web_client):
    client, pages = web_client
    bot.synapse.reset_password = AsyncMock()
    code = await bot.signups.issue_reset_code(STUDENT)

    resp = await client.get("/recover")
    assert resp.status == 200 and "Reset code" in await resp.text()

    resp = await client.post("/recover", data={**recover_form(pages, "student", code), "nonce": "1.forged"})
    assert resp.status == 400 and "expired" in await resp.text()

    resp = await client.post("/recover", data=recover_form(pages, "student", "WRONG-CODE"))
    text = await resp.text()
    assert resp.status == 400 and "don&#x27;t match" in text and 'value="student"' in text

    resp = await client.post("/recover", data=recover_form(pages, "student", code, "short"))
    assert resp.status == 400 and "at least 12" in await resp.text()
    assert await bot.store.get_reset_code(STUDENT) is not None  # a bad password doesn't use up the code

    resp = await client.post("/recover", data=recover_form(pages, "student@unibas.ch", code))
    text = await resp.text()
    assert resp.status == 200 and "new password is set" in text and "Step 1 of 2" in text
    new_code = shown_code(text)
    assert new_code != code
    text = await walk_code_steps(client, pages, STUDENT, "reset", new_code)
    assert "new password is set" in text and "Reset identity" in text
    bot.synapse.reset_password.assert_awaited_once_with(STUDENT, "correct horse battery", logout_devices=True)


async def test_recover_page_locks_account_after_wrong_codes(bot, web_client):
    client, pages = web_client
    bot.synapse.reset_password = AsyncMock()
    code = await bot.signups.issue_reset_code(STUDENT)
    for _ in range(5):
        await client.post("/recover", data=recover_form(pages, f"@student:{SERVER}", "0000"))
    resp = await client.post("/recover", data=recover_form(pages, "student", code))
    assert resp.status == 400
    bot.synapse.reset_password.assert_not_awaited()


async def test_recover_page_disabled(bot, web_client):
    client, _ = web_client
    bot.config["password.reset_codes"] = False
    assert (await client.get("/recover")).status == 404
