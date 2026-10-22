"""DB schema as mautrix upgrade steps. Python, not .sql files: *.sql is gitignored repo-wide.

SQL must run on both SQLite (pytest, maubot's test fixtures) and Postgres (production).
Timestamps are epoch milliseconds (BIGINT), JSON is stored as TEXT.
Course codes are not foreign keys, so a rollover can rename a course in one transaction.
Never edit a released upgrade step; add a new one.
"""
from __future__ import annotations

from mautrix.util.async_db import Connection, Scheme, UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Initial schema")
async def upgrade_v1(conn: Connection, scheme: Scheme) -> None:
    if scheme == Scheme.SQLITE:
        serial, blob = "INTEGER PRIMARY KEY", "BLOB"
    else:
        serial, blob = "BIGSERIAL PRIMARY KEY", "BYTEA"

    await conn.execute(
        """CREATE TABLE professor (
            user_id  TEXT PRIMARY KEY,
            added_by TEXT NOT NULL,
            added_at BIGINT NOT NULL
        )"""
    )
    await conn.execute(
        """CREATE TABLE course (
            code       TEXT PRIMARY KEY,
            title      TEXT NOT NULL,
            semester   TEXT NOT NULL,
            space_id   TEXT NOT NULL,
            owner      TEXT NOT NULL,
            archived   BOOLEAN NOT NULL DEFAULT false,
            created_at BIGINT NOT NULL
        )"""
    )
    await conn.execute(
        """CREATE TABLE course_staff (
            code    TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role    TEXT NOT NULL,
            PRIMARY KEY (code, user_id)
        )"""
    )
    await conn.execute("CREATE INDEX course_staff_user_idx ON course_staff (user_id)")
    await conn.execute(
        """CREATE TABLE template (
            name       TEXT NOT NULL,
            scope      TEXT NOT NULL,
            owner      TEXT NOT NULL,
            yaml       TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            PRIMARY KEY (name, scope, owner)
        )"""
    )
    await conn.execute(
        """CREATE TABLE signup_token (
            token_hash TEXT PRIMARY KEY,
            kind       TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            emails     TEXT NOT NULL,
            course     TEXT,
            created_by TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL,
            used_at    BIGINT
        )"""
    )
    await conn.execute("CREATE INDEX signup_token_user_idx ON signup_token (user_id)")
    await conn.execute(
        """CREATE TABLE pending_invite (
            user_id    TEXT NOT NULL,
            course     TEXT NOT NULL,
            mode       TEXT NOT NULL,
            created_by TEXT NOT NULL,
            PRIMARY KEY (user_id, course)
        )"""
    )
    await conn.execute(
        """CREATE TABLE plan (
            code       TEXT PRIMARY KEY,
            kind       TEXT NOT NULL,
            requester  TEXT NOT NULL,
            room_id    TEXT NOT NULL,
            summary    TEXT NOT NULL,
            items      TEXT NOT NULL,
            context    TEXT NOT NULL,
            expires_at BIGINT NOT NULL
        )"""
    )
    await conn.execute(
        f"""CREATE TABLE job (
            id                {serial},
            kind              TEXT NOT NULL,
            requester         TEXT NOT NULL,
            room_id           TEXT NOT NULL,
            context           TEXT NOT NULL,
            progress_event_id TEXT,
            state             TEXT NOT NULL,
            created_at        BIGINT NOT NULL,
            finished_at       BIGINT
        )"""
    )
    await conn.execute(
        """CREATE TABLE job_item (
            job_id  BIGINT NOT NULL,
            idx     INTEGER NOT NULL,
            payload TEXT NOT NULL,
            state   TEXT NOT NULL,
            error   TEXT,
            PRIMARY KEY (job_id, idx)
        )"""
    )
    await conn.execute(
        f"""CREATE TABLE audit (
            id           {serial},
            ts           BIGINT NOT NULL,
            actor        TEXT NOT NULL,
            action       TEXT NOT NULL,
            course       TEXT,
            bot          TEXT,
            target_count INTEGER,
            job_id       BIGINT,
            result       TEXT NOT NULL
        )"""
    )
    await conn.execute(
        """CREATE TABLE plugin_owner (
            plugin_id TEXT PRIMARY KEY,
            owner     TEXT NOT NULL
        )"""
    )
    await conn.execute(
        f"""CREATE TABLE bot_request (
            id         {serial},
            owner      TEXT NOT NULL,
            name       TEXT NOT NULL,
            action     TEXT NOT NULL,
            plugin_id  TEXT NOT NULL,
            version    TEXT NOT NULL,
            sha256     TEXT NOT NULL,
            mbp        {blob} NOT NULL,
            state      TEXT NOT NULL,
            decided_by TEXT,
            reason     TEXT,
            created_at BIGINT NOT NULL
        )"""
    )
    await conn.execute(
        """CREATE TABLE user_bot (
            owner       TEXT NOT NULL,
            name        TEXT NOT NULL,
            plugin_id   TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            sha256      TEXT NOT NULL,
            state       TEXT NOT NULL,
            PRIMARY KEY (owner, name)
        )"""
    )


@upgrade_table.register(description="Recovery keys of professor bots")
async def upgrade_v2(conn: Connection, scheme: Scheme) -> None:
    # Keyed by account, not by user_bot row: the key has to survive !bot delete, because a
    # reactivated account keeps its cross-signing keys on the server (plan §10).
    await conn.execute(
        """CREATE TABLE bot_recovery_key (
            user_id      TEXT PRIMARY KEY,
            recovery_key TEXT NOT NULL
        )"""
    )


@upgrade_table.register(description="Password reset codes and notices held until a device exists")
async def upgrade_v3(conn: Connection, scheme: Scheme) -> None:
    serial = "INTEGER PRIMARY KEY" if scheme == Scheme.SQLITE else "BIGSERIAL PRIMARY KEY"
    # One code per account, only its SHA-256 (plan §4, reset codes).
    await conn.execute(
        """CREATE TABLE reset_code (
            user_id    TEXT PRIMARY KEY,
            code_hash  TEXT NOT NULL,
            created_at BIGINT NOT NULL
        )"""
    )
    # Messages for users who have no device yet (welcome after signup, notice after a reset);
    # sent by the cleanup loop once one exists, so the encrypted DM can be read.
    await conn.execute(
        f"""CREATE TABLE pending_notice (
            id         {serial},
            user_id    TEXT NOT NULL,
            text_key   TEXT NOT NULL,
            params     TEXT NOT NULL,
            created_at BIGINT NOT NULL
        )"""
    )
