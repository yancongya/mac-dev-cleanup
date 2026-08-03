#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mac_dev_cleanup as cleanup


class ConfigTests(unittest.TestCase):
    def test_config_rejects_unknown_keys(self) -> None:
        with self.assertRaises(ValueError):
            cleanup.validate_config({"surprise": True})

    def test_config_merges_partial_thresholds(self) -> None:
        cfg = cleanup.validate_config({"stale_days": 20, "thresholds": {"large_file_mb": 88}})
        self.assertEqual(cfg["stale_days"], 20)
        self.assertEqual(cfg["thresholds"]["large_file_mb"], 88)
        self.assertEqual(cfg["thresholds"]["app_cache_min_mb"], 50)


class RecoveryTests(unittest.TestCase):
    def test_quarantine_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "project" / ".pytest_cache"
            original.mkdir(parents=True)
            (original / "cache.bin").write_bytes(b"abc")
            trash = root / "trash"
            operations = root / "operations"
            candidate = cleanup.Candidate(original, 3, "project-generated", "safe", "test")
            with patch.object(cleanup, "TRASH_ROOT", trash), patch.object(cleanup, "OPERATIONS_DIR", operations), \
                    patch.object(cleanup, "PRUNE_PATHS", []), patch.object(cleanup, "EXCLUDE_PATHS", []), \
                    patch.object(cleanup, "PROTECTED_PROJECTS", []), patch.object(cleanup, "EXCLUDE_GLOBS", ()), \
                    patch.object(cleanup, "PROTECTED_CATEGORIES", set()):
                ok, message, entry = cleanup.move_to_quarantine(candidate, "test-op")
                self.assertTrue(ok, message)
                self.assertFalse(original.exists())
                self.assertIsNotNone(entry)
                cleanup.save_operation("test-op", "clean-safe", [entry])
                restored, warnings = cleanup.restore_operation("test-op")
                self.assertEqual(restored, 1)
                self.assertEqual(warnings, [])
                self.assertTrue((original / "cache.bin").exists())
                manifest = json.loads((operations / "test-op.json").read_text())
                self.assertEqual(manifest["entries"][0]["status"], "restored")


if __name__ == "__main__":
    unittest.main()
