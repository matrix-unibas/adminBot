"""Help for admins approving professor bots (plan §10): what is in a package, what in its code
needs a look, and what changed since the running version. Pure (stdlib only).

The static check is a reviewer's aid, not a verdict. Python can hide what it does (names built
at run time, code downloaded later), so a clean result proves nothing. It flags the usual ways
out of the plugin API and the usual tricks to hide them, which turns "read everything" into
"read these lines first". The real protection is the separate userbots maubot.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
import difflib
import io
import zipfile

# Files nobody can review: compiled code, native libraries, nested archives.
FORBIDDEN_SUFFIXES = (
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".exe", ".bin", ".class", ".jar",
    ".whl", ".egg", ".zip", ".mbp", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z",
)
# Binary files a plugin's web page may need. Code hidden in them would still need exec() or a
# decoder to run, and those are flagged.
BINARY_OK_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".otf")

CHECK = "check"  # needs a look
INFO = "info"  # worth knowing, normal for many plugins

# Top-level module -> (severity, category). Categories are strings keys: review.cat.<category>.
MODULES = {
    "subprocess": (CHECK, "process"), "pty": (CHECK, "process"), "multiprocessing": (CHECK, "process"),
    "importlib": (CHECK, "exec"), "runpy": (CHECK, "exec"), "code": (CHECK, "exec"), "codeop": (CHECK, "exec"),
    "ctypes": (CHECK, "native"), "cffi": (CHECK, "native"), "mmap": (CHECK, "native"),
    "pickle": (CHECK, "unpickle"), "marshal": (CHECK, "unpickle"), "shelve": (CHECK, "unpickle"),
    "dill": (CHECK, "unpickle"), "cloudpickle": (CHECK, "unpickle"),
    "socket": (CHECK, "socket"), "ssl": (CHECK, "socket"),
    "asyncpg": (CHECK, "database"), "psycopg": (CHECK, "database"), "psycopg2": (CHECK, "database"),
    "sqlalchemy": (CHECK, "database"), "aiosqlite": (CHECK, "database"), "sqlite3": (CHECK, "database"),
    "aiohttp": (INFO, "network"), "requests": (INFO, "network"), "httpx": (INFO, "network"),
    "urllib": (INFO, "network"), "http": (INFO, "network"), "websockets": (INFO, "network"),
    "builtins": (CHECK, "hiding"),
    "shutil": (INFO, "files"), "pathlib": (INFO, "files"), "tempfile": (INFO, "files"),
}
# The plugin API; any other maubot module is maubot's own machinery (clients, tokens, config).
MAUBOT_API = ("maubot", "maubot.handlers", "maubot.matrix", "maubot.plugin_base")
CALLS = {
    "exec": (CHECK, "exec"), "eval": (CHECK, "exec"), "compile": (CHECK, "exec"), "__import__": (CHECK, "exec"),
    "os.system": (CHECK, "process"), "os.popen": (CHECK, "process"), "os.fork": (CHECK, "process"),
    "os.kill": (CHECK, "process"), "os.killpg": (CHECK, "process"), "os.posix_spawn": (CHECK, "process"),
    "globals": (CHECK, "hiding"), "vars": (CHECK, "hiding"),
    "base64.b64decode": (CHECK, "hiding"), "base64.b32decode": (CHECK, "hiding"),
    "base64.b85decode": (CHECK, "hiding"), "base64.a85decode": (CHECK, "hiding"),
    "base64.urlsafe_b64decode": (CHECK, "hiding"), "codecs.decode": (CHECK, "hiding"),
    "zlib.decompress": (CHECK, "hiding"), "lzma.decompress": (CHECK, "hiding"), "bz2.decompress": (CHECK, "hiding"),
    "binascii.unhexlify": (CHECK, "hiding"), "binascii.a2b_base64": (CHECK, "hiding"),
    "bytes.fromhex": (CHECK, "hiding"),
    "open": (INFO, "files"), "os.remove": (INFO, "files"), "os.unlink": (INFO, "files"),
    "os.listdir": (INFO, "files"), "os.walk": (INFO, "files"), "os.scandir": (INFO, "files"),
    "os.getenv": (INFO, "environment"),
}
CALL_PREFIXES = {"os.exec": (CHECK, "process"), "os.spawn": (CHECK, "process")}
# Attributes used to reach things the code was not given (sandbox escapes) or to hide names.
DUNDERS = {"__subclasses__", "__globals__", "__code__", "__builtins__", "__getattribute__", "__closure__",
           "__bases__", "__mro__", "__reduce__", "__loader__", "__spec__"}
# A string literal this long without spaces is probably encoded data (base64, hex, ...).
LONG_BLOB = 400


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    file: str
    line: int
    detail: str  # what was found, e.g. "exec()" or "subprocess"

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Without the line: the same thing in the same file, also after edits elsewhere."""
        return self.severity, self.category, self.file, self.detail


@dataclass
class PackageReport:
    files: list[tuple[str, int]]
    python_files: int
    python_lines: int
    webapp: bool
    database: bool
    findings: list[Finding] = field(default_factory=list)


@dataclass
class PackageDiff:
    added: list[str]
    removed: list[str]
    changed: list[str]
    plus: int
    minus: int
    text: str  # unified diff of the text files

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def unreviewable_files(archive: zipfile.ZipFile) -> list[str]:
    """Files that aren't source or text (images and fonts aside)."""
    bad = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name, lower = info.filename, info.filename.lower()
        if "__pycache__/" in name or lower.endswith(FORBIDDEN_SUFFIXES):
            bad.append(name)
        elif not lower.endswith(BINARY_OK_SUFFIXES) and _text(archive.read(name)) is None:
            bad.append(name)
    return bad


def _text(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if "\x00" in text else text


def _texts(data: bytes) -> dict[str, str | None]:
    """File name -> text (None for images and other binaries)."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    return {i.filename: _text(archive.read(i.filename)) for i in archive.infolist() if not i.is_dir()}


def analyze(data: bytes, meta: dict) -> PackageReport:
    """data: a package that passed validate_mbp; meta: its parsed maubot.yaml."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    report = PackageReport(files=[], python_files=0, python_lines=0,
                           webapp=bool(meta.get("webapp")), database=bool(meta.get("database")))
    for info in archive.infolist():
        if info.is_dir():
            continue
        report.files.append((info.filename, info.file_size))
        if not info.filename.endswith(".py"):
            continue
        source = _text(archive.read(info.filename)) or ""
        report.python_files += 1
        report.python_lines += sum(1 for line in source.splitlines() if line.strip())
        report.findings.extend(scan(info.filename, source))
    return report


def scan(filename: str, source: str) -> list[Finding]:
    try:
        tree = ast.parse(source, filename)
    except SyntaxError as e:
        return [Finding(CHECK, "syntax", filename, e.lineno or 0, "SyntaxError")]
    scanner = _Scanner(filename)
    scanner.visit(tree)
    return scanner.found


class _Scanner(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.file = filename
        self.found: list[Finding] = []
        self.aliases: dict[str, str] = {}  # local name -> dotted origin ("o" -> "os", "system" -> "os.system")

    def add(self, severity: str, category: str, node: ast.AST, detail: str) -> None:
        self.found.append(Finding(severity, category, self.file, getattr(node, "lineno", 0), detail))

    def module(self, node: ast.AST, name: str) -> None:
        top = name.split(".", 1)[0]
        if top == "maubot":
            if not any(name == api or name.startswith(api + ".") for api in MAUBOT_API[1:]) and name != "maubot":
                self.add(CHECK, "internals", node, name)
        elif top in MODULES:
            self.add(*MODULES[top], node, name)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.module(node, alias.name)
            if alias.asname:
                self.aliases[alias.asname] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or not node.module:
            return  # the plugin's own modules
        self.module(node, node.module)
        for alias in node.names:
            dotted = f"{node.module}.{alias.name}"
            self.aliases[alias.asname or alias.name] = dotted
            if dotted in CALLS and CALLS[dotted][0] == CHECK:
                self.add(*CALLS[dotted], node, dotted)

    def dotted(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            base = self.dotted(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    def visit_Call(self, node: ast.Call) -> None:
        name = self.dotted(node.func)
        if name and name.startswith("builtins."):
            name = name.removeprefix("builtins.")
        if name in CALLS:
            self.add(*CALLS[name], node, f"{name}()")
        elif name and any(name.startswith(p) for p in CALL_PREFIXES):
            self.add(*next(v for p, v in CALL_PREFIXES.items() if name.startswith(p)), node, f"{name}()")
        elif name in ("getattr", "setattr", "delattr") and len(node.args) >= 2 \
                and not isinstance(node.args[1], ast.Constant):
            self.add(CHECK, "hiding", node, f"{name}() with a computed name")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in DUNDERS:
            self.add(CHECK, "hiding", node, node.attr)
        elif self.dotted(node) == "os.environ":
            self.add(INFO, "environment", node, "os.environ")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "__builtins__":
            self.add(CHECK, "hiding", node, "__builtins__")

    def visit_Constant(self, node: ast.Constant) -> None:
        value = node.value
        if isinstance(value, (str, bytes)) and len(value) >= LONG_BLOB:
            spaces = value.count(" ") if isinstance(value, str) else value.count(b" ")
            if spaces / len(value) < 0.02:
                self.add(CHECK, "hiding", node, f"a {len(value)}-character string without spaces")


def diff(old: bytes, new: bytes, old_label: str, new_label: str) -> PackageDiff:
    old_files, new_files = _texts(old), _texts(new)
    added = sorted(set(new_files) - set(old_files))
    removed = sorted(set(old_files) - set(new_files))
    changed, chunks, plus, minus = [], [], 0, 0
    for name in sorted(set(old_files) | set(new_files)):
        before, after = old_files.get(name), new_files.get(name)
        if name in old_files and name in new_files and before == after:
            continue
        if name in old_files and name in new_files:
            changed.append(name)
        if (name in old_files and before is None) or (name in new_files and after is None):
            chunks.append(f"Binary file {name} {'changed' if name in changed else 'added or removed'}\n")
            continue
        lines = list(difflib.unified_diff(
            (before or "").splitlines(keepends=True), (after or "").splitlines(keepends=True),
            f"{old_label}/{name}" if name in old_files else "/dev/null",
            f"{new_label}/{name}" if name in new_files else "/dev/null",
        ))
        plus += sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        minus += sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        chunks.append("".join(line if line.endswith("\n") else line + "\n" for line in lines))
    return PackageDiff(added, removed, changed, plus, minus, "".join(chunks))


def group(findings: list[Finding]) -> dict[tuple[str, str], list[Finding]]:
    """(severity, category) -> findings, checks first."""
    grouped: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for finding in sorted(findings, key=lambda f: (f.severity != CHECK, f.category, f.file, f.line)):
        grouped[(finding.severity, finding.category)].append(finding)
    return grouped


def new_since(findings: list[Finding], old: list[Finding]) -> set[tuple[str, str, str, str]]:
    """Keys of findings the previous version didn't have."""
    before = {f.key for f in old}
    return {f.key for f in findings if f.key not in before}
