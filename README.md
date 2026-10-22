# MARVIN admin bot

[![tests](https://github.com/matrix-unibas/adminBot/actions/workflows/tests.yml/badge.svg)](https://github.com/matrix-unibas/adminBot/actions/workflows/tests.yml)
[![handbook](https://github.com/matrix-unibas/adminBot/actions/workflows/handbook.yml/badge.svg)](https://github.com/matrix-unibas/adminBot/actions/workflows/handbook.yml)
[![release](https://img.shields.io/github/v/release/matrix-unibas/adminBot?include_prereleases)](https://github.com/matrix-unibas/adminBot/releases)

maubot plugin `ch.unibas.dmi.marvin.adminbot`. The plan, with the design and its reasoning, is in [claude.md](claude.md). The server-side setup (account, nginx, backups, the second maubot for professor bots) is in the server repo: [matrix-unibas/server/docs/admin-bot-setup.md](https://github.com/matrix-unibas/matrix-unibas/blob/main/server/docs/admin-bot-setup.md).

Professors and TAs talk to `@adminbot` in a direct chat. Everyone else on the server (students) can only use `!help` and `!password` there, for their own account; the bot ignores everything else they send. The bot reacts with 🤖 as soon as it starts on a command. `!help` lists what the sender may use; `!help <command>` (or `!<command> help`, `!<command> <sub> --help`) explains one command with its arguments, an example and the next steps:

| Area | Commands |
|---|---|
| Courses | `!course create / list / info / ta / archive / rollover`, `!room add / remove` |
| People | `!invite`, `!roster sync`, `!signup new / guest / list / revoke / renew / reset` |
| Groups | `!groups create / assign / post` |
| Templates | `!template export / import / list / delete` |
| Own bots | `!bot create / update / list / info / config / start / stop / delete` |
| Admins | `!admin prof / audit / bots` |
| Bulk changes | shown as a plan first, run with `!confirm <code>`, dropped with `!cancel` |
| Own account (every user) | `!password` (reset link, sessions stay), `!password code` (new reset code) |
| Help | `!help`, `!help <command> [<sub>]`, `!whoami` |

User documentation: the handbook, as PDF from the latest release ([professors and TAs](https://github.com/matrix-unibas/adminBot/releases/latest/download/handbook-professors.pdf), [technical](https://github.com/matrix-unibas/adminBot/releases/latest/download/handbook-technical.pdf)); sources in [`handbook/`](handbook/) (see [Handbook](#handbook)).

## Layout

```
maubot.yaml, base-config.yaml   plugin metadata and default instance config (both go into the .mbp)
adminbot/
  bot.py                        Plugin class: builds the services, self-check, registers handlers
  commands/base.py              CommandRouter (the only Matrix event handler) + @command + helpers
  commands/*.py                 one class per command group (password.py: the public !password)
  web/                          signup / reset / recover pages (maubot webapp)
  identity, parsing, roster,    pure logic, unit-tested without a server
  templates (parse/dump)
  synapse_admin, matrix_ops,    talk to Synapse
  attachments, userbots
  signups, confirm, jobs,       services (signups: links and reset codes; notices: messages
  authz, audit, notices         held until the user has a device)
  db, migrations                SQL (portable SQLite + Postgres)
  strings/en.py                 every user-facing text, incl. the detailed help per command
tests/                          pytest (uses maubot's own test fixtures)
dev/                            local Synapse + Postgres (+ optional second maubot) for the MacBook
handbook/                       LaTeX handbook (professors' and technical version) + Makefile
.github/workflows/              CI: tests, handbook PDFs, releases (see Releasing)
```

## Testing: four levels, fastest first

Uploading to a running instance is the *last* step. Most work should never need a server.

| Level | What | Runs where | Turnaround |
|---|---|---|---|
| 1. Unit tests | pure modules and `Store` against SQLite | MacBook, `pytest` | seconds |
| 2. Command tests | routing, permissions, replies, invite/confirm/job flow, signup pages; maubot's fake client records what the bot sends, Synapse calls are mocked | MacBook, `pytest` | seconds |
| 3. Local dev stack | the real bot against a real (throwaway) Synapse and, optionally, a second maubot for professor bots; plugin runs **from source**, so no build or upload | MacBook, Docker | restart ≈ 2 s |
| 4. Test node | the built `.mbp` in the real stack: E2EE, nginx, Postgres, backups | test node | upload |

Production gets exactly the `.mbp` that passed level 4.

### Setup (once)

Python **3.12** (`.python-version` pins it for uv). maubot's standalone mode (level 3) does not run on 3.14.

```bash
git clone git@github.com:matrix-unibas/adminBot.git && cd adminBot
uv sync --group dev            # or: python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

### Levels 1 and 2

```bash
.venv/bin/pytest
```

- `tests/conftest.py` points maubot's pytest fixtures at this plugin. The `bot` fixture mocks all server calls, and `chat.send("!help", sender=...)` returns the bot's replies.
- The test DB is SQLite, so the SQL in `db.py` / `migrations.py` must work on SQLite and Postgres.
- `mautrix.crypto` needs python-olm, which isn't in the dev venv. Import it inside functions only (see `attachments.py`).
- New commands need a `usage.*` *and* a `help.*` text in `strings/en.py`; `test_every_command_has_detailed_help` fails otherwise. Replies should say what happened, why, and what to do next.

### Level 3: local dev stack

```bash
dev/setup.sh            # or dev/setup.sh --bots for the second maubot (professor bots)
.venv/bin/python -m maubot.standalone -m maubot.yaml -c dev/standalone.yaml -b dev/standalone.example.yaml
```

`setup.sh` deletes and recreates everything:
- a Synapse with server name `localhost` on `http://localhost:8008`, without rate limits
- Postgres for the plugin
- users `adminbot` (server admin), `admin`, `prof`, `ta` and `student`, all with password `devpass1234567`
- `dev/standalone.yaml` (gitignored) with the bot's token

Using it:
- Log in with Element Desktop at `http://localhost:8008` and DM `@adminbot:localhost`. `admin` is a bot admin, `prof` a professor.
- The signup pages are at `http://127.0.0.1:8090/_matrix/maubot/plugin/adminbot/...` (not 8080: Ketesa uses that port).
- After code changes, press Ctrl-C and start the bot again.
- `docker compose --profile bots down` (in `dev/`) stops the stack.

Limits:
- Local DMs are unencrypted (no device ID, so no E2EE). Encrypted uploads and verification are tested on level 4.
- With `--bots` there is no audit room locally, so bot requests are approved with `!admin bots pending` / `approve`.
- The stack uses named Docker volumes only: Docker Desktop often may not bind-mount from `~/Documents`.

### Level 4: test node, then production

```bash
# bump `version` in maubot.yaml first
find adminbot -name __pycache__ -prune -exec rm -rf {} +   # mbc packs __pycache__ otherwise
.venv/bin/mbc build                                       # -> ch.unibas.dmi.marvin.adminbot-v<version>.mbp (gitignored)
```

Or let CI build it: see [Releasing](#releasing). Upload it in the maubot UI on the test node (`https://localhost:8443/_matrix/maubot/` through the SSH tunnel). The instance reloads with the new version. After the checklist passes, upload the same file to production.

Checklist on the test node, which levels 1–3 can't cover:
- [ ] The DM with the bot is encrypted, and the bot answers.
- [ ] `!invite` with an attached `.txt` file.
- [ ] `!template import` with a replied-to `.yaml`.
- [ ] The CSV arrives as an encrypted file.
- [ ] The signup page works through `https://matrix.dmi.unibas.ch/_matrix/maubot/plugin/adminbot/signup` (production) or through the tunnel (test node).
- [ ] After a restart of maubot, an interrupted job continues.
- [ ] The audit room receives the startup checks.
- [ ] The 🤖 reaction appears right after sending a command, and multi-line replies (`!course info`, `!whoami`) show one item per line in Element.
- [ ] Professor bots (Phase 8, `user_bots.enabled`): `!bot create` with an `.mbp` → approval in the audit room → the bot answers in the professor's room; `!bot delete` deactivates the account and removes the instance. Full steps: admin-bot-setup.md, section 7.5.
- [ ] Managing bots as an admin (0.3.1): `!bot list` shows every professor bot; `!bot info|stop <name>` works on another professor's bot (by name, `@owner <name>` or the bot's Matrix ID); `!bot delete all` lists all bots, and after `!confirm` every bot account is deactivated and userbots has no instances left, while the admin bot keeps running.
- [ ] As a student (no role): `!help` lists only `!password` and `!password code`; `!course list` gets no answer; the link from `!password` changes the password and the Element session stays logged in.
- [ ] `/recover` through nginx (production) or the tunnel: the code from the signup page works once, the page shows a new one, all sessions are logged out, and 5 wrong codes lock the account for the day.
- [ ] A fresh signup: the success page shows a reset code; after the first login in Element, the welcome DM arrives within a minute and is **readable** (not "Unable to decrypt").
- [ ] After `!signup reset` + using the link: the notice arrives after logging in again and is readable.
- [ ] With I11 deployed: Element Web/Desktop forces setting up recovery after the first login. Check what Element X does.
- [ ] A new professor bot shows as verified in Element (member list → the bot → its session has no red shield), `!bot info` says `Verified: yes`, and the bot answers in an *encrypted* room. After `!bot delete` and `!bot create` with the same name, it is verified again.

### Professor bots and E2EE

Right after creating a bot's maubot client, the provisioning job calls `POST /client/<id>/generate_recovery_key` on the userbots maubot. That creates cross-signing keys for the bot account and signs its device, so Element shows the bot as verified by its owner, and clients that only send room keys to cross-signed devices (MSC4153) still include it.
- The recovery key is stored in the bot DB (`bot_recovery_key`, keyed by the bot's user ID) and never shown to anyone. It is kept after `!bot delete`: a reactivated account still has its cross-signing keys on the server, so maubot answers `409 client_has_keys`, and the job signs the new device with `POST /client/<id>/verify` and the stored key.
- If verification fails (crypto not available in userbots, keys created by someone else, ...), the bot is provisioned anyway; the owner gets a note, and the audit room gets the reason. `!bot delete` + `!bot create` tries again.
- This assumes Synapse accepts the bot's *first* cross-signing key upload without user-interactive auth (MSC3967). Check this once on the test node (checklist above).

## Passwords and encryption recovery

The server sends no email, so the bot provides the "forgot password" paths (plan §4, v7):

| Situation | Path | Sessions |
|---|---|---|
| Still logged in somewhere | `!password` in a DM with the bot: link for the sender's own account, valid `password.self_ttl_minutes` (60) | kept (`logout_devices: false`) |
| Logged out everywhere, has the reset code | `/recover` page: username + reset code + new password, then a new code is shown | all logged out |
| Neither | a bot admin: `!signup reset @user` (24 h) | all logged out |

- **Reset codes**: 20 Crockford base32 characters, one per account (`reset_code` table, SHA-256 only). Shown once on the signup page and by `!password code`. Accounts created before 0.3.0 have none until the user sends `!password code`. `/recover` refuses an account for 24 h after `password.max_code_attempts` wrong codes (in memory).
- **Notices wait for a device.** An encrypted message can only be read by devices that exist when it is sent. Right after signup, or after a reset that logged everyone out, the user has none. The welcome and the reset notices are therefore kept in `pending_notice` and sent once `/keys/query` shows a device with keys (checked at once, then every minute; dropped after `notices.max_age_days`).
- **What the bot can't do:** restore old encrypted messages. Element's recovery key and the cross-signing private keys never leave the user's devices. Someone who lost both their sessions and the recovery key has to choose *Can't confirm?* → *Reset identity* in Element (needs the password, which the paths above provide). After that they can chat normally and show as verified, but older encrypted messages stay unreadable. The welcome DM, the reset notices and the handbook all explain this.
- **Making people save the key (I11, infra):** Element Web/Desktop honour `"io.element.e2ee": {"secure_backup_required": true, "secure_backup_setup_methods": ["key"]}` in `/.well-known/matrix/client` and then don't let users skip setting up recovery. That file is served by host nginx, so the change belongs to the `matrix-unibas` repo (admin-bot-setup.md). Element X support still has to be checked on the test node.

## Releasing

Releases are made by CI (`.github/workflows/release.yml`), not by hand. Pushing a tag `v<version>`:
- fails unless the tag matches `version:` in `maubot.yaml`
- runs the tests (`tests.yml`) and builds both handbook PDFs (`handbook.yml`)
- builds `ch.unibas.dmi.marvin.adminbot-v<version>.mbp` from a clean checkout
- creates a **pre-release** with the `.mbp` and the two PDFs attached, and release notes from the commits

```bash
# 1. bump `version` in maubot.yaml, commit, push to main
git tag v0.3.1 && git push origin v0.3.1
gh run watch                                              # or the Actions tab

# 2. test exactly that file on the test node (checklist above)
gh release download v0.3.1 --pattern '*.mbp'

# 3. checklist passed: make it the latest release, then upload the same file to production
gh release edit v0.3.1 --prerelease=false --latest
```

- A pre-release never counts as *latest*, so the handbook links at the top of this README (`releases/latest/download/...`) always point to a release that passed the test node.
- A failed release: fix it, delete the tag (`git push --delete origin v0.3.1 && git tag -d v0.3.1`) and the release, if one was created (`gh release delete v0.3.1`), then tag again.
- Every push to `main` and every PR runs the tests; changes under `handbook/` also build the PDFs (download them from the run's *Artifacts*).

## Slow replies

Every command writes one line to the maubot log (logger `maubot.adminbot.commands`, level INFO):

```
!help from @prof:matrix.dmi.unibas.ch: reached the bot 18734 ms after it was sent, handled in 412 ms
```

- **"reached the bot" is large** (seconds): the delay is *before* the plugin sees the message: Synapse delivering it through `/sync`, the bot's sync loop, or decrypting it. Our code hasn't run yet. The 🤖 reaction then also arrives late. Check the Synapse logs for slow `/sync` requests of `@adminbot`, the maubot log for `mau.client.crypto` warnings ("Failed to decrypt", key sharing), and the server load. Both containers share the host clock, so the number is reliable.
- **"handled in" is large**: the command itself is slow. Most commands make a few calls to Synapse (`http://synapse:8008`) and some DB queries; bulk work runs as a job after `!confirm` and doesn't count here.
- **Rate limits are not the cause of plain slowness.** Synapse answers a rate-limited request with `429 M_LIMIT_EXCEEDED` after at most a short pause, and mautrix doesn't retry 429s, so you would see an error reply, not a delay. The bot also lifts its own rate limit at startup (`ratelimit` in the startup check; a failure is posted to the audit room).

Read the log in the maubot UI (*Logs*) or with `docker logs matrix-maubot 2>&1 | grep "reached the bot"`.

## Handbook

`handbook/` contains a LaTeX handbook in two versions, built from the same sources:

| File | For | Content |
|---|---|---|
| `build/handbook-professors.pdf` | professors and TAs | getting started, courses, people, groups, templates, own bots, troubleshooting, command reference |
| `build/handbook-technical.pdf` | admins, maintainers | everything above plus architecture, connection to Synapse and maubot, data and privacy, security, operations |

```bash
cd handbook
make            # both PDFs into handbook/build/
make professors # or: make technical
make clean
```

The built PDFs aren't committed (`handbook/build/` is gitignored). CI attaches them to every release; the latest ones are always at `https://github.com/matrix-unibas/adminBot/releases/latest/download/handbook-professors.pdf` and `.../handbook-technical.pdf`.

Needs a TeX distribution with `latexmk` (MacTeX or TeX Live). Sections that only belong in the technical version are wrapped in `\iftechnical ... \fi`. When a command changes, update `strings/en.py` *and* the handbook (`handbook/chapters/`).
