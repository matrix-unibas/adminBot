"""Staff commands only from verified sessions of the pinned identity (sessions.py)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from mautrix.types import CrossSigningUsage, EncryptedEvent, TrustState

from adminbot import sessions
from adminbot.sessions import SenderSession

from .conftest import ADMIN, PROF, STUDENT

OK = TrustState.CROSS_SIGNED_TOFU
KEY_A, KEY_B, ADMIN_KEY = "A" * 43, "B" * 43, "C" * 43


@pytest.fixture
def senders(bot):
    """What each sender's session looks like; tests change it. Switches the check on."""
    state = {ADMIN: SenderSession(True, OK, ADMIN_KEY), PROF: SenderSession(True, OK, KEY_A)}
    bot.config["security.verified_sessions"] = True
    bot.sessions.inspect = AsyncMock(side_effect=lambda room, event, sender: state[sender])
    bot.sessions.current_master_key = AsyncMock(side_effect=lambda user: state[user].master_key)
    bot.audit.post = AsyncMock()
    return state


async def test_unencrypted_message_is_refused(bot, chat, senders):
    senders[PROF] = SenderSession(encrypted=False)
    [reply] = await chat.send("!course list", sender=PROF)
    assert "isn't encrypted" in reply
    assert await bot.store.get_identity(PROF) is None


@pytest.mark.parametrize("trust", [TrustState.UNVERIFIED, TrustState.UNKNOWN_DEVICE, TrustState.FORWARDED])
async def test_unverified_session_is_refused(bot, chat, senders, trust):
    senders[ADMIN] = SenderSession(True, trust, ADMIN_KEY)
    [reply] = await chat.send("!admin prof add @new:example.com", sender=ADMIN)
    assert "isn't verified" in reply and "recovery key" in reply
    assert "@new:example.com" not in await bot.store.list_professors()


async def test_first_command_pins_the_identity(bot, chat, senders):
    replies = await chat.send("!course list", sender=PROF)
    assert not any("verified" in r for r in replies)
    assert await bot.store.get_identity(PROF) == KEY_A
    assert any(e.action == "identity.pin" for e in await bot.audit.recent(5))


async def test_new_identity_is_refused_until_an_admin_accepts_it(bot, chat, senders):
    await chat.send("!course list", sender=PROF)
    # "Reset identity": a new master key; the session is signed by it (mautrix: untrusted).
    senders[PROF] = SenderSession(True, TrustState.CROSS_SIGNED_UNTRUSTED, KEY_B)
    [reply] = await chat.send("!course list", sender=PROF)
    assert "identity changed" in reply
    await chat.send("!course list", sender=PROF)
    warnings = [c for c in bot.audit.post.await_args_list if "new encryption identity" in c.args[0]]
    assert len(warnings) == 1  # told once per new key, not per command

    [show] = await chat.send(f"!admin identity {PROF}", sender=ADMIN)
    assert "**Changed:**" in show and "AAAA AAAA" in show and "BBBB BBBB" in show
    accepted, notice = await chat.send(f"!admin identity accept {PROF}", sender=ADMIN)
    assert "Accepted the new identity" in accepted and "BBBB BBBB" in accepted
    assert "Your new encryption identity was accepted" in notice  # to the professor (same fake DM)
    assert await bot.store.get_identity(PROF) == KEY_B
    assert any(e.action == "identity.accept" for e in await bot.audit.recent(5))

    replies = await chat.send("!course list", sender=PROF)
    assert not any("identity" in r for r in replies)


async def test_accept_needs_an_identity(chat, senders):
    senders[PROF] = SenderSession(True, OK, None)
    [reply] = await chat.send(f"!admin identity accept {PROF}", sender=ADMIN)
    assert "no encryption identity" in reply


async def test_public_commands_are_not_checked(bot, chat, senders):
    await chat.send("!help", sender=STUDENT)
    await chat.send("!help", sender=PROF)
    bot.sessions.inspect.assert_not_awaited()


async def test_switched_off_nothing_is_checked(bot, chat, senders):
    bot.config["security.verified_sessions"] = False
    senders[PROF] = SenderSession(encrypted=False)
    replies = await chat.send("!course list", sender=PROF)
    assert not any("encrypted" in r for r in replies)


# --- reading the trust state ----------------------------------------------------------------

async def test_inspect_decrypts_the_event_again(bot, monkeypatch):
    check = sessions.SessionCheck(bot)
    encrypted = MagicMock(spec=EncryptedEvent)
    monkeypatch.setattr(sessions.EventMethods, "get_event", AsyncMock(return_value=encrypted))
    crypto = MagicMock()
    crypto.decrypt_megolm_event = AsyncMock(return_value={"mautrix": {"trust_state": OK}})
    crypto.crypto_store.get_cross_signing_keys = AsyncMock(
        return_value={CrossSigningUsage.MASTER: MagicMock(key=KEY_A)})
    monkeypatch.setattr(type(bot.client), "crypto", crypto, raising=False)
    assert await check.inspect("!r:example.com", "$e", PROF) == SenderSession(True, OK, KEY_A)

    crypto.decrypt_megolm_event.side_effect = ValueError("no session")
    assert (await check.inspect("!r:example.com", "$e", PROF)).trust == TrustState.UNVERIFIED

    monkeypatch.setattr(sessions.EventMethods, "get_event", AsyncMock(return_value=object()))
    assert await check.inspect("!r:example.com", "$e", PROF) == SenderSession(encrypted=False)
