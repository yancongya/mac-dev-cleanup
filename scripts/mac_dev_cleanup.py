#!/usr/bin/env python3
"""Scan and clean common macOS developer-generated files.

Default behavior is dry-run. Deletion only happens with --apply.
The `manual` risk level is reported but never auto-deleted; it exists so the
user can review large dirs, screenshots, archives, etc. before acting.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


HOME = Path.home()
LOG_DIR = HOME / ".codex" / "logs" / "mac-dev-cleanup"
STATE_PATH = LOG_DIR / "state.json"
HISTORY_PATH = LOG_DIR / "history.jsonl"
OPERATIONS_DIR = LOG_DIR / "operations"
TRASH_ROOT = HOME / ".Trash" / "mac-dev-cleanup"
DASHBOARD_PATH = Path(__file__).resolve().parents[1] / "dashboard.html"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"

# Default config written to config.json on first run. Web dashboard edits this
# file; the script reads it on every run. System-level safety sets
# (GLOBAL_SAFE_PATHS, PRUNE_PATHS, SAFE_DIR_NAMES, MODEL_SUFFIXES, etc.) stay
# hardcoded — they are safety boundaries, not user preferences.
DEFAULT_CONFIG = {
    "stale_days": 90,
    "thresholds": {
        "app_cache_min_mb": 50,
        "app_log_min_mb": 10,
        "large_dir_mb": 100,
        "large_file_mb": 50,
    },
    "scan_roots": [
        "~/工作/开发",
        "~/Desktop/OH-WorkSpace",
        "~/Documents",
        "~/Developer",
        "~/dev",
        "~/workspace",
    ],
    "personal_roots": [
        "~/Desktop",
        "~/Pictures",
        "~/Downloads",
    ],
    "exclude_paths": [],
    "exclude_globs": [],
    "protected_projects": [],
    "protected_categories": [],
    "trash_retention_days": 30,
}


def _expand(path_str: str) -> Path:
    return Path(path_str).expanduser()


def load_config() -> dict:
    """Read config.json, merging onto defaults. Writes defaults if missing."""
    cfg = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in DEFAULT_CONFIG.items()}
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k, v in loaded.items():
                if k == "thresholds" and isinstance(v, dict):
                    cfg["thresholds"].update(v)
                elif k in cfg and isinstance(cfg[k], list) and isinstance(v, list):
                    cfg[k] = list(v)
                else:
                    cfg[k] = v
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def validate_config(cfg: dict) -> dict:
    """Validate and normalize user-editable config without weakening hard safety boundaries."""
    if not isinstance(cfg, dict):
        raise ValueError("config must be a JSON object")
    merged = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in DEFAULT_CONFIG.items()}
    for key, value in cfg.items():
        if key not in DEFAULT_CONFIG:
            raise ValueError(f"unknown config key: {key}")
        if key == "thresholds":
            if not isinstance(value, dict):
                raise ValueError("thresholds must be an object")
            unknown = set(value) - set(DEFAULT_CONFIG["thresholds"])
            if unknown:
                raise ValueError(f"unknown threshold: {sorted(unknown)[0]}")
            merged["thresholds"].update(value)
        else:
            merged[key] = value
    for key in ("scan_roots", "personal_roots", "exclude_paths", "exclude_globs", "protected_projects", "protected_categories"):
        if not isinstance(merged[key], list) or not all(isinstance(v, str) for v in merged[key]):
            raise ValueError(f"{key} must be an array of strings")
        merged[key] = list(dict.fromkeys(v.strip() for v in merged[key] if v.strip()))
    for key in ("stale_days", "trash_retention_days"):
        if not isinstance(merged[key], int) or merged[key] < 0:
            raise ValueError(f"{key} must be a non-negative integer")
    for key, value in merged["thresholds"].items():
        if not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"thresholds.{key} must be a non-negative number")
    return merged


def save_config(cfg: dict) -> Path:
    normalized = validate_config(cfg)
    temp = CONFIG_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, CONFIG_PATH)
    return CONFIG_PATH


try:
    CONFIG = validate_config(load_config())
except ValueError as exc:
    print(f"warning: invalid config ignored: {exc}", file=sys.stderr)
    CONFIG = validate_config(DEFAULT_CONFIG)

CORE_TOOL_CHECKS = [
    "python3",
    "df",
]

OPTIONAL_TOOL_CHECKS = [
    "brew",
    "ncdu",
    "docker",
    "node",
    "npm",
    "pnpm",
    "bun",
    "python3",
    "pip3",
    "dart",
    "flutter",
    "cargo",
    "rustup",
]

PROJECT_ROOTS = [_expand(p) for p in CONFIG.get("scan_roots", [])]
PERSONAL_ROOTS = [_expand(p) for p in CONFIG.get("personal_roots", [])]
EXCLUDE_PATHS = [_expand(p) for p in CONFIG.get("exclude_paths", [])]
EXCLUDE_GLOBS = tuple(CONFIG.get("exclude_globs", []))
PROTECTED_PROJECTS = [_expand(p) for p in CONFIG.get("protected_projects", [])]
PROTECTED_CATEGORIES = set(CONFIG.get("protected_categories", []))

GLOBAL_SAFE_PATHS = [
    HOME / ".npm" / "_npx",
    HOME / ".npm" / "_cacache",
    HOME / ".cache" / "uv",
    HOME / ".cargo" / "registry" / "cache",
    HOME / ".cargo" / "registry" / "src",
    HOME / ".cargo" / "git" / "checkouts",
    HOME / ".cargo" / "git" / "db",
    HOME / ".rustup" / "downloads",
    HOME / ".rustup" / "tmp",
    HOME / "Library" / "Caches" / "pip",
    HOME / "Library" / "Caches" / "ms-playwright",
    HOME / "Library" / "Caches" / "ms-playwright-go",
    HOME / "Library" / "Caches" / "node-gyp",
    HOME / "Library" / "Caches" / "electron",
]

GLOBAL_AGGRESSIVE_PATHS = [
    HOME / ".cache" / "codex-runtimes",
    HOME / "Library" / "Caches" / "com.openai.codex",
    HOME / "Library" / "Caches" / "Codex",
    HOME / "Library" / "Caches" / "Trae",
    HOME / ".bun" / "install" / "cache",
    HOME / ".local" / "share" / "uv",
]

# System caches / app data roots scanned at top level for large entries.
APP_CACHES_ROOT = HOME / "Library" / "Caches"
APP_LOGS_ROOT = HOME / "Library" / "Logs"

_th = CONFIG.get("thresholds", {})
APP_CACHE_MIN_SIZE = _th.get("app_cache_min_mb", 50) * 1024 * 1024
APP_LOG_MIN_SIZE = _th.get("app_log_min_mb", 10) * 1024 * 1024
LARGE_DIR_THRESHOLD = _th.get("large_dir_mb", 100) * 1024 * 1024
LARGE_FILE_THRESHOLD = _th.get("large_file_mb", 50) * 1024 * 1024

SAFE_DIR_NAMES = {
    "playwright-report",
    "test-results",
    "blob-report",
    ".nyc_output",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    ".turbo",
    ".vite",
    "coverage",
    "__snapshots__",
    "__image_snapshots__",
    ".cypress-cache",
    ".parcel-cache",
    "storybook-static",
}

SAFE_FILE_NAMES = {
    ".coverage",
}

SAFE_FILE_SUFFIXES = {
    ".trace.zip",
    ".har",
    ".tmp",
    ".temp",
}

SAFE_FILE_EXACT_PREFIXES = {
    "junit",
    "test-results",
}

AGGRESSIVE_DIR_NAMES = {
    "node_modules",
    ".venv",
    "venv",
    "target",
    ".next",
    "build",
    "dist",
    "out",
    ".svelte-kit",
    ".dart_tool",
    ".gradle",
    ".angular",
}

# Project-side log directories and log file patterns.
LOG_DIR_NAMES = {
    "logs",
    "log",
    "npm-debug",
    ".npm-cache",
}

LOG_FILE_PATTERNS = (".log", ".log.")

# Screenshot roots (macOS default + common Chinese names).
SCREENSHOT_DIRS = [
    HOME / "Desktop" / "Screenshots",
    HOME / "Desktop" / "屏幕快照",
    HOME / "Desktop" / "截图",
    HOME / "Pictures" / "Screenshots",
    HOME / "Pictures" / "屏幕快照",
    HOME / "Pictures" / "截图",
    HOME / "Pictures" / "Photos Library.photoslibrary",  # flagged manual, never auto-deleted
]

SCREENSHOT_FILE_KEYWORDS = (
    "screenshot",
    "screen shot",
    "屏幕快照",
    "截图",
    "截屏",
    "屏幕截图",
)

SCREENSHOT_SUFFIXES = {".png", ".jpg", ".jpeg", ".heic"}

# Archive / dump file patterns (reported as manual, never auto-deleted).
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".dmg", ".iso"}
DUMP_SUFFIXES = {".core", ".heapdump", ".prof", ".db-wal", ".db-shm"}

# Model / weight file suffixes (reported as stale-model when in idle projects).
MODEL_SUFFIXES = {".pth", ".safetensors", ".onnx", ".bin", ".pt", ".gguf", ".ckpt", ".tflite", ".ot"}

# A project whose newest source/git activity is older than this is considered stale.
STALE_DAYS_DEFAULT = int(CONFIG.get("stale_days", 90))

# Source code extensions used to gauge real development activity (mtime of these
# files, plus the last git commit, define "last active"; .DS_Store / build info /
# tool metadata are ignored so they don't masquerade as activity).
CODE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".rs", ".go", ".dart",
    ".swift", ".java", ".kt", ".kts", ".rb", ".php", ".vue", ".svelte", ".css",
    ".scss", ".less", ".html", ".htm", ".toml", ".yaml", ".yml", ".md", ".sh",
    ".bash", ".zsh", ".sql", ".proto", ".lua", ".r", ".jl", ".ex", ".exs", ".clj",
    ".cljs", ".hs", ".ml", ".fs", ".cs", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".m", ".mm", ".gradle",
}
CODE_FILE_NAMES = {"Dockerfile", "Makefile", "Gemfile", "Rakefile"}
LOCK_FILE_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "poetry.lock",
    "uv.lock", "composer.lock", "Gemfile.lock", "go.sum", "go.mod", "pubspec.lock",
}
# Tool-generated metadata dirs whose mtime does NOT reflect human development.
NOISE_DIR_NAMES = {
    ".workbuddy", ".planning", ".wrangler", ".playwright-cli", ".system-monitor",
    ".agents", "crashinfo", ".vscode", ".idea", ".DS_Store",
}

PRUNE_NAMES = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",   # handled explicitly, avoid double walk
    ".venv",
    "venv",
}

PRUNE_PATHS = [
    HOME / "Library" / "Application Support",
    HOME / "Library" / "Containers",
    HOME / "Library" / "Group Containers",
    HOME / "Library" / "Mobile Documents",
    HOME / "Music",
    HOME / "Movies",
    HOME / ".Trash",
    HOME / ".pub-cache",
    HOME / "go" / "pkg" / "mod",
]


@dataclass(frozen=True)
class Candidate:
    path: Path
    size: int
    category: str
    risk: str
    reason: str


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        return proc.returncode, proc.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return 127, str(exc)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def get_free_space() -> str:
    code, out = run(["df", "-h", HOME.as_posix()])
    return out if code == 0 else "df unavailable"


def size_bytes(path: Path) -> int:
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
        total = 0
        for root, dirs, files in os.walk(path, topdown=True):
            dirs[:] = [d for d in dirs if d not in PRUNE_NAMES]
            for name in files:
                p = Path(root) / name
                try:
                    if not p.is_symlink():
                        total += p.stat().st_size
                except OSError:
                    continue
        return total
    except OSError:
        return 0


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:  # noqa: BLE001
        return False


def excluded(path: Path, category: str | None = None) -> bool:
    """User-level protection applied in addition to immutable system prune rules."""
    expanded = path.expanduser()
    if category and category in PROTECTED_CATEGORIES:
        return True
    if any(is_under(expanded, p) for p in EXCLUDE_PATHS + PROTECTED_PROJECTS):
        return True
    text = expanded.as_posix()
    home_text = "~" + text[len(HOME.as_posix()):] if text.startswith(HOME.as_posix()) else text
    return any(fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(home_text, pattern) for pattern in EXCLUDE_GLOBS)


def pruned(path: Path, category: str | None = None) -> bool:
    return any(is_under(path, p) for p in PRUNE_PATHS if p.exists()) or excluded(path, category)


def add_path(
    candidates: dict[Path, Candidate],
    path: Path,
    category: str,
    risk: str,
    reason: str,
    skip_prune: bool = False,
) -> None:
    if not path.exists():
        return
    if excluded(path, category) or (not skip_prune and pruned(path, category)):
        return
    resolved = path.resolve()
    if resolved in candidates:
        return
    candidates[resolved] = Candidate(resolved, size_bytes(resolved), category, risk, reason)


def discover_global() -> dict[Path, Candidate]:
    candidates: dict[Path, Candidate] = {}
    for path in GLOBAL_SAFE_PATHS:
        add_path(candidates, path, "global-cache", "safe", "Rebuildable developer cache")
    for path in GLOBAL_AGGRESSIVE_PATHS:
        add_path(candidates, path, "global-cache", "aggressive", "Tool/app runtime cache; may require re-download")
    return candidates


def scan_app_roots() -> dict[Path, Candidate]:
    """Large app cache / app log directories under ~/Library (top level only)."""
    candidates: dict[Path, Candidate] = {}
    if APP_CACHES_ROOT.exists():
        for entry in APP_CACHES_ROOT.iterdir():
            if not entry.is_dir() or entry.is_symlink():
                continue
            resolved = entry.resolve()
            # Skip anything already enumerated explicitly above.
            if any(resolved == p.resolve() for p in GLOBAL_SAFE_PATHS + GLOBAL_AGGRESSIVE_PATHS if p.exists()):
                continue
            sz = size_bytes(resolved)
            if sz >= APP_CACHE_MIN_SIZE:
                candidates[resolved] = Candidate(resolved, sz, "app-cache", "aggressive",
                                                  "Large application cache under ~/Library/Caches")
    if APP_LOGS_ROOT.exists():
        for entry in APP_LOGS_ROOT.iterdir():
            if not entry.is_dir() or entry.is_symlink():
                continue
            resolved = entry.resolve()
            sz = size_bytes(resolved)
            if sz >= APP_LOG_MIN_SIZE:
                candidates[resolved] = Candidate(resolved, sz, "app-log", "aggressive",
                                                "Application log directory under ~/Library/Logs")
    return candidates


def is_log_file(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(pat) for pat in LOG_FILE_PATTERNS) or lower in {"npm-debug.log", "yarn-error.log"}


def scan_projects(include_aggressive: bool) -> dict[Path, Candidate]:
    candidates: dict[Path, Candidate] = {}
    roots = [p for p in PROJECT_ROOTS if p.exists()]
    for root in roots:
        depth0_dirs: list[Path] = []
        for current, dirs, files in os.walk(root, topdown=True):
            current_path = Path(current)
            depth = len(current_path.parts) - len(root.parts)
            if depth == 0:
                depth0_dirs = [current_path / d for d in dirs]
            dirs[:] = [d for d in dirs if d not in PRUNE_NAMES]
            keep_dirs: list[str] = []
            for d in dirs:
                p = current_path / d
                if pruned(p):
                    continue
                if d in SAFE_DIR_NAMES:
                    add_path(candidates, p, "project-generated", "safe", f"Generated test/cache directory: {d}")
                    continue
                if d in LOG_DIR_NAMES:
                    add_path(candidates, p, "log-file", "safe", f"Project log directory: {d}")
                    continue
                if d in AGGRESSIVE_DIR_NAMES:
                    if include_aggressive:
                        add_path(candidates, p, "project-generated", "aggressive",
                                 f"Rebuildable dependency/build directory: {d}")
                    continue
                keep_dirs.append(d)
            dirs[:] = keep_dirs

            for name in files:
                p = current_path / name
                if name in SAFE_FILE_NAMES:
                    add_path(candidates, p, "test-artifact", "safe", f"Generated test artifact: {name}")
                    continue
                if is_log_file(name):
                    add_path(candidates, p, "log-file", "safe", f"Project log file: {name}")
                    continue
                lower = name.lower()
                if any(lower.endswith(suffix) for suffix in SAFE_FILE_SUFFIXES):
                    add_path(candidates, p, "temp-file", "safe", f"Temporary/generated file: {name}")
                    continue
                if any(name.startswith(prefix) for prefix in SAFE_FILE_EXACT_PREFIXES) and (
                    lower.endswith(".xml") or lower.endswith(".json")
                ):
                    add_path(candidates, p, "test-artifact", "safe", f"Generated test result file: {name}")
                    continue
                # Large single file inside a project (archives, dumps, big logs, videos).
                try:
                    fsize = p.stat().st_size
                except OSError:
                    fsize = 0
                if fsize >= LARGE_FILE_THRESHOLD:
                    if any(lower.endswith(s) for s in ARCHIVE_SUFFIXES):
                        add_path(candidates, p, "large-file", "manual", f"Large archive ({fsize // 1048576}M): {name}")
                    elif any(lower.endswith(s) for s in DUMP_SUFFIXES):
                        add_path(candidates, p, "large-file", "manual", f"Core/dump file ({fsize // 1048576}M): {name}")
                    elif is_log_file(name):
                        add_path(candidates, p, "large-file", "manual", f"Large log file ({fsize // 1048576}M): {name}")
                    else:
                        add_path(candidates, p, "large-file", "manual", f"Large file ({fsize // 1048576}M): {name}")

        # Large top-level project directories not already classified.
        for d in depth0_dirs:
            if not d.exists() or pruned(d):
                continue
            resolved = d.resolve()
            if resolved in candidates:
                continue
            name = d.name
            if name in SAFE_DIR_NAMES or name in AGGRESSIVE_DIR_NAMES or name in LOG_DIR_NAMES:
                continue
            sz = size_bytes(resolved)
            if sz >= LARGE_DIR_THRESHOLD:
                candidates[resolved] = Candidate(resolved, sz, "large-dir", "manual",
                                                  f"Large project directory ({sz // 1048576}M): {name}")
    return candidates


def scan_temp() -> dict[Path, Candidate]:
    candidates: dict[Path, Candidate] = {}
    temp_roots = [Path("/tmp"), Path("/var/folders")]
    prefixes = ("playwright-", "playwright_", "puppeteer-", "chrome-profile")
    for root in temp_roots:
        if not root.exists():
            continue
        for current, dirs, files in os.walk(root, topdown=True):
            depth = len(Path(current).parts) - len(root.parts)
            if depth > 5:
                dirs[:] = []
                continue
            current_path = Path(current)
            if "node_modules" in current_path.parts or ".venv" in current_path.parts or "venv" in current_path.parts:
                dirs[:] = []
                continue
            keep_dirs: list[str] = []
            for d in dirs:
                p = current_path / d
                if d == "node_modules" or d in {".venv", "venv"}:
                    continue
                if d.startswith(prefixes):
                    add_path(candidates, p, "temp-browser", "safe", "Browser automation temporary directory")
                    continue
                keep_dirs.append(d)
            dirs[:] = keep_dirs
            for name in files:
                lower = name.lower()
                if "playwright" in lower or lower.endswith(".trace.zip"):
                    add_path(candidates, current_path / name, "temp-browser", "safe", "Browser automation temporary file")
    return candidates


def scan_screenshots() -> dict[Path, Candidate]:
    """Screenshot directories and loose screenshot files. Always manual risk."""
    candidates: dict[Path, Candidate] = {}
    for d in SCREENSHOT_DIRS:
        if not d.exists():
            continue
        resolved = d.resolve()
        if resolved in candidates:
            continue
        if not d.is_dir():
            continue
        # Photos Library is huge and personal; flag but do not size-walk fully (skip to avoid stalls).
        if d.name.endswith(".photoslibrary"):
            candidates[resolved] = Candidate(resolved, -1, "screenshot", "manual",
                                             "Apple Photos library; personal media, do not auto-delete")
            continue
        sz = size_bytes(resolved)
        candidates[resolved] = Candidate(resolved, sz, "screenshot", "manual",
                                         "Screenshot directory; personal files, review before deleting")
    # Loose screenshot files in personal root tops.
    for root in PERSONAL_ROOTS:
        if not root.exists():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                continue
            lower = entry.name.lower()
            if not any(lower.endswith(s) for s in SCREENSHOT_SUFFIXES):
                continue
            if any(kw in entry.name.lower() for kw in SCREENSHOT_FILE_KEYWORDS):
                add_path(candidates, entry, "screenshot", "manual",
                         "Screenshot file; personal file, review before deleting", skip_prune=True)
    return candidates


def scan_personal_large() -> dict[Path, Candidate]:
    """Large top-level dirs/files in Desktop / Pictures / Downloads. Always manual."""
    candidates: dict[Path, Candidate] = {}
    for root in PERSONAL_ROOTS:
        if not root.exists():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            resolved = entry.resolve()
            if resolved in candidates:
                continue
            if pruned(entry) and not is_under(entry, root):
                continue
            if entry.is_dir():
                # Skip screenshot dirs already captured.
                if any(resolved == sd.resolve() for sd in SCREENSHOT_DIRS if sd.exists()):
                    continue
                sz = size_bytes(resolved)
                if sz >= LARGE_DIR_THRESHOLD:
                    candidates[resolved] = Candidate(resolved, sz, "large-dir", "manual",
                                                     f"Large directory in {root.name} ({sz // 1048576}M): {entry.name}")
            else:
                try:
                    fsize = entry.stat().st_size
                except OSError:
                    fsize = 0
                if fsize >= LARGE_FILE_THRESHOLD:
                    lower = entry.name.lower()
                    if any(lower.endswith(s) for s in ARCHIVE_SUFFIXES):
                        candidates[resolved] = Candidate(resolved, fsize, "large-file", "manual",
                                                        f"Large archive in {root.name} ({fsize // 1048576}M): {entry.name}")
                    else:
                        candidates[resolved] = Candidate(resolved, fsize, "large-file", "manual",
                                                        f"Large file in {root.name} ({fsize // 1048576}M): {entry.name}")
    return candidates


def git_last_commit_epoch(project: Path) -> float:
    """Last commit timestamp from .git/logs/HEAD (no subprocess). 0 if unknown."""
    logf = project / ".git" / "logs" / "HEAD"
    if not logf.exists():
        return 0.0
    try:
        with logf.open("rb") as f:
            f.seek(0, 2)
            pos = f.tell()
            data = b""
            while pos > 0 and data.count(b"\n") < 3:
                step = min(4096, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
        lines = [ln for ln in data.decode("utf-8", "ignore").splitlines() if ln.strip()]
        if not lines:
            return 0.0
        head = lines[-1].split("\t", 1)[0].split()
        # fields: old new author email <timestamp> tz
        if len(head) >= 5:
            try:
                return float(head[-2])
            except ValueError:
                return 0.0
    except OSError:
        return 0.0
    return 0.0


def scan_stale_projects(stale_days: int) -> dict[Path, Candidate]:
    """Identify dependencies and model files inside long-idle projects.

    A project is stale when its newest source file or .git activity is older
    than `stale_days`. For stale projects, dependency/build dirs become
    `stale-deps` (aggressive) and model/weight files become `stale-model`
    (manual). Runs before scan_projects so the stale-prefixed entries win
    deduplication.
    """
    candidates: dict[Path, Candidate] = {}
    if stale_days <= 0:
        return candidates
    now = time.time()
    threshold = stale_days * 86400
    for root in PROJECT_ROOTS:
        if not root.exists():
            continue
        try:
            projects = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
        except OSError:
            continue
        for project in projects:
            latest = 0.0
            deps_found: list[tuple[Path, str]] = []
            models_found: list[tuple[Path, int]] = []
            for current, dirs, files in os.walk(project, topdown=True):
                cp = Path(current)
                keep: list[str] = []
                for d in dirs:
                    if d in AGGRESSIVE_DIR_NAMES:
                        deps_found.append((cp / d, d))
                        continue
                    if d in PRUNE_NAMES or d in SAFE_DIR_NAMES or d in LOG_DIR_NAMES or d in NOISE_DIR_NAMES:
                        continue
                    keep.append(d)
                dirs[:] = keep
                for name in files:
                    p = cp / name
                    lower = name.lower()
                    # Record model files regardless of activity.
                    if any(lower.endswith(suf) for suf in MODEL_SUFFIXES):
                        try:
                            models_found.append((p, p.stat().st_size))
                        except OSError:
                            pass
                    # Only source files count as development activity.
                    if name in LOCK_FILE_NAMES or name == ".DS_Store":
                        continue
                    ext = p.suffix.lower()
                    if ext not in CODE_EXTENSIONS and name not in CODE_FILE_NAMES:
                        continue
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    if st.st_mtime > latest:
                        latest = st.st_mtime
            commit_t = git_last_commit_epoch(project)
            if commit_t > latest:
                latest = commit_t
            if latest == 0:
                continue
            idle_days = int((now - latest) / 86400)
            if now - latest < threshold:
                continue
            reason = f"stale project {project.name} ({idle_days}d idle)"
            for dpath, dname in deps_found:
                add_path(candidates, dpath, "stale-deps", "aggressive",
                         f"{reason}: rebuildable {dname}")
            for mpath, msize in models_found:
                resolved = mpath.resolve()
                if resolved in candidates:
                    continue
                candidates[resolved] = Candidate(resolved, msize, "stale-model", "manual",
                                                 f"{reason}: model {mpath.name}")
    return candidates


def collect(mode: str, stale_days: int = STALE_DAYS_DEFAULT) -> list[Candidate]:
    candidates: dict[Path, Candidate] = {}
    candidates.update(discover_global())
    candidates.update(scan_app_roots())
    candidates.update(scan_projects(include_aggressive=mode in {"clean-aggressive", "scan"}))
    candidates.update(scan_temp())
    candidates.update(scan_screenshots())
    candidates.update(scan_personal_large())
    # stale-project pass runs last so stale-deps/stale-model labels win over
    # generic project-generated/large-file for the same paths (dict.update
    # would otherwise let later passes overwrite the more specific stale tag).
    candidates.update(scan_stale_projects(stale_days))
    items = list(candidates.values())
    # Keep -1 (unsized Photos library) sorted toward the bottom but visible.
    return sorted(items, key=lambda c: c.size if c.size >= 0 else -1, reverse=True)


def fmt_size(num: int) -> str:
    if num < 0:
        return "n/a"
    units = ["B", "K", "M", "G", "T"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{num}B"


def is_eligible(candidate: Candidate, policy: str = "clean-aggressive") -> bool:
    """Return whether policy permits cleanup, independent of scan/apply execution state."""
    if candidate.risk == "manual" or excluded(candidate.path, candidate.category):
        return False
    if policy == "clean-safe":
        return candidate.risk == "safe"
    return candidate.risk in {"safe", "aggressive"}


def should_delete(candidate: Candidate, mode: str) -> bool:
    return mode in {"clean-safe", "clean-aggressive"} and is_eligible(candidate, mode)


def candidate_id(candidate: Candidate) -> str:
    raw = f"{candidate.path}\0{candidate.category}\0{candidate.risk}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def fingerprint(path: Path) -> dict[str, int | str | bool]:
    st = path.lstat()
    return {
        "path": str(path), "device": st.st_dev, "inode": st.st_ino,
        "size": st.st_size, "mtime_ns": st.st_mtime_ns, "is_symlink": path.is_symlink(),
    }


def move_to_quarantine(candidate: Candidate, operation_id: str) -> tuple[bool, str, dict[str, object] | None]:
    """Move a verified candidate to an operation-scoped Trash folder for recovery."""
    try:
        before = fingerprint(candidate.path)
        if before["is_symlink"]:
            return False, "refused: candidate became a symlink", None
        if excluded(candidate.path, candidate.category) or pruned(candidate.path, candidate.category):
            return False, "refused: candidate is protected", None
        destination_dir = TRASH_ROOT / operation_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{candidate_id(candidate)}-{candidate.path.name}"
        if destination.exists():
            return False, "refused: quarantine destination already exists", None
        shutil.move(str(candidate.path), str(destination))
        entry = {
            "candidate_id": candidate_id(candidate), "original_path": str(candidate.path),
            "quarantine_path": str(destination), "category": candidate.category,
            "risk": candidate.risk, "reason": candidate.reason, "size": candidate.size,
            "fingerprint": before, "status": "quarantined",
        }
        return True, "quarantined", entry
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), None


def save_operation(operation_id: str, mode: str, entries: list[dict[str, object]]) -> Path:
    OPERATIONS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "operation_id": operation_id, "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode, "trash_retention_days": CONFIG["trash_retention_days"], "entries": entries,
    }
    path = OPERATIONS_DIR / f"{operation_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def restore_operation(operation_id: str) -> tuple[int, list[str]]:
    manifest = OPERATIONS_DIR / f"{operation_id}.json"
    if not manifest.exists():
        raise FileNotFoundError(f"operation not found: {operation_id}")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    restored = 0
    messages: list[str] = []
    for entry in payload.get("entries", []):
        if entry.get("status") != "quarantined":
            continue
        source = Path(str(entry["quarantine_path"]))
        target = Path(str(entry["original_path"]))
        if not source.exists():
            messages.append(f"missing quarantine item: {source}")
            continue
        if target.exists():
            messages.append(f"target already exists, skipped: {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        entry["status"] = "restored"
        entry["restored_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        restored += 1
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return restored, messages


def candidate_action(candidate: Candidate, mode: str, actions: dict[Path, str]) -> str:
    if candidate.path in actions:
        return actions[candidate.path]
    if candidate.risk == "manual":
        return "needs review"
    if mode == "scan":
        return "scan only"
    return "would delete" if should_delete(candidate, mode) else "scan only"


def candidate_to_dict(candidate: Candidate, mode: str, actions: dict[Path, str]) -> dict[str, object]:
    return {
        "id": candidate_id(candidate),
        "path": str(candidate.path),
        "size": candidate.size,
        "size_human": fmt_size(candidate.size),
        "category": candidate.category,
        "risk": candidate.risk,
        "reason": candidate.reason,
        "action": candidate_action(candidate, mode, actions),
        "deletable": is_eligible(candidate, "clean-aggressive" if mode == "scan" else mode),
    }


def write_state(
    mode: str,
    apply_flag: bool,
    tools: dict[str, bool],
    candidates: list[Candidate],
    actions: dict[Path, str],
    before_df: str,
    after_df: str,
    stale_days: int = STALE_DAYS_DEFAULT,
) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    safe_total = sum(c.size for c in candidates if c.size >= 0 and is_eligible(c, "clean-safe"))
    aggressive_total = sum(c.size for c in candidates if c.size >= 0 and c.risk == "aggressive" and is_eligible(c))
    total = safe_total + aggressive_total
    selected_total = sum(c.size for c in candidates if c.size >= 0 and should_delete(c, mode))
    manual_total = sum(c.size for c in candidates if c.size >= 0 and c.risk == "manual")
    missing_core = [name for name in CORE_TOOL_CHECKS if not tools.get(name)]
    missing_optional = [name for name in OPTIONAL_TOOL_CHECKS if not tools.get(name)]
    by_category: dict[str, int] = {}
    for c in candidates:
        by_category[c.category] = by_category.get(c.category, 0) + (c.size if c.size >= 0 else 0)
    state = {
        "timestamp": timestamp,
        "mode": mode,
        "apply": apply_flag,
        "deletable_bytes": total,
        "deletable_human": fmt_size(total),
        "safe_bytes": safe_total,
        "safe_human": fmt_size(safe_total),
        "aggressive_bytes": aggressive_total,
        "aggressive_human": fmt_size(aggressive_total),
        "selected_bytes": selected_total,
        "selected_human": fmt_size(selected_total),
        "manual_bytes": manual_total,
        "manual_human": fmt_size(manual_total),
        "candidate_count": len(candidates),
        "tools": tools,
        "core_tools": CORE_TOOL_CHECKS,
        "optional_tools": OPTIONAL_TOOL_CHECKS,
        "missing_tools": missing_core,
        "missing_core_tools": missing_core,
        "missing_optional_tools": missing_optional,
        "disk_before": before_df,
        "disk_after": after_df,
        "dashboard": str(DASHBOARD_PATH),
        "by_category": by_category,
        "config": CONFIG,
        "stale_days_used": stale_days,
        "candidates": [candidate_to_dict(c, mode, actions) for c in candidates],
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    # Also emit dashboard_data.js so the HTML works under file:// (no XHR/CORS).
    data_js_path = DASHBOARD_PATH.parent / "dashboard_data.js"
    data_js_path.write_text(
        "window.__DASHBOARD_DATA__ = " + json.dumps(state, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    # Emit config_data.js so the settings panel can render current config.
    config_js_path = DASHBOARD_PATH.parent / "config_data.js"
    config_js_path.write_text(
        "window.__DASHBOARD_CONFIG__ = " + json.dumps(CONFIG, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )

    # Build a fully self-contained dashboard.html (no external scripts, no CDN, no
    # framework) by injecting the state + config into the design template. This keeps
    # the dashboard working under file:// and inside sandboxed preview webviews where
    # sibling <script src> loads and inlined frameworks can fail to boot.
    _render_dashboard_html(state)

    summary = {
        "timestamp": timestamp,
        "mode": mode,
        "apply": apply_flag,
        "deletable_bytes": total,
        "manual_bytes": manual_total,
        "candidate_count": len(candidates),
    }
    with HISTORY_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return STATE_PATH


def _render_dashboard_html(state: dict) -> None:
    """Produce a fully self-contained dashboard.html from the design template.

    The data and config are inlined directly into the page, so the dashboard has no
    external <script src>, no CDN, and no framework runtime. This is what lets it boot
    reliably under file:// and inside sandboxed preview webviews.
    """
    template_path = DASHBOARD_PATH.with_name("dashboard_template.html")
    if not template_path.exists():
        print(f"warning: {template_path.name} missing; skipped self-contained dashboard build")
        return
    try:
        template = template_path.read_text(encoding="utf-8")
        data_json = json.dumps(state, ensure_ascii=False)
        config_json = json.dumps(CONFIG, ensure_ascii=False)
        html = (
            template
            .replace("/*__DATA__*/null", data_json, 1)
            .replace("/*__CONFIG__*/null", config_json, 1)
        )
        DASHBOARD_PATH.write_text(html, encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: failed to build dashboard.html: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan and clean macOS developer-generated files.")
    parser.add_argument("mode", nargs="?", choices=["scan", "clean-safe", "clean-aggressive"],
                        help="Operation mode. Omit when using --show-config / --set-config.")
    parser.add_argument("--apply", action="store_true", help="Actually delete candidates for the selected mode.")
    parser.add_argument("--limit", type=int, default=0, help="Only print the largest N candidates in terminal output.")
    parser.add_argument("--candidate-id", action="append", default=[], help="Limit this run to a stable candidate ID; repeatable.")
    parser.add_argument("--category", action="append", default=[], help="Limit this run to a category; repeatable.")
    parser.add_argument("--stale-days", type=int, default=None,
                        help=f"Treat projects idle for more than N days as stale (default from config: {STALE_DAYS_DEFAULT}).")
    parser.add_argument("--show-config", action="store_true", help="Print current config.json and exit.")
    parser.add_argument("--set-config", action="store_true",
                        help="Read JSON config from stdin and atomically write validated config.json.")
    parser.add_argument("--restore", metavar="OPERATION_ID", help="Restore every available item from an operation.")
    parser.add_argument("--list-operations", action="store_true", help="List recoverable cleanup operations.")
    args = parser.parse_args()

    # Management modes (no scan).
    if args.list_operations:
        OPERATIONS_DIR.mkdir(parents=True, exist_ok=True)
        for path in sorted(OPERATIONS_DIR.glob("*.json"), reverse=True):
            try:
                op = json.loads(path.read_text(encoding="utf-8"))
                pending = sum(1 for e in op.get("entries", []) if e.get("status") == "quarantined")
                print(f"{op.get('operation_id')}  {op.get('timestamp')}  {op.get('mode')}  recoverable={pending}")
            except (OSError, json.JSONDecodeError):
                continue
        return 0
    if args.restore:
        try:
            restored, messages = restore_operation(args.restore)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"restored: {restored}")
        for message in messages:
            print(f"warning: {message}")
        return 0
    if args.show_config:
        print(json.dumps(CONFIG, ensure_ascii=False, indent=2))
        return 0
    if args.set_config:
        raw = sys.stdin.read().strip()
        if not raw:
            print("error: no JSON on stdin", file=sys.stderr)
            return 2
        try:
            new_cfg = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"error: invalid JSON: {e}", file=sys.stderr)
            return 2
        try:
            save_config(new_cfg)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"config written atomically to {CONFIG_PATH}")
        return 0

    if not args.mode:
        parser.error("mode is required (scan / clean-safe / clean-aggressive) unless using --show-config / --set-config")

    stale_days = args.stale_days if args.stale_days is not None else STALE_DAYS_DEFAULT
    tools = {name: command_exists(name) for name in [*CORE_TOOL_CHECKS, *OPTIONAL_TOOL_CHECKS]}
    before_df = get_free_space()
    candidates = collect(args.mode, stale_days)
    if args.candidate_id:
        wanted_ids = set(args.candidate_id)
        candidates = [c for c in candidates if candidate_id(c) in wanted_ids]
    if args.category:
        wanted_categories = set(args.category)
        candidates = [c for c in candidates if c.category in wanted_categories]

    actions: dict[Path, str] = {}
    if args.apply:
        operation_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        operation_entries: list[dict[str, object]] = []
        for candidate in candidates:
            if should_delete(candidate, args.mode):
                ok, message, entry = move_to_quarantine(candidate, operation_id)
                actions[candidate.path] = message if ok else f"failed: {message}"
                if entry:
                    operation_entries.append(entry)
        if operation_entries:
            operation_path = save_operation(operation_id, args.mode, operation_entries)
            print(f"operation_id: {operation_id}")
            print(f"operation_manifest: {operation_path}")
            print(f"restore_command: python3 {Path(__file__).resolve()} --restore {operation_id}")

    after_df = get_free_space()
    state = write_state(args.mode, args.apply, tools, candidates, actions, before_df, after_df, stale_days)

    visible = candidates[: args.limit] if args.limit else candidates
    potential = sum(c.size for c in candidates if c.size >= 0 and is_eligible(c))
    selected = sum(c.size for c in candidates if c.size >= 0 and should_delete(c, args.mode))
    manual_total = sum(c.size for c in candidates if c.size >= 0 and c.risk == "manual")
    stale_deps_total = sum(c.size for c in candidates if c.size >= 0 and c.category == "stale-deps")
    stale_models_total = sum(c.size for c in candidates if c.size >= 0 and c.category == "stale-model")
    stale_project_names = sorted({
        c.reason.split(" (")[0].replace("stale project ", "")
        for c in candidates if c.category in {"stale-deps", "stale-model"}
    })
    print(f"mode: {args.mode}")
    print(f"apply: {args.apply}")
    print(f"potentially_cleanable: {fmt_size(potential)}")
    print(f"selected_in_mode: {fmt_size(selected)}")
    print(f"needs_review (manual): {fmt_size(manual_total)}")
    print(f"stale_deps (aggressive): {fmt_size(stale_deps_total)}")
    print(f"stale_models (manual): {fmt_size(stale_models_total)}")
    if stale_project_names:
        print(f"stale_projects: {', '.join(stale_project_names)}")
    print(f"candidates: {len(candidates)}")
    print(f"state_json: {state}")
    print(f"dashboard_html: {DASHBOARD_PATH}")
    missing_core = [name for name in CORE_TOOL_CHECKS if not tools.get(name)]
    missing_optional = [name for name in OPTIONAL_TOOL_CHECKS if not tools.get(name)]
    print("missing_core_tools: " + (", ".join(missing_core) if missing_core else "none"))
    print("missing_optional_tools: " + (", ".join(missing_optional) if missing_optional else "none"))
    for c in visible:
        action = candidate_action(c, args.mode, actions)
        print(f"{fmt_size(c.size):>8}  {c.risk:<10}  {c.category:<14}  {action:<13}  {c.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
