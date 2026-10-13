#!/usr/bin/env python3
"""Exercise the generated SkillDo bundle boundary and rollback behavior."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_skilldo_package.py"
SPEC = importlib.util.spec_from_file_location("build_skilldo_package", BUILDER_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class SkillDoPackageTests(unittest.TestCase):
    def test_bundle_contains_only_declared_skill_files(self) -> None:
        output = builder.OUTPUT
        builder.check_bundle(output)
        actual = {
            path.relative_to(output).as_posix()
            for path in output.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual, builder.EXPECTED_PACKAGE_FILES)
        self.assertEqual(output, ROOT / "skills" / "mac-dev-cleanup")
        for forbidden in ("config.json", "state.json", "history.jsonl", "dashboard.html",
                          "dashboard_data.js", "config_data.js"):
            self.assertNotIn(forbidden, actual)

    def test_failed_package_swap_restores_previous_bundle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mdc-bundle-rollback-") as directory:
            parent = Path(directory)
            output = parent / "mac-dev-cleanup"
            staging = parent / ".mac-dev-cleanup-stage"
            previous = output.with_name(f".{output.name}.previous")
            shutil.copytree(builder.OUTPUT, output)
            shutil.copytree(builder.OUTPUT, staging)
            old_files = {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }

            real_rename = Path.rename

            def fail_new_package_rename(path: Path, target: str | Path) -> Path:
                if path == staging and Path(target) == output:
                    raise OSError("injected package install failure")
                return real_rename(path, target)

            with patch.object(Path, "rename", fail_new_package_rename):
                with self.assertRaisesRegex(OSError, "injected package install failure"):
                    builder.install_bundle(staging, output)

            builder.check_bundle(output)
            restored_files = {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(restored_files, old_files)
            self.assertFalse(previous.exists())

    def test_invalid_previous_bundle_is_replaced_during_rebuild(self) -> None:
        """A stale manifest must not block the build repair path."""
        with tempfile.TemporaryDirectory(prefix="mdc-bundle-repair-") as directory:
            parent = Path(directory)
            output = parent / "mac-dev-cleanup"
            staging = parent / ".mac-dev-cleanup-stage"
            shutil.copytree(builder.OUTPUT, output)
            (output / "SKILL.md").write_text("stale package\n", encoding="utf-8")
            shutil.copytree(builder.OUTPUT, staging)

            builder.install_bundle(staging, output)
            builder.check_bundle(output)
            self.assertEqual((output / "SKILL.md").read_bytes(),
                             (builder.OUTPUT / "SKILL.md").read_bytes())
            self.assertFalse(output.with_name(f".{output.name}.previous").exists())

    def test_unverified_existing_directory_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mdc-unverified-output-") as directory:
            parent = Path(directory)
            output = parent / "mac-dev-cleanup"
            staging = parent / ".mac-dev-cleanup-stage"
            output.mkdir()
            user_file = output / "keep.txt"
            user_file.write_text("user content\n", encoding="utf-8")
            shutil.copytree(builder.OUTPUT, staging)

            with self.assertRaises(SystemExit):
                builder.install_bundle(staging, output)

            self.assertEqual(user_file.read_text(encoding="utf-8"), "user content\n")
            self.assertTrue(staging.is_dir())
            self.assertFalse(output.with_name(f".{output.name}.previous").exists())

    def test_known_manifest_with_extra_user_file_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mdc-extra-output-") as directory:
            parent = Path(directory)
            output = parent / "mac-dev-cleanup"
            staging = parent / ".mac-dev-cleanup-stage"
            shutil.copytree(builder.OUTPUT, output)
            user_file = output / "notes.txt"
            user_file.write_text("keep alongside the bundle\n", encoding="utf-8")
            shutil.copytree(builder.OUTPUT, staging)

            with self.assertRaises(SystemExit):
                builder.install_bundle(staging, output)

            self.assertEqual(user_file.read_text(encoding="utf-8"), "keep alongside the bundle\n")
            self.assertEqual((output / "SKILL.md").read_bytes(),
                             (builder.OUTPUT / "SKILL.md").read_bytes())

    def test_missing_declared_package_file_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mdc-missing-package-file-") as directory:
            parent = Path(directory)
            output = parent / "mac-dev-cleanup"
            staging = parent / ".mac-dev-cleanup-stage"
            shutil.copytree(builder.OUTPUT, output)
            (output / "scripts" / "local_services_cli.py").unlink()
            shutil.copytree(builder.OUTPUT, staging)

            builder.install_bundle(staging, output)
            builder.check_bundle(output)
            self.assertEqual((output / "scripts" / "local_services_cli.py").read_bytes(),
                             (builder.OUTPUT / "scripts" / "local_services_cli.py").read_bytes())

    def test_failed_repair_swap_restores_damaged_skilldo_bundle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mdc-damaged-rollback-") as directory:
            parent = Path(directory)
            output = parent / "mac-dev-cleanup"
            staging = parent / ".mac-dev-cleanup-stage"
            previous = output.with_name(f".{output.name}.previous")
            shutil.copytree(builder.OUTPUT, output)
            (output / "SKILL.md").write_text("damaged but recognized\n", encoding="utf-8")
            damaged_files = {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*") if path.is_file()
            }
            shutil.copytree(builder.OUTPUT, staging)

            real_rename = Path.rename

            def fail_new_package_rename(path: Path, target: str | Path) -> Path:
                if path == staging and Path(target) == output:
                    raise OSError("injected package repair failure")
                return real_rename(path, target)

            with patch.object(Path, "rename", fail_new_package_rename):
                with self.assertRaisesRegex(OSError, "injected package repair failure"):
                    builder.install_bundle(staging, output)

            restored_files = {
                path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob("*") if path.is_file()
            }
            self.assertEqual(restored_files, damaged_files)
            self.assertFalse(previous.exists())

    def test_verified_previous_bundle_is_accepted_only_for_upgrade(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mdc-legacy-bundle-") as directory:
            legacy = Path(directory) / "mac-dev-cleanup"
            shutil.copytree(builder.OUTPUT, legacy)
            (legacy / "scripts" / "local_services_cli.py").unlink()
            (legacy / "scripts" / "export_summary.py").unlink()
            (legacy / "scripts" / "login_items.py").unlink()
            (legacy / "scripts" / "local_login_items_cli.py").unlink()
            manifest_path = legacy / builder.MANIFEST
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"] = [record for record in manifest["files"] if record["path"] not in {
                "scripts/local_services_cli.py", "scripts/export_summary.py",
                "scripts/login_items.py", "scripts/local_login_items_cli.py",
            }]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")

            builder.check_bundle(legacy, allow_legacy=True)
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    builder.check_bundle(legacy)

    def test_pre_cli_bundle_is_accepted_only_for_upgrade(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mdc-pre-cli-bundle-") as directory:
            previous = Path(directory) / "mac-dev-cleanup"
            shutil.copytree(builder.OUTPUT, previous)
            (previous / "scripts" / "local_services_cli.py").unlink()
            (previous / "scripts" / "login_items.py").unlink()
            (previous / "scripts" / "local_login_items_cli.py").unlink()
            manifest_path = previous / builder.MANIFEST
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"] = [record for record in manifest["files"]
                                 if record["path"] not in {"scripts/local_services_cli.py",
                                                            "scripts/login_items.py",
                                                            "scripts/local_login_items_cli.py"}]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")

            builder.check_bundle(previous, allow_legacy=True)
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    builder.check_bundle(previous)

    def test_pre_login_items_bundle_is_accepted_only_for_upgrade(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mdc-pre-login-items-bundle-") as directory:
            previous = Path(directory) / "mac-dev-cleanup"
            shutil.copytree(builder.OUTPUT, previous)
            for path in ("scripts/login_items.py", "scripts/local_login_items_cli.py"):
                (previous / path).unlink()
            manifest_path = previous / builder.MANIFEST
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"] = [record for record in manifest["files"]
                                 if record["path"] not in {"scripts/login_items.py", "scripts/local_login_items_cli.py"}]
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
            builder.check_bundle(previous, allow_legacy=True)
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    builder.check_bundle(previous)


if __name__ == "__main__":
    unittest.main()
