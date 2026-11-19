"""Synapse admin API wrappers. All calls use the bot's own token via client.api.request and
mautrix's SynapseAdminPath; the bot reaches Synapse on the Docker network (http://synapse:8008).
"""
from __future__ import annotations

from typing import Any

import aiohttp
from maubot.matrix import MaubotMatrixClient
from mautrix.api import Method, SynapseAdminPath
from mautrix.errors import MatrixRequestError, MForbidden, MNotFound
from mautrix.types import RoomAlias, RoomID, UserID

from .errors import ValidationError


class SynapseAdmin:
    def __init__(self, client: MaubotMatrixClient, http: aiohttp.ClientSession) -> None:
        self.client = client
        self.http = http

    async def get_user(self, user_id: UserID) -> dict[str, Any] | None:
        """GET /_synapse/admin/v2/users/<user_id>; None if the user doesn't exist."""
        try:
            return await self.client.api.request(Method.GET, SynapseAdminPath.v2.users[user_id])
        except MNotFound:
            return None

    async def user_exists(self, user_id: UserID) -> bool:
        return await self.get_user(user_id) is not None

    async def is_server_admin(self, user_id: UserID) -> bool:
        try:
            user = await self.get_user(user_id)
        except MForbidden:
            return False
        return bool(user and user.get("admin"))

    async def create_user(
        self,
        user_id: UserID,
        password: str,
        displayname: str | None = None,
        emails: list[str] | None = None,
        user_type: str | None = None,
    ) -> None:
        """PUT /_synapse/admin/v2/users/<user_id>. That endpoint also *modifies* existing users,
        so refuse if the user exists already."""
        if await self.user_exists(user_id):
            raise ValidationError("err.account_exists", user_id=user_id)
        content: dict[str, Any] = {"password": password, "admin": False}
        if displayname:
            content["displayname"] = displayname
        if emails:
            content["threepids"] = [{"medium": "email", "address": e} for e in emails]
        if user_type:
            content["user_type"] = user_type
        await self.client.api.request(Method.PUT, SynapseAdminPath.v2.users[user_id], content)

    async def set_user_type(self, user_id: UserID, user_type: str | None) -> None:
        """PUT /_synapse/admin/v2/users/<user_id> with only `user_type` (null clears it). Synapse
        exempts `bot` (and `support`) accounts from the terms-and-conditions check (`user_consent`),
        so bots can send messages without agreeing to the terms."""
        await self.client.api.request(Method.PUT, SynapseAdminPath.v2.users[user_id], {"user_type": user_type})

    async def reset_password(self, user_id: UserID, new_password: str, logout_devices: bool = True) -> None:
        await self.client.api.request(
            Method.POST, SynapseAdminPath.v1.reset_password[user_id],
            {"new_password": new_password, "logout_devices": logout_devices},
        )

    async def reactivate(self, user_id: UserID, password: str) -> None:
        """Only for professor bots deleted before 1.1.0, when !bot delete still deactivated the
        account (its secret storage is gone, so the bot comes back unverified)."""
        await self.client.api.request(Method.PUT, SynapseAdminPath.v2.users[user_id],
                                      {"deactivated": False, "password": password})

    async def deactivate(self, user_id: UserID, erase: bool = False) -> None:
        await self.client.api.request(Method.POST, SynapseAdminPath.v1.deactivate[user_id], {"erase": erase})

    async def set_locked(self, user_id: UserID, locked: bool) -> None:
        """A locked account can't log in, and its tokens are refused (M_USER_LOCKED). Unlike
        deactivation it keeps its account data (secret storage), devices aside, and rooms."""
        await self.client.api.request(Method.PUT, SynapseAdminPath.v2.users[user_id], {"locked": locked})

    async def set_displayname(self, user_id: UserID, displayname: str) -> None:
        """Synapse also updates the membership event in every room the user is in."""
        await self.client.api.request(Method.PUT, SynapseAdminPath.v2.users[user_id], {"displayname": displayname})

    async def delete_all_devices(self, user_id: UserID) -> None:
        """Logs every session out: the access tokens stop working, the device keys are removed."""
        resp = await self.client.api.request(Method.GET, SynapseAdminPath.v2.users[user_id].devices)
        devices = [d["device_id"] for d in resp.get("devices", [])]
        if devices:
            await self.client.api.request(Method.POST, SynapseAdminPath.v2.users[user_id].delete_devices,
                                          {"devices": devices})

    async def joined_rooms(self, user_id: UserID) -> list[RoomID]:
        resp = await self.client.api.request(Method.GET, SynapseAdminPath.v1.users[user_id].joined_rooms)
        return [RoomID(r) for r in resp.get("joined_rooms", [])]

    async def room_label(self, room_id: RoomID) -> str:
        """Name, else alias, else '' (e.g. a DM), for lists shown to people."""
        try:
            room = await self.client.api.request(Method.GET, SynapseAdminPath.v1.rooms[room_id])
        except MatrixRequestError:
            return room_id
        return room.get("name") or room.get("canonical_alias") or ""

    async def override_ratelimit(self, user_id: UserID) -> None:
        """0/0 means 'no limit' for this user."""
        await self.client.api.request(
            Method.POST, SynapseAdminPath.v1.users[user_id].override_ratelimit,
            {"messages_per_second": 0, "burst_count": 0},
        )

    async def force_join(self, user_id: UserID, room: RoomID | RoomAlias) -> None:
        """The bot must be in the room with invite power (always true for bot-created rooms)."""
        await self.client.api.request(Method.POST, SynapseAdminPath.v1.join[room], {"user_id": user_id})

    async def joined_room_count(self, user_id: UserID) -> int:
        resp = await self.client.api.request(Method.GET, SynapseAdminPath.v1.users[user_id].joined_rooms)
        return int(resp.get("total", len(resp.get("joined_rooms", []))))

    async def login(self, user_id: UserID, password: str, device_name: str) -> tuple[str, str]:
        """Client-server password login WITHOUT the bot's token -> (access_token, device_id)."""
        url = str(self.client.api.base_url).rstrip("/") + "/_matrix/client/v3/login"
        body = {
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": user_id},
            "password": password,
            "initial_device_display_name": device_name,
        }
        async with self.http.post(url, json=body) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200:
                raise MatrixRequestError(f"login failed: {resp.status} {data.get('error', '')}")
        return data["access_token"], data["device_id"]
