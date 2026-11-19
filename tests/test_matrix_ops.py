"""MatrixOps against mautrix's real client and state store; only HTTP and the Olm machine are fake."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from mautrix.client import Client
from mautrix.client.state_store.memory import MemoryStateStore
from mautrix.errors import MNotFound
from mautrix.types import RoomID, UserID

from adminbot.matrix_ops import MatrixOps

BOT = UserID("@adminbot:example.com")
USER = UserID("@new.student:example.com")
ROOM = RoomID("!dm:example.com")


def member(user_id: UserID, membership: str) -> dict[str, Any]:
    return {"type": "m.room.member", "state_key": user_id, "sender": BOT, "room_id": ROOM,
            "event_id": f"$m-{user_id}", "origin_server_ts": 0, "content": {"membership": membership}}


def fake_client() -> Client:
    """A real mautrix Client (with its state-store updates) whose server has one fresh DM in
    which the bot is joined and the user only invited."""
    client = Client(mxid=BOT, device_id="BOTDEVICE", base_url="http://synapse:8008",
                    state_store=MemoryStateStore())

    async def request(method, path, content=None, **kwargs):
        path = str(path)
        if path.endswith("/createRoom"):
            return {"room_id": ROOM}
        if "/account_data/" in path:
            if content is None:
                raise MNotFound(404, "not found")
            return {}
        if path.endswith("/joined_members"):
            return {"joined": {BOT: {}}}
        if path.endswith("/members"):
            return {"chunk": [member(BOT, "join"), member(USER, "invite")]}
        raise AssertionError(f"unexpected request {method} {path}")

    client.api.request = AsyncMock(side_effect=request)
    crypto = MagicMock()
    crypto.share_group_session = AsyncMock()
    client.crypto = crypto
    return client


async def test_new_dm_shares_the_room_key_with_the_invited_user():
    """The welcome DM is sent right after the room is created, before the user has joined.
    The Megolm key must still reach them, or the message can never be decrypted (mautrix
    doesn't re-share when an invitee joins)."""
    client = fake_client()
    ops = MatrixOps(client, "example.com")  # type: ignore[arg-type]

    room_id = await ops.open_dm(USER)
    await client.share_group_session(room_id)

    share: AsyncMock = client.crypto.share_group_session  # type: ignore[union-attr,assignment]
    [(shared_room, users)] = [c.args for c in share.await_args_list]
    assert shared_room == ROOM
    assert USER in users
    await client.api.session.close()
