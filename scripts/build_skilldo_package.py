#!/usr/bin/env python3
"""Build and verify the local SkillDo bundle from this repository's source files.

The repository root remains authoritative. The generated bundle is a deterministic
projection containing only the skill entrypoint and runtime/support files needed
by the installed skill; it never copies runtime data, generated dashboard data,
dependencies, Git metadata, or arbitrary repository files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "skills" / "mac-dev-cleanup"
FORMAT_VERSION = 1
PACKAGE_FILES = (
    "SKILL.md",
    "dashboard_template.html",
    "agents/openai.yaml",
    "scripts/mac_dev_cleanup.py",
    "scripts/export_summary.py",
    "scripts/web_server.py",
    "scripts/check_skill_routing.py",
)
LEGACY_PACKAGE_FILES = tuple(path for path in PACKAGE_FILES if path != "scripts/export_summary.py")
MANIFEST = "manifest.json"
EXPECTED_PACKAGE_FILES = frozenset((*PACKAGE_FILES, MANIFEST))
RUNTIME_FILES = ("dashboard.html", "dashboard_data.js", "config_data.js")
FORBIDDEN_NAMES = {
    ".git",
    "node_modules",
    "config.json",
    "state.json",
    "history.jsonl",
    "dashboard.html",
    "dashboard_data.js",
    "config_data.js",
}


def fail(message: str) -> NoReturn:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(directory: Path) -> dict:
    manifest_path = directory / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        fail(f"missing regular {MANIFEST} in {directory}")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid {MANIFEST}: {exc}")
    if value.get("format") != FORMAT_VERSION or value.get("source") != "mac-dev-cleanup":
        fail(f"unsupported package manifest: {manifest_path}")
    if value.get("runtimeFiles", list(RUNTIME_FILES)) != list(RUNTIME_FILES):
        fail(f"runtime output allowlist differs from the declared SkillDo package: {manifest_path}")
    return value


def check_bundle(directory: Path, *, allow_legacy: bool = False) -> None:
    if directory.is_symlink() or not directory.is_dir():
        fail(f"bundle must be a real directory: {directory}")
    manifest = load_manifest(directory)
    records = manifest.get("files")
    if not isinstance(records, list):
        fail("manifest files must be a list")
    paths = [record.get("path") for record in records if isinstance(record, dict)]
    permitted_sets = {frozenset(PACKAGE_FILES)}
    if allow_legacy:
        permitted_sets.add(frozenset(LEGACY_PACKAGE_FILES))
    if len(paths) != len(records) or frozenset(paths) not in permitted_sets:
        fail("manifest file list does not match the declared SkillDo bundle")

    actual: set[str] = set()
    for path in directory.rglob("*"):
        relative = path.relative_to(directory).as_posix()
        if path.is_symlink():
            fail(f"bundle contains a symbolic link: {relative}")
        if path.is_file():
            actual.add(relative)
        elif path.is_dir() and path.name in FORBIDDEN_NAMES:
            fail(f"bundle contains forbidden runtime/project content: {relative}")
    expected_inventory = frozenset((*paths, MANIFEST))
    if actual != expected_inventory:
        fail(f"bundle file inventory differs: {sorted(actual ^ expected_inventory)}")

    for record in records:
        path = directory / record["path"]
        if sha256(path) != record.get("sha256"):
            fail(f"bundle file differs from its manifest: {record['path']}")

    route_check = subprocess.run(
        [sys.executable, str(directory / "scripts" / "check_skill_routing.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    if route_check.returncode:
        fail(f"bundle routing check failed: {route_check.stderr.strip() or route_check.stdout.strip()}")


def expected_manifest() -> dict:
    files = []
    for relative in PACKAGE_FILES:
        source = ROOT / relative
        if source.is_symlink() or not source.is_file():
            fail(f"required package source is missing or not a regular file: {relative}")
        files.append({"path": relative, "sha256": sha256(source)})
    return {"format": FORMAT_VERSION, "source": "mac-dev-cleanup", "files": files,
            "runtimeFiles": list(RUNTIME_FILES)}


def build() -> None:
    manifest = expected_manifest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(tempfile.mkdtemp(prefix=".mac-dev-cleanup-stage-", dir=OUTPUT.parent))
    try:
        for record in manifest["files"]:
            relative = record["path"]
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        (staging / MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        check_bundle(staging)

        install_bundle(staging, OUTPUT)
        staging = None
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)

    check_bundle(OUTPUT)
    print(f"[OK] Built and verified SkillDo bundle: {OUTPUT}")


def install_bundle(staging: Path, output: Path) -> None:
    """Atomically replace a package directory, restoring the old copy on failure."""
    previous = output.with_name(f".{output.name}.previous")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        # Permit a verified prior package when the allowlist grows. It is
        # replaced only after the staged current package passes full checks.
        check_bundle(output, allow_legacy=True)
        if previous.exists() or previous.is_symlink():
            fail(f"refusing to overwrite existing recovery path: {previous}")
        output.rename(previous)
    try:
        staging.rename(output)
    except OSError:
        if previous.exists() and not output.exists():
            previous.rename(output)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("build", "check"), default="build")
    args = parser.parse_args()
    if args.action == "build":
        build()
    else:
        check_bundle(OUTPUT)
        print(f"[OK] SkillDo bundle is valid: {OUTPUT}")


if __name__ == "__main__":
    main()
