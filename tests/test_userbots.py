"""Professor-bot provisioning against a mocked userbots maubot: cross-signing of the bot's device."""
from unittest.mock import AsyncMock

import pytest

from adminbot import userbots
from adminbot.db import BotRequest
from adminbot.userbots import BotManager, UserbotsClient, UserbotsError

from .conftest import PROF, SERVER

BOT_MXID = f"@bot.prof.quiz:{SERVER}"


def crypto_error(detail: str) -> UserbotsError:
    return UserbotsError("err.userbots_api", status=500, detail=detail)


@pytest.fixture
def manager(bot, monkeypatch) -> BotManager:
    monkeypatch.setattr(userbots, "VERIFY_RETRY_SECONDS", 0)
    client = AsyncMock(spec=UserbotsClient)
    client.generate_recovery_key.return_value = "EsT0 abcd"
    client.get_client.return_value = None
    client.get_instance.return_value = {"started": True, "enabled": True}
    client.get_plugin.return_value = {"version": "1.0"}
    bot.synapse.get_user = AsyncMock(return_value=None)
    bot.synapse.login = AsyncMock(return_value=("syt_token", "DEVICE"))
    bot.synapse.joined_room_count = AsyncMock(return_value=0)
    bot.ops.send = AsyncMock()
    bot.audit.post = AsyncMock()
    return BotManager(bot, client)


def request() -> BotRequest:
    return BotRequest(id=1, owner=PROF, name="quiz", action="create", plugin_id="ch.unibas.prof.quiz",
                      version="1.0", sha256="abc", mbp=b"PK", state="approved")


async def test_new_bot_is_cross_signed_and_key_kept(bot, manager):
    await manager._provision_create(request())
    manager.client.generate_recovery_key.assert_awaited_once_with(BOT_MXID)
    manager.client.verify.assert_not_awaited()
    assert await bot.store.get_bot_recovery_key(BOT_MXID) == "EsT0 abcd"
    ready = manager.bot.ops.send.await_args.args[1]
    assert "is running" in ready and "couldn't verify" not in ready


async def test_existing_keys_are_reused_with_stored_recovery_key(bot, manager):
    await bot.store.set_bot_recovery_key(BOT_MXID, "old key")
    manager.client.generate_recovery_key.return_value = None  # 409 client_has_keys
    assert await manager.cross_sign(BOT_MXID)
    manager.client.verify.assert_awaited_once_with(BOT_MXID, "old key")


async def test_waits_until_device_keys_are_shared(manager):
    manager.client.generate_recovery_key.side_effect = [
        crypto_error("Internal crypto error: Device keys must be shared before generating recovery key"),
        "new key",
    ]
    assert await manager.cross_sign(BOT_MXID)
    assert manager.client.generate_recovery_key.await_count == 2


async def test_failed_verification_still_provisions_and_warns(bot, manager):
    manager.client.generate_recovery_key.side_effect = crypto_error("Internal crypto error: no olm")
    await manager._provision_create(request())
    manager.client.put_instance.assert_awaited_once()
    assert (await bot.store.get_user_bot(PROF, "quiz")).state == "running"
    assert "couldn't verify" in manager.bot.ops.send.await_args.args[1]
    assert BOT_MXID in manager.bot.audit.post.await_args.args[0]


async def test_existing_keys_without_stored_key_warn(manager):
    manager.client.generate_recovery_key.return_value = None
    assert not await manager.cross_sign(BOT_MXID)
    manager.client.verify.assert_not_awaited()
    assert "no recovery key" in manager.bot.audit.post.await_args.args[0]


async def test_info_shows_trust_state(bot, manager):
    await manager._provision_create(request())
    manager.client.get_client.return_value = {"trust_state": "cross-signed-tofu"}
    assert (await manager.info(PROF, "quiz"))["verified"]
    manager.client.get_client.return_value = {"trust_state": "unverified"}
    assert not (await manager.info(PROF, "quiz"))["verified"]


async def test_client_treats_409_as_existing_keys():
    client = UserbotsClient(None, "http://userbots:29316", "adminbot", "pw")
    client.request = AsyncMock(side_effect=UserbotsError("err.userbots_api", status=409, detail="has keys"))
    assert await client.generate_recovery_key(BOT_MXID) is None
    client.request = AsyncMock(side_effect=crypto_error("boom"))
    with pytest.raises(UserbotsError):
        await client.generate_recovery_key(BOT_MXID)
