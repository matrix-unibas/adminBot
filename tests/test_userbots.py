"""Professor bots against a mocked userbots maubot: cross-signing of the bot's device, and
managing bots (list, naming other owners' bots, delete, delete all)."""
import re
from unittest.mock import AsyncMock

import pytest

from adminbot import userbots
from adminbot.db import BotRequest, JobItem, UserBot
from adminbot.errors import ValidationError
from adminbot.userbots import BotManager, UserbotsClient, UserbotsError

from .conftest import ADMIN, PROF, SERVER, wait_for_jobs
from .test_mbp import make_mbp

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
    bot.synapse.set_user_type = AsyncMock()
    bot.synapse.reactivate = AsyncMock()
    bot.synapse.reset_password = AsyncMock()
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


async def test_new_bot_account_is_created_as_bot(bot, manager):
    await manager._provision_create(request())
    assert bot.synapse.create_user.await_args.kwargs["user_type"] == "bot"
    bot.synapse.set_user_type.assert_not_awaited()


@pytest.mark.parametrize("existing", [{"deactivated": True}, {"deactivated": False, "user_type": None}])
async def test_reused_account_is_marked_as_bot(bot, manager, existing):
    """Without user_type bot the account can't send until it agrees to the terms (user_consent)."""
    bot.synapse.get_user = AsyncMock(return_value=existing)
    await bot.store.add_bot_account(BOT_MXID)
    await manager._provision_create(request())
    bot.synapse.set_user_type.assert_awaited_once_with(BOT_MXID, "bot")


async def test_reused_bot_account_is_left_alone(bot, manager):
    bot.synapse.get_user = AsyncMock(return_value={"deactivated": True, "user_type": "bot"})
    await bot.store.add_bot_account(BOT_MXID)
    await manager._provision_create(request())
    bot.synapse.set_user_type.assert_not_awaited()


async def test_new_account_is_recorded_before_it_is_created(bot, manager):
    """A retry after a crash between create_user and the end of provisioning must still find it ours."""
    bot.synapse.create_user = AsyncMock(side_effect=RuntimeError("crash"))
    with pytest.raises(RuntimeError):
        await manager._provision_create(request())
    assert await bot.store.is_bot_account(BOT_MXID)


@pytest.mark.parametrize("existing", [{"deactivated": False, "user_type": None},
                                      {"deactivated": True, "user_type": "bot"}])
async def test_account_the_plugin_did_not_create_is_never_taken_over(bot, manager, existing):
    """E.g. someone registered @bot.prof.quiz with a registration token before the professor
    asked for a bot called quiz: no password reset, no login, admins are told."""
    bot.synapse.get_user = AsyncMock(return_value=existing)
    with pytest.raises(ValidationError) as e:
        await manager._provision_create(request())
    assert e.value.key == "err.bot_account_foreign"
    bot.synapse.reset_password.assert_not_awaited()
    bot.synapse.reactivate.assert_not_awaited()
    bot.synapse.login.assert_not_awaited()
    assert BOT_MXID in manager.bot.audit.post.await_args.args[0]


async def test_guard_only_accepts_the_bot_namespace(bot, manager):
    await bot.store.add_bot_account(PROF)  # even if a non-bot ID somehow got into the table
    with pytest.raises(ValidationError):
        await manager.require_own_account(PROF)


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
    await bot.store.add_bot_account(user_bot.user_id)  # provisioning records it
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
    bot.synapse.get_user = AsyncMock(return_value={"deactivated": False})
    plan = (await chat.send("!bot delete poll", sender=ADMIN))[0]
    code = re.search(r"!confirm (\w+)", plan).group(1)
    await chat.send(f"!confirm {code}", sender=ADMIN)
    await wait_for_jobs(bot)
    assert await bot.store.get_user_bot(OTHER, "poll") is None
    managed.client.delete_instance.assert_awaited_once_with(poll.instance_id)
    bot.synapse.set_locked.assert_awaited_once_with(poll.user_id, True)
    bot.synapse.deactivate.assert_not_awaited()


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
    bot.synapse.get_user = AsyncMock(return_value={"deactivated": False})
    code = re.search(r"!confirm (\w+)", plan).group(1)
    await chat.send(f"!confirm {code}", sender=ADMIN)
    await wait_for_jobs(bot)
    assert await bot.store.list_user_bots() == []
    assert bot.synapse.set_locked.await_count == 3
    assert "no bots to delete" in (await chat.send("!bot delete all", sender=ADMIN))[0]


async def test_create_refuses_a_name_whose_account_someone_else_holds(bot, chat, managed):
    """The professor learns it before uploading anything."""
    bot.audit.post = AsyncMock()
    bot.synapse.get_user = AsyncMock(return_value={"deactivated": False})
    reply = (await chat.send("!bot create quiz", sender=PROF))[0]
    assert "didn't create it" in reply and "another name" in reply


async def test_keywords_are_not_bot_names():
    for name in ("all", "help"):
        with pytest.raises(ValidationError):
            BotManager.check_name(name)


async def test_owner_is_told_when_someone_else_changes_their_bot(bot, chat, managed):
    await add_bot(bot, OTHER, "poll")
    await add_bot(bot, PROF, "quiz")
    bot.notices.send = AsyncMock()
    await chat.send("!bot stop quiz", sender=PROF)
    assert bot.notices.send.await_count == 0
    await chat.send("!bot stop poll", sender=ADMIN)
    await chat.send("!bot start poll", sender=ADMIN)
    plan = (await chat.send("!bot delete poll", sender=ADMIN))[0]
    await chat.send(f"!confirm {re.search(r'!confirm (\w+)', plan).group(1)}", sender=ADMIN)
    await wait_for_jobs(bot)
    sent = [(c.args[0], c.args[1], c.kwargs["actor"]) for c in bot.notices.send.await_args_list]
    assert sent == [
        (OTHER, "msg.notice.bot_stopped", ADMIN),
        (OTHER, "msg.notice.bot_started", ADMIN),
        (OTHER, "msg.notice.bot_deleted", ADMIN),
    ]


async def test_disable_all_tells_owners_of_running_bots(bot, chat, managed):
    await add_bot(bot, OTHER, "poll")
    await add_bot(bot, PROF, "quiz")
    await add_bot(bot, PROF, "echo")
    await bot.store.set_user_bot_state(PROF, "echo", "stopped")
    managed.client.stop_all.return_value = 2
    bot.notices.send = AsyncMock()
    await chat.send("!admin bots disable-all", sender=ADMIN)
    sent = {c.args[0]: c.kwargs["bots"] for c in bot.notices.send.await_args_list}
    assert sent == {OTHER: "`poll`", PROF: "`quiz`"}


# --- delete locks the account, re-create unlocks it (plan §10) ----------------------------------

ROOMS = [f"!course:{SERVER}", f"!dm:{SERVER}"]


async def test_delete_retires_the_account_but_keeps_it(bot, manager):
    """Not deactivated: that would purge the secret storage, and the same name could never be
    verified again. Renamed so every room sees it, sessions logged out, then locked."""
    quiz = await add_bot(bot, PROF, "quiz")
    bot.synapse.get_user = AsyncMock(return_value={"deactivated": False})
    bot.synapse.deactivate = AsyncMock()
    bot.synapse.joined_rooms = AsyncMock(return_value=ROOMS)
    bot.synapse.room_label = AsyncMock(side_effect=lambda r: "CS101 [General]" if "course" in r else "")
    calls = []
    for name in ("set_displayname", "delete_all_devices", "set_locked"):
        getattr(bot.synapse, name).side_effect = lambda *a, n=name: calls.append(n)
    rooms = await manager.delete_item(None, JobItem(0, 0, {"owner": PROF, "name": "quiz"}, "pending", None))
    assert calls == ["set_displayname", "delete_all_devices", "set_locked"]
    assert bot.synapse.set_displayname.await_args.args == (quiz.user_id, "quiz (prof) – removed")
    bot.synapse.deactivate.assert_not_awaited()
    assert "2 room(s)" in rooms and f"[CS101 General](https://matrix.to/#/{ROOMS[0]})" in rooms
    assert "unnamed room" in rooms


async def test_owner_learns_where_their_deleted_bot_still_is(bot, chat, managed):
    await add_bot(bot, PROF, "quiz")
    bot.synapse.get_user = AsyncMock(return_value={"deactivated": False})
    bot.synapse.joined_rooms = AsyncMock(return_value=ROOMS[:1])
    bot.notices.send = AsyncMock()
    plan = (await chat.send("!bot delete quiz", sender=PROF))[0]
    await chat.send(f"!confirm {re.search(r'!confirm (\w+)', plan).group(1)}", sender=PROF)
    await wait_for_jobs(bot)
    [call] = bot.notices.send.await_args_list
    assert call.args[:2] == (PROF, "msg.bot_deleted_rooms") and ROOMS[0] in call.kwargs["rooms"]


async def test_recreated_bot_gets_its_locked_account_back_verified(bot, manager):
    """Same account, same keys: the stored recovery key verifies the new device."""
    await bot.store.add_bot_account(BOT_MXID)
    await bot.store.set_bot_recovery_key(BOT_MXID, "stored key")
    bot.synapse.get_user = AsyncMock(return_value={"deactivated": False, "locked": True, "user_type": "bot"})
    bot.synapse.joined_rooms = AsyncMock(return_value=ROOMS[:1])
    manager.client.generate_recovery_key.return_value = None  # 409: the account has keys
    await manager._provision_create(request())
    bot.synapse.set_locked.assert_awaited_once_with(BOT_MXID, False)
    bot.synapse.reset_password.assert_awaited_once()
    bot.synapse.set_displayname.assert_awaited_once_with(BOT_MXID, "quiz (prof)")
    bot.synapse.create_user.assert_not_awaited()
    manager.client.verify.assert_awaited_once_with(BOT_MXID, "stored key")
    ready = manager.bot.ops.send.await_args.args[1]
    assert "back in 1 room(s)" in ready and ROOMS[0] in ready and "couldn't verify" not in ready


async def test_bot_deleted_before_locking_is_reactivated(bot, manager):
    """Accounts deactivated by !bot delete before 1.1.0 still come back (unverified)."""
    await bot.store.add_bot_account(BOT_MXID)
    bot.synapse.get_user = AsyncMock(return_value={"deactivated": True, "user_type": "bot"})
    await manager._provision_create(request())
    bot.synapse.reactivate.assert_awaited_once()
    bot.synapse.set_locked.assert_not_awaited()


# --- approval aids: summary, kept package, diff, show (plan §10) --------------------------------

QUIZ_META = "maubot: 0.1.0\nid: ch.unibas.prof.quiz\nversion: {v}\nmodules: [quiz]\nmain_class: Quiz\n"
QUIZ = "from maubot import Plugin\n\n\nclass Quiz(Plugin):\n    pass\n"


def quiz_package(version: str, code: str = QUIZ) -> bytes:
    return make_mbp({"maubot.yaml": QUIZ_META.format(v=version), "quiz/__init__.py": code})


async def provision(bot, manager, request_id: int) -> None:
    await bot.store.set_bot_request_state(request_id, "approved")
    await manager.provision_item(None, JobItem(0, 0, {"request_id": request_id}, "pending", None))


async def test_admins_get_a_review_and_updates_a_diff(bot, manager, chat, maubot_test_bot):
    bot.config["user_bots.require_approval"] = True
    first = await manager.request(PROF, "quiz", quiz_package("1.0"), "create", PROF)
    text = manager.bot.audit.post.await_args.args[0]
    assert "nothing that needs a look" in text and f"!admin bots show {first.id}" in text

    await provision(bot, manager, first.id)
    assert await bot.store.deployed_package(PROF, "quiz") == ("1.0", quiz_package("1.0"))

    second = await manager.request(PROF, "quiz", quiz_package("1.1", QUIZ + "exec(x)\n"), "update", PROF)
    text = manager.bot.audit.post.await_args.args[0]
    assert "Changes since the running v1.0:** 2 file(s) changed" in text and "(new)" in text

    bot.bots = manager
    bot.client.upload_media = AsyncMock(return_value="mxc://example.com/file")
    replies = await chat.send(f"!admin bots show {second.id}", sender=ADMIN)
    assert replies[0] == "ch.unibas.prof.quiz-v1.1.mbp" and replies[1] == "quiz-v1.0-to-v1.1.diff"
    full = manager.bot.ops.send.await_args.args[1]  # text replies go through the mocked ops.send here
    assert "`exec()` quiz/__init__.py:6 (new)" in full and "changes since the running version" in full

    # The new version replaces the kept one; deleting the bot drops it.
    await provision(bot, manager, second.id)
    assert (await bot.store.deployed_package(PROF, "quiz"))[0] == "1.1"
    assert (await bot.store.get_bot_request(first.id)).mbp == b""
    bot.synapse.get_user = AsyncMock(return_value=None)
    await manager.delete_item(None, JobItem(0, 0, {"owner": PROF, "name": "quiz"}, "pending", None))
    assert await bot.store.deployed_package(PROF, "quiz") is None
    await chat.send(f"!admin bots show {second.id}", sender=ADMIN)
    assert "no longer stored" in manager.bot.ops.send.await_args.args[1]
