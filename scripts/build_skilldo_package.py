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
import re
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
    "scripts/local_services.py",
    "scripts/local_services_cli.py",
    "scripts/cli_inventory.py",
    "scripts/local_cli_tools_cli.py",
    "scripts/login_items.py",
    "scripts/local_login_items_cli.py",
    "scripts/check_skill_routing.py",
)
PRE_CLI_TOOLS_PACKAGE_FILES = tuple(path for path in PACKAGE_FILES if path not in {
    "scripts/cli_inventory.py", "scripts/local_cli_tools_cli.py"
})
PRE_LOGIN_PACKAGE_FILES = tuple(
    path for path in PRE_CLI_TOOLS_PACKAGE_FILES
    if path not in {"scripts/login_items.py", "scripts/local_login_items_cli.py"}
)
PRE_CLI_PACKAGE_FILES = tuple(path for path in PRE_LOGIN_PACKAGE_FILES if path != "scripts/local_services_cli.py")
LEGACY_PACKAGE_FILES = tuple(
    path for path in PRE_LOGIN_PACKAGE_FILES if path not in {"scripts/export_summary.py", "scripts/local_services_cli.py"}
)
PREVIOUS_PACKAGE_FILES = tuple(
    path for path in PRE_LOGIN_PACKAGE_FILES if path not in {"scripts/local_services.py", "scripts/local_services_cli.py"}
)
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
    permitted_sets = _permitted_package_sets(allow_legacy)
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


def _permitted_package_sets(allow_legacy: bool) -> set[frozenset[str]]:
    permitted_sets = {frozenset(PACKAGE_FILES)}
    if allow_legacy:
        permitted_sets.add(frozenset(PRE_CLI_TOOLS_PACKAGE_FILES))
        permitted_sets.add(frozenset(PRE_LOGIN_PACKAGE_FILES))
        permitted_sets.add(frozenset(PRE_CLI_PACKAGE_FILES))
        permitted_sets.add(frozenset(LEGACY_PACKAGE_FILES))
        permitted_sets.add(frozenset(PREVIOUS_PACKAGE_FILES))
        # Accept the intermediate package combinations produced while the
        # CLI, export, and login-item files were introduced independently.
        permitted_sets.add(frozenset(set(PACKAGE_FILES) - {
            "scripts/local_services_cli.py", "scripts/export_summary.py",
            "scripts/login_items.py", "scripts/local_login_items_cli.py",
        }))
        permitted_sets.add(frozenset(set(PACKAGE_FILES) - {
            "scripts/local_services_cli.py", "scripts/login_items.py",
            "scripts/local_login_items_cli.py",
        }))
        permitted_sets.add(frozenset(set(PACKAGE_FILES) - {
            "scripts/login_items.py", "scripts/local_login_items_cli.py",
        }))
    return permitted_sets


def _is_known_repairable_bundle(directory: Path) -> bool:
    """Recognize a damaged SkillDo package without claiming arbitrary data.

    A stale hash or a missing declared package file is repairable. Invalid or
    foreign manifests, symlinks, and any undeclared filesystem content are
    not sufficient proof that this directory belongs to this builder.
    """
    if directory.is_symlink() or not directory.is_dir():
        return False
    manifest_path = directory / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if (not isinstance(manifest, dict)
            or manifest.get("format") != FORMAT_VERSION
            or manifest.get("source") != "mac-dev-cleanup"
            or manifest.get("runtimeFiles", list(RUNTIME_FILES)) != list(RUNTIME_FILES)):
        return False
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        return False
    paths = []
    for record in records:
        if not isinstance(record, dict):
            return False
        path = record.get("path")
        digest = record.get("sha256")
        if (not isinstance(path, str) or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            return False
        paths.append(path)
    if (len(paths) != len(set(paths))
            or frozenset(paths) not in _permitted_package_sets(allow_legacy=True)):
        return False

    expected_files = set(paths) | {MANIFEST}
    expected_dirs = {
        parent.as_posix()
        for relative in expected_files
        for parent in Path(relative).parents
        if parent.as_posix() != "."
    }
    try:
        for path in directory.rglob("*"):
            relative = path.relative_to(directory).as_posix()
            if path.is_symlink():
                return False
            if path.is_dir():
                if relative not in expected_dirs:
                    return False
            elif path.is_file():
                if relative not in expected_files:
                    return False
            else:
                return False
    except OSError:
        return False
    return True


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
    check_bundle(staging)
    previous = output.with_name(f".{output.name}.previous")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        # Permit a verified prior package when the allowlist grows. A package
        # with a stale manifest/hash must also be replaceable: the build
        # command is the repair path for exactly that interrupted or older
        # install state. Keep the old directory as the normal recovery sibling
        # before installing the already-verified staging directory.
        try:
            check_bundle(output, allow_legacy=True)
        except (SystemExit, OSError):
            if not _is_known_repairable_bundle(output):
                fail(f"refusing to replace an unverified existing directory: {output}")
            print(f"[WARN] Replacing invalid existing SkillDo bundle: {output}", file=sys.stderr)
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
