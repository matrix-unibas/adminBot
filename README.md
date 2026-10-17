# MARVIN admin bot

[![tests](https://github.com/Noah-Klaholz/adminBot/actions/workflows/tests.yml/badge.svg)](https://github.com/Noah-Klaholz/adminBot/actions/workflows/tests.yml)
[![handbook](https://github.com/Noah-Klaholz/adminBot/actions/workflows/handbook.yml/badge.svg)](https://github.com/Noah-Klaholz/adminBot/actions/workflows/handbook.yml)
[![release](https://img.shields.io/github/v/release/Noah-Klaholz/adminBot?include_prereleases)](https://github.com/Noah-Klaholz/adminBot/releases)

maubot plugin `ch.unibas.dmi.marvin.adminbot`. The plan, with the design and its reasoning, is in [claude.md](claude.md). The server-side setup (account, nginx, backups, the second maubot for professor bots) is in the server repo: [matrix-unibas/server/docs/admin-bot-setup.md](https://github.com/matrix-unibas/matrix-unibas/blob/main/server/docs/admin-bot-setup.md).

Professors and TAs talk to `@adminbot` in a direct chat. The bot reacts with 🤖 as soon as it starts on a command. `!help` lists what the sender may use; `!help <command>` (or `!<command> help`, `!<command> <sub> --help`) explains one command with its arguments, an example and the next steps:

| Area | Commands |
|---|---|
| Courses | `!course create / list / info / ta / archive / rollover`, `!room add / remove` |
| People | `!invite`, `!roster sync`, `!signup new / guest / list / revoke / renew / reset` |
| Groups | `!groups create / assign / post` |
| Templates | `!template export / import / list / delete` |
| Own bots | `!bot create / update / list / info / config / start / stop / delete` |
| Admins | `!admin prof / audit / bots` |
| Bulk changes | shown as a plan first, run with `!confirm <code>`, dropped with `!cancel` |
| Help | `!help`, `!help <command> [<sub>]`, `!whoami` |

User documentation: the handbook, as PDF from the latest release ([professors and TAs](https://github.com/Noah-Klaholz/adminBot/releases/latest/download/handbook-professors.pdf), [technical](https://github.com/Noah-Klaholz/adminBot/releases/latest/download/handbook-technical.pdf)); sources in [`handbook/`](handbook/) (see [Handbook](#handbook)).

## Layout

```
maubot.yaml, base-config.yaml   plugin metadata and default instance config (both go into the .mbp)
adminbot/
  bot.py                        Plugin class: builds the services, self-check, registers handlers
  commands/base.py              CommandRouter (the only Matrix event handler) + @command + helpers
  commands/*.py                 one class per command group
  web/                          signup / reset pages (maubot webapp)
  identity, parsing, roster,    pure logic, unit-tested without a server
  templates (parse/dump)
  synapse_admin, matrix_ops,    talk to Synapse
  attachments, userbots
  signups, confirm, jobs,       services
  authz, audit
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
git clone git@github.com:Noah-Klaholz/adminBot.git && cd adminBot
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

## Releasing

Releases are made by CI (`.github/workflows/release.yml`), not by hand. Pushing a tag `v<version>`:
- fails unless the tag matches `version:` in `maubot.yaml`
- runs the tests (`tests.yml`) and builds both handbook PDFs (`handbook.yml`)
- builds `ch.unibas.dmi.marvin.adminbot-v<version>.mbp` from a clean checkout
- creates a **pre-release** with the `.mbp` and the two PDFs attached, and release notes from the commits

```bash
# 1. bump `version` in maubot.yaml, commit, push to main
git tag v0.2.0 && git push origin v0.2.0
gh run watch                                              # or the Actions tab

# 2. test exactly that file on the test node (checklist above)
gh release download v0.2.0 --pattern '*.mbp'

# 3. checklist passed: make it the latest release, then upload the same file to production
gh release edit v0.2.0 --prerelease=false --latest
```

- A pre-release never counts as *latest*, so the handbook links at the top of this README (`releases/latest/download/...`) always point to a release that passed the test node.
- A failed release: fix it, delete the tag (`git push --delete origin v0.2.0 && git tag -d v0.2.0`) and the release, if one was created (`gh release delete v0.2.0`), then tag again.
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

The built PDFs aren't committed (`handbook/build/` is gitignored). CI attaches them to every release; the latest ones are always at `https://github.com/Noah-Klaholz/adminBot/releases/latest/download/handbook-professors.pdf` and `.../handbook-technical.pdf`.

Needs a TeX distribution with `latexmk` (MacTeX or TeX Live). Sections that only belong in the technical version are wrapped in `\iftechnical ... \fi`. When a command changes, update `strings/en.py` *and* the handbook (`handbook/chapters/`).
