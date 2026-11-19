"""Professor-owned bots (plan §10): .mbp validation, client for the SECOND maubot, provisioning.

Never point user_bots.maubot_url at the maubot this plugin runs in: any plugin uploaded there
could read the admin bot's server-admin token. is_separate_from() guards against that.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import logging
import re
import secrets
from typing import TYPE_CHECKING, Any
import zipfile

import aiohttp
from mautrix.types import UserID
from packaging.requirements import InvalidRequirement, Requirement
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .confirm import Plan
from .db import BotRequest, Job, JobItem, UserBot
from .errors import NotFound, ValidationError
from . import review
from .identity import is_bot_account
from .strings import t

if TYPE_CHECKING:
    from .bot import AdminBot

log = logging.getLogger("maubot.adminbot.userbots")

PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,127}$")
BOT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
# Words the !bot commands read as keywords (`!bot delete all`, `!bot info help`).
RESERVED_BOT_NAMES = frozenset({"all", "help"})
# Rooms listed by name when a bot is deleted or comes back; the rest only as a count.
MAX_LISTED_ROOMS = 20
OWN_PLUGIN_ID = "ch.unibas.dmi.marvin.adminbot"
VERIFY_ATTEMPTS = 5
VERIFY_RETRY_SECONDS = 2
# maubot trust states (mautrix TrustState) that count as "verified by its owner".
VERIFIED_TRUST_STATES = {"cross-signed-tofu", "cross-signed-trusted", "verified"}


@dataclass
class MbpInfo:
    plugin_id: str
    version: str
    modules: list[str]
    main_class: str
    dependencies: list[str]
    sha256: str
    size: int
    meta: dict = field(default_factory=dict)  # the parsed maubot.yaml


# Locations shown per category in the approval request; `!admin bots show` lists all.
REVIEW_LOCATIONS = 3


def _invalid(detail: str) -> ValidationError:
    return ValidationError("err.mbp_invalid", detail=detail)


def validate_mbp(data: bytes, max_size: int) -> MbpInfo:
    """stdlib zipfile only: size limit, maubot.yaml present and parseable, id/version,
    main module exists, no absolute or '..' paths. Raises errors.ValidationError."""
    if len(data) > max_size:
        raise ValidationError("err.file_too_large", mb=max_size // (1024 * 1024))
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise _invalid("the file is not a zip archive (an .mbp is the zip file that `mbc build` creates)") from e
    infos = archive.infolist()
    names = set()
    for info in infos:
        name = info.filename
        if name.startswith("/") or "\\" in name or ".." in name.split("/") or re.match(r"^[A-Za-z]:", name):
            raise _invalid(f"the archive contains the unsafe path '{name}' (absolute or with '..')")
        names.add(name)
    if sum(info.file_size for info in infos) > max_size * 10:
        raise _invalid("the unpacked files are too large")
    unreviewable = review.unreviewable_files(archive)
    if unreviewable:
        listed = ", ".join(f"'{n}'" for n in unreviewable[:5]) + (" ..." if len(unreviewable) > 5 else "")
        raise _invalid(f"it contains files that can't be reviewed ({listed}). A package may only contain source "
                       "code, text files, images and fonts, no compiled files (.pyc, .so, `__pycache__`) and no "
                       "archives. Remove them and run `mbc build` again")
    if "maubot.yaml" not in names:
        raise _invalid("there is no maubot.yaml at the top level of the archive (run `mbc build` in the folder that contains maubot.yaml)")
    try:
        meta = YAML(typ="safe").load(archive.read("maubot.yaml"))
    except YAMLError as e:
        raise _invalid("maubot.yaml is not valid YAML (check the indentation)") from e
    if not isinstance(meta, dict):
        raise _invalid("maubot.yaml must consist of `key: value` lines")
    plugin_id = str(meta.get("id") or "")
    if not PLUGIN_ID_RE.match(plugin_id):
        raise _invalid("maubot.yaml has no valid `id:` (lowercase letters, digits, `.`, `_`, `-`, e.g. `ch.unibas.max.muster.quiz`)")
    version = str(meta.get("version") or "")
    if not version:
        raise _invalid("maubot.yaml has no `version:` (e.g. `version: 1.0.0`)")
    modules = meta.get("modules") or []
    if not isinstance(modules, list) or not modules or not all(isinstance(m, str) for m in modules):
        raise _invalid("maubot.yaml has no `modules:` list (the Python module(s) of your plugin)")
    main_class = str(meta.get("main_class") or "")
    if not main_class:
        raise _invalid("maubot.yaml has no `main_class:` (the name of your Plugin class)")
    main_module = main_class.split("/", 1)[0] if "/" in main_class else modules[-1]
    main_path = main_module.replace(".", "/")
    if f"{main_path}/__init__.py" not in names and f"{main_path}.py" not in names:
        raise _invalid(f"the module '{main_module}' named in maubot.yaml is not in the archive (add its folder or .py file to `modules:` and rebuild)")
    dependencies = meta.get("dependencies") or []
    if not isinstance(dependencies, list):
        raise _invalid("`dependencies:` in maubot.yaml must be a list")
    return MbpInfo(
        plugin_id=plugin_id, version=version, modules=modules, main_class=main_class,
        dependencies=[str(d) for d in dependencies], sha256=hashlib.sha256(data).hexdigest(), size=len(data),
        meta=meta,
    )


def format_findings(findings: list[review.Finding], new_keys: set | None = None,
                    locations: int | None = REVIEW_LOCATIONS) -> str:
    """Markdown: what needs a look, then what the plugin uses. new_keys marks findings the
    running version didn't have. locations=None lists every place."""
    lines = []
    grouped = review.group(findings)
    checks = [(cat, items) for (sev, cat), items in grouped.items() if sev == review.CHECK]
    if checks:
        lines.append(t("msg.review_checks", count=sum(len(i) for _, i in checks)))
        for category, items in checks:
            shown = items if locations is None else items[:locations]
            places = ", ".join(
                f"`{f.detail}` {f.file}:{f.line}" + (t("msg.review_new") if new_keys and f.key in new_keys else "")
                for f in shown
            )
            more = t("msg.more_rooms", count=len(items) - len(shown)) if len(items) > len(shown) else ""
            lines.append(f"- {t('review.cat.' + category)}: {places}{' ' + more if more else ''}")
    else:
        lines.append(t("msg.review_clean"))
    infos = [(cat, items) for (sev, cat), items in grouped.items() if sev == review.INFO]
    if infos:
        uses = "; ".join(f"{t('review.cat.' + cat)} (`" + "`, `".join(sorted({f.detail for f in items})) + "`)"
                         for cat, items in infos)
        lines.append(t("msg.review_uses", uses=uses))
    return "\n".join(lines)


def package_meta(data: bytes) -> dict:
    """maubot.yaml of a package that passed validate_mbp once."""
    return YAML(typ="safe").load(zipfile.ZipFile(io.BytesIO(data)).read("maubot.yaml")) or {}


def format_review(info: MbpInfo, data: bytes, deployed: tuple[str, bytes] | None) -> str:
    """The part of an approval request that helps decide: contents, static check and, for an
    update, what changed since the running version (deployed = its version and package)."""
    report = review.analyze(data, info.meta)
    yes, no = t("msg.yes"), t("msg.no")
    lines = [t("msg.review_package", files=len(report.files), py_files=report.python_files,
               lines=report.python_lines, webapp=yes if report.webapp else no,
               database=yes if report.database else no)]
    new_keys = None
    if deployed:
        old_version, old_data = deployed
        changes = review.diff(old_data, data, f"v{old_version}", f"v{info.version}")
        lines.append(t("msg.review_changes", version=old_version, changed=len(changes.changed),
                       added=len(changes.added), removed=len(changes.removed), plus=changes.plus,
                       minus=changes.minus))
        new_keys = review.new_since(report.findings, review.analyze(old_data, package_meta(old_data)).findings)
    lines.append(format_findings(report.findings, new_keys))
    lines.append(t("msg.review_disclaimer"))
    return "\n".join(lines)


def missing_dependencies(dependencies: list[str]) -> list[str]:
    """Dependencies not installed in this maubot image. The userbots maubot runs the same pinned
    image, so what is missing here is missing there too."""
    missing = []
    for dep in dependencies:
        try:
            name = Requirement(dep).name
        except InvalidRequirement:
            missing.append(dep)
            continue
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(dep)
    return missing


class UserbotsError(ValidationError):
    pass


class UserbotsClient:
    """maubot management API (<maubot_url>/_matrix/maubot/v1/...) of the userbots maubot."""

    def __init__(self, http: aiohttp.ClientSession, base_url: str, username: str, password: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/") + "/_matrix/maubot/v1"
        self.username = username
        self.password = password
        self.token: str | None = None

    async def login(self) -> None:
        async with self.http.post(f"{self.base_url}/auth/login",
                                  json={"username": self.username, "password": self.password}) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200 or not isinstance(data, dict) or "token" not in data:
                raise UserbotsError("err.userbots_api", status=resp.status, detail="login failed")
            self.token = data["token"]

    async def request(self, method: str, path: str, *, allow_404: bool = False, retry: bool = True,
                      **kwargs: Any) -> Any:
        """Authenticated request; logs in again once on 401. Returns parsed JSON (or None)."""
        if self.token is None:
            await self.login()
        headers = {"Authorization": f"Bearer {self.token}", **kwargs.pop("headers", {})}
        async with self.http.request(method, f"{self.base_url}{path}", headers=headers, **kwargs) as resp:
            if resp.status == 401 and retry:
                self.token = None
                return await self.request(method, path, allow_404=allow_404, retry=False, **kwargs)
            if resp.status == 404 and allow_404:
                return None
            text = await resp.text()
            if resp.status >= 400:
                raise UserbotsError("err.userbots_api", status=resp.status, detail=text[:200])
            if not text:
                return None
            try:
                return await resp.json(content_type=None)
            except ValueError:
                return text

    async def list_clients(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/clients") or []

    async def get_client(self, user_id: UserID) -> dict[str, Any] | None:
        return await self.request("GET", f"/client/{user_id}", allow_404=True)

    async def list_instances(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/instances") or []

    async def get_instance(self, instance_id: str) -> dict[str, Any] | None:
        return await self.request("GET", f"/instance/{instance_id}", allow_404=True)

    async def get_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        return await self.request("GET", f"/plugin/{plugin_id}", allow_404=True)

    async def upload_plugin(self, data: bytes) -> dict[str, Any]:
        return await self.request(
            "POST", "/plugins/upload", params={"allow_override": "true"}, data=data,
            headers={"Content-Type": "application/zip"},
        )

    async def delete_plugin(self, plugin_id: str) -> None:
        await self.request("DELETE", f"/plugin/{plugin_id}", allow_404=True)

    async def save_client(self, user_id: UserID, homeserver: str, access_token: str, device_id: str,
                          displayname: str) -> None:
        """Create the client, or update it if a previous (interrupted) run created it already."""
        body = {
            "homeserver": homeserver, "access_token": access_token, "device_id": device_id,
            "enabled": True, "started": True, "sync": True, "autojoin": True, "displayname": displayname,
        }
        if await self.get_client(user_id):
            await self.request("PUT", f"/client/{user_id}", json=body)
        else:
            await self.request("POST", "/client/new", json=body)

    async def generate_recovery_key(self, user_id: UserID) -> str | None:
        """New cross-signing keys, signs the client's device. None if the account has keys already."""
        try:
            data = await self.request("POST", f"/client/{user_id}/generate_recovery_key")
        except UserbotsError as e:
            if e.params.get("status") == 409:  # client_has_keys
                return None
            raise
        return data["recovery_key"]

    async def verify(self, user_id: UserID, recovery_key: str) -> None:
        """Sign the client's device with the cross-signing keys behind an existing recovery key."""
        await self.request("POST", f"/client/{user_id}/verify", json={"recovery_key": recovery_key})

    async def delete_client(self, user_id: UserID) -> None:
        await self.request("DELETE", f"/client/{user_id}", allow_404=True)

    async def put_instance(self, instance_id: str, **fields: Any) -> dict[str, Any]:
        """Create (needs type + primary_user) or partially update an instance."""
        return await self.request("PUT", f"/instance/{instance_id}", json=fields)

    async def delete_instance(self, instance_id: str) -> None:
        await self.request("DELETE", f"/instance/{instance_id}", allow_404=True)

    async def stop_all(self) -> int:
        """Kill switch: started=false on every instance."""
        count = 0
        for instance in await self.list_instances():
            if instance.get("started"):
                await self.put_instance(instance["id"], started=False)
                count += 1
        return count

    async def is_separate_from(self, own_mxid: UserID) -> bool:
        """False if our own client shows up in the target maubot (= same maubot)."""
        return all(client.get("id") != own_mxid for client in await self.list_clients())


class BotManager:
    """Requests, approval, provisioning and deletion on top of UserbotsClient."""

    def __init__(self, bot: AdminBot, client: UserbotsClient) -> None:
        self.bot = bot
        self.client = client

    @property
    def cfg(self) -> Any:
        return self.bot.config

    @staticmethod
    def check_name(name: str) -> str:
        name = (name or "").lower()
        if not BOT_NAME_RE.match(name):
            raise ValidationError("err.bot_name", name=name)
        if name in RESERVED_BOT_NAMES:
            raise ValidationError("err.bot_name_reserved", name=name)
        return name

    async def check_can_create(self, owner: UserID, name: str) -> None:
        """Name free, its account not taken by someone else, quota not reached (admins have no quota)."""
        if await self.bot.store.get_user_bot(owner, name):
            raise ValidationError("err.bot_exists", name=name)
        user_id = self.bot_user_id(owner, name)
        if await self.bot.synapse.get_user(user_id) is not None:
            await self.require_own_account(user_id)
        limit = self.cfg["user_bots.max_per_professor"]
        if not self.bot.authz.is_admin(owner) and await self.bot.store.count_user_bots(owner) >= limit:
            raise ValidationError("err.bot_quota", limit=limit)

    async def require_own_account(self, user_id: UserID) -> None:
        """The guard for every call that changes a professor bot's account (password reset,
        login, reactivation, deactivation): only @bot.* accounts this plugin created itself.
        An account in the bot. namespace made some other way (open token registration, Ketesa)
        is refused, so the admin bot never takes over an account it didn't make. Admins are
        told, because such an account shouldn't exist."""
        if is_bot_account(user_id) and await self.bot.store.is_bot_account(user_id):
            return
        log.warning(f"Refusing to touch {user_id}: not an account this plugin created")
        await self.bot.audit.post(t("msg.bot_account_foreign_audit", user_id=user_id))
        raise ValidationError("err.bot_account_foreign", user_id=user_id)

    @staticmethod
    def suggest_plugin_id(owner: UserID, plugin_id: str) -> str:
        """ch.unibas.<owner-localpart>.<last part of the taken ID>, e.g. ch.unibas.max.muster.echo"""
        localpart = re.sub(r"[^a-z0-9.-]", "-", owner[1:].split(":", 1)[0].lower())
        return f"ch.unibas.{localpart}.{plugin_id.rsplit('.', 1)[-1]}"

    def bot_user_id(self, owner: UserID, name: str) -> UserID:
        """@bot.<owner-localpart>.<name>:<server>"""
        return UserID(f"@bot.{owner[1:].split(':', 1)[0]}.{name}:{self.bot.server_name}")

    @staticmethod
    def instance_id(owner: UserID, name: str) -> str:
        return re.sub(r"[^a-z0-9-]", "-", f"{owner[1:].split(':', 1)[0]}-{name}")

    async def request(self, owner: UserID, name: str, data: bytes, action: str, requester: UserID) -> BotRequest:
        """Quota, package checks, plugin-ID ownership; store the request and post it to the audit
        room. Without require_approval (or when an admin uploads) it is approved right away."""
        name = self.check_name(name)
        existing = await self.bot.store.get_user_bot(owner, name)
        if action == "create":
            await self.check_can_create(owner, name)
        elif not existing:
            raise NotFound("err.bot_unknown", name=name)
        info = validate_mbp(data, self.cfg["user_bots.max_mbp_size_mb"] * 1024 * 1024)
        if info.plugin_id == OWN_PLUGIN_ID:
            raise ValidationError("err.plugin_taken", plugin_id=info.plugin_id,
                                  suggestion=self.suggest_plugin_id(owner, info.plugin_id))
        plugin_owner = await self.bot.store.plugin_owner(info.plugin_id)
        if plugin_owner and plugin_owner != owner:
            # A file problem (the professor can fix the ID), so ValidationError: the router then
            # waits for a corrected file instead of making them repeat the command.
            raise ValidationError("err.plugin_taken", plugin_id=info.plugin_id,
                                  suggestion=self.suggest_plugin_id(owner, info.plugin_id))
        if existing and existing.sha256 == info.sha256:
            raise ValidationError("err.bot_unchanged", name=name, version=info.version)
        missing = missing_dependencies(info.dependencies)
        if missing:
            raise ValidationError("err.mbp_dependencies", deps=", ".join(missing))
        request = BotRequest(
            id=None, owner=owner, name=name, action=action, plugin_id=info.plugin_id, version=info.version,
            sha256=info.sha256, mbp=data, state="pending",
        )
        request.id = await self.bot.store.add_bot_request(request)
        await self.bot.audit.log(requester, f"bot.request.{action}", bot=name, target_count=1)
        auto = not self.cfg["user_bots.require_approval"] or self.bot.authz.is_admin(requester)
        if auto:
            await self.approve(request.id, requester)
            request.state = "approved"
        else:
            deployed = await self.bot.store.deployed_package(owner, name) if action == "update" else None
            await self.bot.audit.post(t(
                "msg.bot_request_audit", id=request.id, owner=owner, name=name, action=action,
                plugin_id=info.plugin_id, version=info.version, sha256=info.sha256,
                deps=", ".join(info.dependencies) or "-", review=format_review(info, data, deployed),
            ))
        return request

    async def show(self, request_id: int) -> tuple[BotRequest, str, tuple[str, str] | None]:
        """For `!admin bots show`: the request (with its package), every finding of the static
        check, and for an update the diff against the running version as (file name, text)."""
        request = await self.bot.store.get_bot_request(request_id)
        if request is None:
            raise NotFound("err.bot_request_unknown", id=request_id)
        if not request.mbp:
            raise NotFound("err.bot_package_gone", id=request_id)
        meta = package_meta(request.mbp)
        findings = review.analyze(request.mbp, meta).findings
        deployed = await self.bot.store.deployed_package(request.owner, request.name)
        changes, new_keys = None, None
        if deployed and deployed[1] != request.mbp:
            old_version, old_data = deployed
            text = review.diff(old_data, request.mbp, f"v{old_version}", f"v{request.version}").text
            changes = (f"{request.name}-v{old_version}-to-v{request.version}.diff", text)
            new_keys = review.new_since(findings, review.analyze(old_data, package_meta(old_data)).findings)
        return request, format_findings(findings, new_keys, locations=None), changes

    async def approve(self, request_id: int, admin: UserID) -> int:
        """Mark approved, submit a BOT_PROVISION job reporting to the owner's DM. Returns the job ID."""
        from .jobs import JobKind

        request = await self.bot.store.get_bot_request(request_id)
        if request is None or request.state != "pending":
            raise NotFound("err.bot_request_unknown", id=request_id)
        await self.bot.store.set_bot_request_state(request_id, "approved", decided_by=admin)
        room_id = await self.bot.ops.open_dm(request.owner)
        plan = Plan(
            code="", kind=JobKind.BOT_PROVISION.value, requester=admin, room_id=room_id,
            summary="", items=[{"request_id": request_id, "label": request.name}],
            context={"bot": request.name}, expires_at=datetime.now(timezone.utc),
        )
        return await self.bot.jobs.submit(plan)

    async def reject(self, request_id: int, admin: UserID, reason: str | None) -> None:
        request = await self.bot.store.get_bot_request(request_id)
        if request is None or request.state != "pending":
            raise NotFound("err.bot_request_unknown", id=request_id)
        await self.bot.store.set_bot_request_state(request_id, "rejected", decided_by=admin, reason=reason,
                                                   drop_package=True)
        await self.bot.audit.log(admin, "bot.reject", bot=request.name, target_count=1)
        room_id = await self.bot.ops.open_dm(request.owner)
        await self.bot.ops.send(room_id, t("msg.bot_rejected", name=request.name, reason=reason or "-", admin=admin))

    async def provision_item(self, job: Job, item: JobItem) -> None:
        """Plan §10 step 5. Safe to re-run after an interruption."""
        request = await self.bot.store.get_bot_request(item.payload["request_id"])
        if request is None:
            raise NotFound("err.bot_request_unknown", id=item.payload["request_id"])
        try:
            if request.action == "create":
                await self._provision_create(request)
            else:
                await self._provision_update(request)
        except Exception:
            await self.bot.store.set_bot_request_state(request.id, "failed")
            raise
        await self.bot.store.set_bot_request_state(request.id, "done")
        # Keep the running version (for the diff of the next update), drop older ones.
        await self.bot.store.drop_bot_packages(request.owner, request.name, keep=request.id)

    async def _provision_create(self, request: BotRequest) -> None:
        synapse = self.bot.synapse
        user_id = self.bot_user_id(request.owner, request.name)
        password = secrets.token_urlsafe(32)
        displayname = f"{request.name} ({request.owner[1:].split(':', 1)[0]})"
        existing = await synapse.get_user(user_id)
        if existing is None:
            await self.bot.store.add_bot_account(user_id)
            await synapse.create_user(user_id, password, displayname, user_type="bot")
        else:
            # A deleted bot (locked by !bot delete) or an interrupted run: the same account,
            # with its secret storage, so the stored recovery key verifies the new device.
            await self.require_own_account(user_id)
            if existing.get("deactivated"):
                await synapse.reactivate(user_id, password)
            else:
                if existing.get("locked"):
                    await synapse.set_locked(user_id, False)
                await synapse.reset_password(user_id, password, logout_devices=True)
            await synapse.set_displayname(user_id, displayname)  # undo "... – removed"
        if existing and existing.get("user_type") != "bot":
            # reused account that isn't marked as a bot yet: without the type it can't send
            # messages until someone agrees to the terms (user_consent) in its name
            await synapse.set_user_type(user_id, "bot")
        if self.cfg["user_bots.ratelimit_exempt"]:
            await synapse.override_ratelimit(user_id)
        access_token, device_id = await synapse.login(user_id, password, "maubot")
        del password
        await self.client.upload_plugin(request.mbp)
        await self.bot.store.set_plugin_owner(request.plugin_id, request.owner)
        await self.client.save_client(user_id, self.cfg["user_bots.homeserver_url"], access_token, device_id,
                                      displayname)
        verified = await self.cross_sign(user_id)
        instance_id = self.instance_id(request.owner, request.name)
        await self.client.put_instance(instance_id, type=request.plugin_id, primary_user=user_id,
                                       enabled=True, started=True)
        await self.bot.store.save_user_bot(UserBot(
            owner=request.owner, name=request.name, plugin_id=request.plugin_id, instance_id=instance_id,
            user_id=user_id, sha256=request.sha256, state="running",
        ))
        room_id = await self.bot.ops.open_dm(request.owner)
        text = t("msg.bot_ready", name=request.name, user_id=user_id, plugin_id=request.plugin_id)
        if existing is not None:
            count, rooms = await self.room_list(user_id)
            if count:
                text += "\n\n" + t("msg.bot_back_in_rooms", count=count, rooms=rooms)
        if not verified:
            text += "\n\n" + t("msg.bot_unverified")
        await self.bot.ops.send(room_id, text)

    async def cross_sign(self, user_id: UserID) -> bool:
        """Self-verify the bot's new device, so Element shows it as verified by its owner and clients
        that only share keys with cross-signed devices (MSC4153) still send it room keys.
        A fresh account gets new keys; the recovery key is kept to sign the devices of a later
        re-login (reactivation, interrupted run). Failure doesn't stop provisioning."""
        try:
            for attempt in range(VERIFY_ATTEMPTS):
                try:
                    key = await self.client.generate_recovery_key(user_id)
                    if key is None:
                        stored = await self.bot.store.get_bot_recovery_key(user_id)
                        if stored is None:
                            raise UserbotsError("err.bot_no_recovery_key")
                        await self.client.verify(user_id, stored)
                    else:
                        await self.bot.store.set_bot_recovery_key(user_id, key)
                    return True
                except UserbotsError as e:
                    # The client uploads its device keys while starting; maubot refuses until then.
                    if "must be shared" not in str(e.params.get("detail", "")) or attempt == VERIFY_ATTEMPTS - 1:
                        raise
                    await asyncio.sleep(VERIFY_RETRY_SECONDS)
        except Exception as e:
            log.warning(f"Couldn't cross-sign {user_id}: {e}")
            detail = e.params.get("detail", str(e)) if isinstance(e, UserbotsError) else str(e)
            await self.bot.audit.post(t("msg.bot_unverified_audit", user_id=user_id, detail=detail))
        return False

    async def _provision_update(self, request: BotRequest) -> None:
        bot = await self.bot.store.get_user_bot(request.owner, request.name)
        if bot is None:
            raise NotFound("err.bot_unknown", name=request.name)
        await self.client.upload_plugin(request.mbp)
        await self.bot.store.set_plugin_owner(request.plugin_id, request.owner)
        if request.plugin_id != bot.plugin_id:
            await self.client.put_instance(bot.instance_id, type=request.plugin_id)
        old_plugin = bot.plugin_id
        bot.plugin_id, bot.sha256 = request.plugin_id, request.sha256
        await self.bot.store.save_user_bot(bot)
        if old_plugin != request.plugin_id and not await self.bot.store.instances_using_plugin(old_plugin):
            await self.client.delete_plugin(old_plugin)
            await self.bot.store.delete_plugin_owner(old_plugin)
        room_id = await self.bot.ops.open_dm(request.owner)
        await self.bot.ops.send(room_id, t("msg.bot_updated", name=request.name, version=request.version))

    async def delete_item(self, job: Job, item: JobItem) -> str:
        """Stop and remove the bot in maubot (instance, client, plugin if unused), then retire its
        account: rename it to '... – removed' (every room it is in sees that), log out all its
        sessions and lock it. Not deactivated: that would purge its secret storage, and a bot
        created again under the same name couldn't verify itself (plan §10). Its rooms stay;
        returns the owner's text listing them ('' if none). Safe to re-run."""
        bot = await self.bot.store.get_user_bot(item.payload["owner"], item.payload["name"])
        if bot is None:
            raise NotFound("err.bot_unknown", name=item.payload["name"])
        await self.client.delete_instance(bot.instance_id)
        await self.client.delete_client(bot.user_id)
        rooms = ""
        account = await self.bot.synapse.get_user(bot.user_id)
        if account is not None and not account.get("deactivated"):
            await self.require_own_account(bot.user_id)
            synapse = self.bot.synapse
            displayname = f"{bot.name} ({bot.owner[1:].split(':', 1)[0]})"
            await synapse.set_displayname(bot.user_id, t("msg.bot_removed_displayname", name=displayname))
            await synapse.delete_all_devices(bot.user_id)
            await synapse.set_locked(bot.user_id, True)
            count, listed = await self.room_list(bot.user_id)
            if count:
                rooms = t("msg.bot_still_in_rooms", count=count, rooms=listed)
        await self.bot.store.set_user_bot_state(bot.owner, bot.name, "deleted")
        await self.bot.store.drop_bot_packages(bot.owner, bot.name)
        if not await self.bot.store.instances_using_plugin(bot.plugin_id):
            await self.client.delete_plugin(bot.plugin_id)
            await self.bot.store.delete_plugin_owner(bot.plugin_id)
        return rooms

    async def room_list(self, user_id: UserID) -> tuple[int, str]:
        """(number of rooms the account is in, Markdown list with matrix.to links)."""
        rooms = await self.bot.synapse.joined_rooms(user_id)
        lines = []
        for room_id in rooms[:MAX_LISTED_ROOMS]:
            label = re.sub(r"[\[\]\\]", "", await self.bot.synapse.room_label(room_id)) or t("msg.unnamed_room")
            lines.append(f"- [{label}](https://matrix.to/#/{room_id})")
        if len(rooms) > MAX_LISTED_ROOMS:
            lines.append(t("msg.more_rooms", count=len(rooms) - MAX_LISTED_ROOMS))
        return len(rooms), "\n".join(lines)

    async def get(self, owner: UserID, name: str) -> UserBot:
        bot = await self.bot.store.get_user_bot(owner, name)
        if bot is None:
            raise NotFound("err.bot_unknown", name=name)
        return bot

    async def resolve(self, sender: UserID, name: str, admin: bool) -> UserBot:
        """A bot named by `name` alone: the sender's own one; for admins, otherwise the only bot
        with that name among all owners."""
        own = await self.bot.store.get_user_bot(sender, name)
        if own or not admin:
            return own or await self.get(sender, name)
        matches = await self.bot.store.find_user_bots(name)
        if not matches:
            raise NotFound("err.bot_unknown", name=name)
        if len(matches) > 1:
            raise ValidationError("err.bot_ambiguous", name=name, owners=", ".join(b.owner for b in matches),
                                  user_ids=", ".join(b.user_id for b in matches))
        return matches[0]

    async def by_user_id(self, user_id: UserID) -> UserBot:
        bot = await self.bot.store.get_user_bot_by_user_id(user_id)
        if bot is None:
            raise NotFound("err.bot_unknown", name=user_id)
        return bot

    async def info(self, owner: UserID, name: str) -> dict[str, Any]:
        bot = await self.get(owner, name)
        instance = await self.client.get_instance(bot.instance_id) or {}
        plugin = await self.client.get_plugin(bot.plugin_id) or {}
        client = await self.client.get_client(bot.user_id) or {}
        rooms = await self.bot.synapse.joined_room_count(bot.user_id)
        return {
            "name": bot.name, "user_id": bot.user_id, "plugin_id": bot.plugin_id,
            "version": plugin.get("version", "?"), "started": bool(instance.get("started")),
            "enabled": bool(instance.get("enabled")), "rooms": rooms,
            "verified": client.get("trust_state") in VERIFIED_TRUST_STATES,
        }

    async def set_started(self, owner: UserID, name: str, started: bool) -> None:
        bot = await self.get(owner, name)
        await self.client.put_instance(bot.instance_id, started=started)
        await self.bot.store.set_user_bot_state(owner, name, "running" if started else "stopped")

    async def get_config(self, owner: UserID, name: str) -> str:
        bot = await self.get(owner, name)
        instance = await self.client.get_instance(bot.instance_id) or {}
        return instance.get("config") or ""

    async def set_config(self, owner: UserID, name: str, yaml: str) -> None:
        bot = await self.get(owner, name)
        try:
            YAML(typ="safe").load(yaml)
        except YAMLError as e:
            raise ValidationError("err.yaml_invalid", detail=str(e).splitlines()[0]) from e
        await self.client.put_instance(bot.instance_id, config=yaml)

    async def list_for(self, owner: UserID | None) -> list[UserBot]:
        return await self.bot.store.list_user_bots(owner)

    async def disable_all(self) -> int:
        count = await self.client.stop_all()
        for bot in await self.bot.store.list_user_bots():
            await self.bot.store.set_user_bot_state(bot.owner, bot.name, "stopped")
        return count
