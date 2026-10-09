#!/usr/bin/env python3
"""Exercise the generated SkillDo bundle boundary and rollback behavior."""

from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
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
        for forbidden in ("config.json", "state.json", "history.jsonl", "dashboard_data.js", "config_data.js"):
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


if __name__ == "__main__":
    unittest.main()
