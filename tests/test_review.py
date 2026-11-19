"""The approval aids for professor bots: reviewable packages, static check, diff (plan §10).

The dangerous-looking code below (exec, os.system, ...) only exists as strings that the static
check parses; none of it is ever run."""
import io
import zipfile

import pytest

from adminbot import review
from adminbot.errors import ValidationError
from adminbot.userbots import format_findings, format_review, validate_mbp

from .test_mbp import META

MAX = 1024 * 1024

ECHO = '''"""Answers !echo."""
from maubot import Plugin, MessageEvent
from maubot.handlers import command
from mautrix.types import TextMessageEventContent


class EchoBot(Plugin):
    @command.new("echo")
    @command.argument("text", pass_raw=True)
    async def echo(self, evt: MessageEvent, text: str) -> None:
        async with self.http.get("https://example.com") as resp:
            await evt.reply(text)
'''


def mbp(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def checks(source: str) -> list[tuple[str, str]]:
    return [(f.category, f.detail) for f in review.scan("bot.py", source) if f.severity == review.CHECK]


# --- only reviewable files ---------------------------------------------------------------------

@pytest.mark.parametrize("extra", [
    {"echo/__pycache__/x.cpython-312.pyc": b"\x00\x01"},
    {"echo/fast.so": b"\x7fELF"},
    {"vendor.zip": b"PK\x03\x04"},
    {"echo/data.bin": b"\x00\xff\x00"},
    {"echo/blob.txt": b"\xff\xfe\x00not utf-8"},
])
def test_unreviewable_files_are_refused(extra):
    with pytest.raises(ValidationError) as e:
        validate_mbp(mbp({"maubot.yaml": META, "echo/__init__.py": ECHO, **extra}), MAX)
    assert "can't be reviewed" in e.value.params["detail"]


def test_source_text_images_and_fonts_are_fine():
    validate_mbp(mbp({"maubot.yaml": META, "echo/__init__.py": ECHO, "base-config.yaml": "a: 1",
                      "web/index.html": "<p>hi</p>", "web/logo.png": b"\x89PNG\r\n\x1a\n\x00",
                      "web/font.woff2": b"wOF2\x00"}), MAX)


# --- static check ------------------------------------------------------------------------------

def test_ordinary_plugin_needs_no_look():
    assert checks(ECHO) == []
    infos = {(f.category, f.detail) for f in review.scan("bot.py", "import aiohttp\nopen('x')\n")}
    assert infos == {("network", "aiohttp"), ("files", "open()")}


@pytest.mark.parametrize("source, expected", [
    ("import subprocess", ("process", "subprocess")),
    ("import os\nos.system('id')", ("process", "os.system()")),
    ("import os as o\no.popen('id')", ("process", "os.popen()")),
    ("from os import system\nsystem('id')", ("process", "os.system")),
    ("import os\nos.execv('/bin/sh', [])", ("process", "os.execv()")),
    ("exec('print(1)')", ("exec", "exec()")),
    ("import builtins\nbuiltins.eval('1')", ("exec", "eval()")),
    ("__import__('os')", ("exec", "__import__()")),
    ("import importlib", ("exec", "importlib")),
    ("import ctypes", ("native", "ctypes")),
    ("import pickle", ("unpickle", "pickle")),
    ("import socket", ("socket", "socket")),
    ("import asyncpg", ("database", "asyncpg")),
    ("from maubot.client import Client", ("internals", "maubot.client")),
    ("from maubot.lib.store_proxy import x", ("internals", "maubot.lib.store_proxy")),
    ("getattr(obj, 'ex' + 'ec')", ("hiding", "getattr() with a computed name")),
    ("x = ().__class__.__bases__[0].__subclasses__()", ("hiding", "__subclasses__")),
    ("import base64\nbase64.b64decode(s)", ("hiding", "base64.b64decode()")),
    ("globals()['x']", ("hiding", "globals()")),
    ("print(__builtins__)", ("hiding", "__builtins__")),
    ("BLOB = '" + "QUJD" * 150 + "'", ("hiding", "a 600-character string without spaces")),
    ("def broken(:", ("syntax", "SyntaxError")),
])
def test_ways_out_of_the_plugin_api_are_flagged(source, expected):
    assert expected in checks(source)


def test_harmless_lookalikes_are_not_flagged():
    source = 'DOC = """' + "a long help text with spaces " * 30 + '"""\ngetattr(self, "name")\n'
    assert checks(source) == []


def test_line_numbers_point_at_the_code():
    [finding] = [f for f in review.scan("bot.py", "x = 1\n\nexec(y)\n")]
    assert (finding.file, finding.line) == ("bot.py", 3)


# --- what the admin sees ------------------------------------------------------------------------

def test_request_summary_lists_what_needs_a_look():
    data = mbp({"maubot.yaml": META + "webapp: true\n", "echo/__init__.py": ECHO + "\nimport subprocess\n"})
    text = format_review(validate_mbp(data, MAX), data, None)
    assert "2 files, 1 Python file(s)" in text and "Web endpoints: yes" in text and "Database: no" in text
    assert "Needs a look (1)" in text and "`subprocess` echo/__init__.py:14" in text
    assert "network (`aiohttp`)" not in text  # self.http isn't an import
    assert "not everything" in text


def test_clean_package_says_so():
    data = mbp({"maubot.yaml": META, "echo/__init__.py": ECHO})
    assert "nothing that needs a look" in format_review(validate_mbp(data, MAX), data, None)


def test_update_shows_changes_and_marks_new_findings():
    old = mbp({"maubot.yaml": META, "echo/__init__.py": ECHO + "import pickle\n", "README.md": "old"})
    new = mbp({"maubot.yaml": META.replace("version: 1.0", "version: 1.1"),
               "echo/__init__.py": ECHO + "import pickle\nexec(x)\n", "NOTES.md": "new"})
    text = format_review(validate_mbp(new, MAX), new, ("1.0", old))
    assert "Changes since the running v1.0:** 2 file(s) changed, 1 added, 1 removed" in text
    assert "`exec()` echo/__init__.py:14 (new)" in text
    assert "`pickle` echo/__init__.py:13" in text and "`pickle` echo/__init__.py:13 (new)" not in text

    changes = review.diff(old, new, "v1.0", "v1.1")
    assert changes.added == ["NOTES.md"] and changes.removed == ["README.md"]
    assert "+exec(x)" in changes.text and "--- v1.0/echo/__init__.py" in changes.text


def test_full_list_has_every_location():
    findings = review.scan("bot.py", "\n".join(f"exec(x{i})" for i in range(6)))
    assert "more" in format_findings(findings) and "bot.py:6" not in format_findings(findings)
    assert "bot.py:6" in format_findings(findings, locations=None)
