"""Professor bots against a mocked userbots maubot: cross-signing of the bot's device, and
managing bots (list, naming other owners' bots, delete, delete all)."""
import re
from unittest.mock import AsyncMock

import pytest

from adminbot import userbots
from adminbot.db import BotRequest, UserBot
from adminbot.errors import ValidationError
from adminbot.userbots import BotManager, UserbotsClient, UserbotsError

from .conftest import ADMIN, PROF, SERVER, wait_for_jobs

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


# --- managing bots: !bot list / info / delete ---------------------------------------------------

OTHER = f"@other:{SERVER}"


async def add_bot(bot, owner: str, name: str) -> UserBot:
    localpart = owner[1:].split(":")[0]
    user_bot = UserBot(owner, name, f"ch.unibas.{localpart}.{name}", f"{localpart}-{name}",
                       f"@bot.{localpart}.{name}:{SERVER}", "abc", "running")
    await bot.store.save_user_bot(user_bot)
    return user_bot


@pytest.fixture
def managed(bot) -> BotManager:
    """Like `manager`, but replies still reach the chat (ops.send isn't mocked)."""
    client = AsyncMock(spec=UserbotsClient)
    client.get_client.return_value = None
    client.get_instance.return_value = {"started": True, "enabled": True}
    client.get_plugin.return_value = {"version": "1.0"}
    bot.synapse.joined_room_count = AsyncMock(return_value=0)
    bot.synapse.deactivate = AsyncMock()
    bot.bots = BotManager(bot, client)
    return bot.bots


async def test_list_all_for_admins_and_own_for_professors(bot, chat, managed):
    await add_bot(bot, PROF, "quiz")
    await add_bot(bot, OTHER, "poll")
    everything = (await chat.send("!bot list", sender=ADMIN))[0]
    assert "All professor bots" in everything and "quiz" in everything and "poll" in everything
    one_owner = (await chat.send(f"!bot list {OTHER}", sender=ADMIN))[0]
    assert "poll" in one_owner and "quiz" not in one_owner
    own = (await chat.send("!bot list", sender=PROF))[0]
    assert "quiz" in own and "poll" not in own
    assert "only manage your own bots" in (await chat.send(f"!bot list {OTHER}", sender=PROF))[0]


async def test_admins_name_other_bots_three_ways(bot, chat, managed):
    poll = await add_bot(bot, OTHER, "poll")
    for target in ("poll", f"{OTHER} poll", poll.user_id):
        assert "**poll**" in (await chat.send(f"!bot info {target}", sender=ADMIN))[0], target
    # Professors only ever reach their own bots.
    assert "no bot called poll" in (await chat.send("!bot info poll", sender=PROF))[0]
    assert "only manage your own bots" in (await chat.send(f"!bot info {OTHER} poll", sender=PROF))[0]
    assert "only manage your own bots" in (await chat.send(f"!bot info {poll.user_id}", sender=PROF))[0]


async def test_same_name_for_two_owners_needs_the_owner(bot, chat, managed):
    await add_bot(bot, PROF, "quiz")
    await add_bot(bot, OTHER, "quiz")
    reply = (await chat.send("!bot info quiz", sender=ADMIN))[0]
    assert "Several people" in reply and PROF in reply and OTHER in reply
    # The sender's own bot wins without asking.
    assert "**quiz**" in (await chat.send("!bot info quiz", sender=PROF))[0]


async def test_admin_deletes_a_single_bot_of_someone_else(bot, chat, managed):
    poll = await add_bot(bot, OTHER, "poll")
    plan = (await chat.send("!bot delete poll", sender=ADMIN))[0]
    code = re.search(r"!confirm (\w+)", plan).group(1)
    await chat.send(f"!confirm {code}", sender=ADMIN)
    await wait_for_jobs(bot)
    assert await bot.store.get_user_bot(OTHER, "poll") is None
    managed.client.delete_instance.assert_awaited_once_with(poll.instance_id)
    bot.synapse.deactivate.assert_awaited_once_with(poll.user_id)


async def test_delete_all(bot, chat, managed):
    await add_bot(bot, PROF, "quiz")
    await add_bot(bot, PROF, "poll")
    await add_bot(bot, OTHER, "echo")
    # A professor's "all" means their own bots.
    plan = (await chat.send("!bot delete all", sender=PROF))[0]
    assert "**2** bot(s)" in plan and "echo" not in plan
    assert "only manage your own bots" in (await chat.send(f"!bot delete all {OTHER}", sender=PROF))[0]
    await chat.send("!cancel", sender=PROF)
    # An admin's means every professor bot.
    plan = (await chat.send("!bot delete all", sender=ADMIN))[0]
    assert "**3** bot(s)" in plan
    code = re.search(r"!confirm (\w+)", plan).group(1)
    await chat.send(f"!confirm {code}", sender=ADMIN)
    await wait_for_jobs(bot)
    assert await bot.store.list_user_bots() == []
    assert bot.synapse.deactivate.await_count == 3
    assert "no bots to delete" in (await chat.send("!bot delete all", sender=ADMIN))[0]


async def test_keywords_are_not_bot_names():
    for name in ("all", "help"):
        with pytest.raises(ValidationError):
            BotManager.check_name(name)
