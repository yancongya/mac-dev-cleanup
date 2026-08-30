#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt  # noqa: F401  (kept for parity with production imports)
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_config_rejects_bad_wechat_keep_months(self) -> None:
        with self.assertRaises(ValueError):
            cleanup.validate_config({"wechat_media_keep_months": 0})
        with self.assertRaises(ValueError):
            cleanup.validate_config({"wechat_media_keep_months": "1"})
        cfg = cleanup.validate_config({"wechat_media_keep_months": 3})
        self.assertEqual(cfg["wechat_media_keep_months"], 3)


class WeChatMonthTests(unittest.TestCase):
    def test_month_key_strict(self) -> None:
        self.assertEqual(cleanup.wechat_month_key("2026-07"), (2026, 7))
        self.assertIsNone(cleanup.wechat_month_key("2026-13"))
        self.assertIsNone(cleanup.wechat_month_key("2026-00"))
        self.assertIsNone(cleanup.wechat_month_key("26-07"))
        self.assertIsNone(cleanup.wechat_month_key("2026-7"))
        self.assertIsNone(cleanup.wechat_month_key("2026-07x"))
        self.assertIsNone(cleanup.wechat_month_key("db_storage"))

    def test_cutoff_keeps_current_month_only(self) -> None:
        def fake_today(year: int, month: int):
            day = MagicMock()
            day.year = year
            day.month = month
            return day

        with patch.object(cleanup, "dt") as mock_dt:
            mock_dt.date.today.return_value = fake_today(2026, 8)
            self.assertEqual(cleanup._wechat_cutoff(1), (2026, 8))
            self.assertEqual(cleanup._wechat_cutoff(2), (2026, 7))
            mock_dt.date.today.return_value = fake_today(2026, 1)
            self.assertEqual(cleanup._wechat_cutoff(1), (2026, 1))
            self.assertEqual(cleanup._wechat_cutoff(2), (2025, 12))

    def test_media_month_shape_whitelist(self) -> None:
        base = cleanup.WECHAT_FILES / "wxid_abc_1dd5"
        ok_shapes = [
            base / "msg" / "video" / "2026-07",
            base / "msg" / "file" / "2026-01",
            base / "msg" / "attach" / ("0" * 32) / "2026-05",
            base / "cache" / "2026-07",
        ]
        for p in ok_shapes:
            self.assertIsNotNone(cleanup.wechat_media_month(p), p)
        bad_shapes = [
            base / "db_storage" / "message",
            base / "msg" / "attach" / ("0" * 32),              # month level missing
            base / "msg" / "attach" / "nothex" / "2026-05",    # not a 32-hex hash
            base / "msg" / "attach" / ("0" * 32) / "latest",   # not YYYY-MM
            base / "msg" / "video" / "2026-07" / "extra",    # deeper than a month dir
            base / "business" / "favorite" / "2026-07",
            cleanup.WECHAT_FILES / "all_users" / "msg" / "video" / "2026-07",
            cleanup.WECHAT_FILES / "Backup" / "cache" / "2026-07",
        ]
        for p in bad_shapes:
            self.assertIsNone(cleanup.wechat_media_month(p), p)

    def test_exempt_only_whitelisted_wechat_paths(self) -> None:
        self.assertTrue(cleanup.wechat_exempt(cleanup.WECHAT_APP_DATA / "radium"))
        self.assertTrue(cleanup.wechat_exempt(
            cleanup.WECHAT_FILES / "wxid_abc_1dd5" / "msg" / "video" / "2026-07"))
        # Container paths outside the whitelist stay pruned.
        self.assertFalse(cleanup.wechat_exempt(cleanup.WECHAT_CONTAINER / "Data" / "Documents"))
        self.assertFalse(cleanup.wechat_exempt(cleanup.WECHAT_CONTAINER / "Data" / "whatever"))
        # Unrelated paths are never exempt.
        self.assertFalse(cleanup.wechat_exempt(Path("/tmp")))

    def test_pruned_respects_wechat_whitelist(self) -> None:
        month = cleanup.WECHAT_FILES / "wxid_abc_1dd5" / "msg" / "video" / "2026-07"
        with patch.object(cleanup, "EXCLUDE_PATHS", []), patch.object(cleanup, "PROTECTED_PROJECTS", []), \
                patch.object(cleanup, "EXCLUDE_GLOBS", ()), patch.object(cleanup, "PROTECTED_CATEGORIES", set()):
            self.assertFalse(cleanup.pruned(month))
            # User-level exclusion still protects WeChat paths.
            with patch.object(cleanup, "EXCLUDE_PATHS", [cleanup.WECHAT_CONTAINER]):
                self.assertTrue(cleanup.pruned(month))


class TauriBuildTests(unittest.TestCase):
    """Tauri / Vite build by-products must be classified, and packaged
    installers must never be auto-removed."""

    def _scan(self, root: Path, aggressive: bool = True):
        with patch.object(cleanup, "PROJECT_ROOTS", [root]), \
                patch.object(cleanup, "EXCLUDE_PATHS", []), \
                patch.object(cleanup, "PROTECTED_PROJECTS", []), \
                patch.object(cleanup, "EXCLUDE_GLOBS", ()), \
                patch.object(cleanup, "PROTECTED_CATEGORIES", set()):
            return {c.path.name: c for c in cleanup.scan_projects(aggressive).values()}

    def test_gen_schemas_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gen = root / "app" / "src-tauri" / "gen" / "schemas"
            gen.mkdir(parents=True)
            (gen / "desktop-schema.json").write_text("{}")
            found = self._scan(root, aggressive=False)
            self.assertEqual(found["gen"].risk, "safe")
            self.assertEqual(found["gen"].category, "project-generated")

    def test_target_is_aggressive_and_labeled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "app" / "src-tauri" / "target" / "debug" / "deps"
            target.mkdir(parents=True)
            (target / "libapp.rlib").write_bytes(b"binary")
            found = self._scan(root)
            self.assertEqual(found["target"].risk, "aggressive")
            self.assertIn("Tauri/Rust build directory", found["target"].reason)

    def test_packaged_target_is_manual(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "app" / "src-tauri" / "target" / "release" / "bundle" / "dmg"
            bundle.mkdir(parents=True)
            (bundle / "SkillDo_1.0.0_aarch64.dmg").write_bytes(b"pkg")
            found = self._scan(root)
            self.assertEqual(found["target"].risk, "manual")
            self.assertFalse(cleanup.is_eligible(found["target"], "clean-aggressive"))

    def test_stale_pass_does_not_promote_packaged_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "app"
            bundle = app / "src-tauri" / "target" / "release" / "bundle" / "macos"
            bundle.mkdir(parents=True)
            (bundle / "SkillDo.app").mkdir()
            source = app / "src" / "main.rs"
            source.parent.mkdir(parents=True)
            source.write_text("fn main() {}")
            old = time.time() - 200 * 86400
            os.utime(source, (old, old))
            with patch.object(cleanup, "PROJECT_ROOTS", [root]), \
                    patch.object(cleanup, "EXCLUDE_PATHS", []), \
                    patch.object(cleanup, "PROTECTED_PROJECTS", []), \
                    patch.object(cleanup, "EXCLUDE_GLOBS", ()):
                stale = cleanup.scan_stale_projects(90)
            paths = [c.path.name for c in stale.values()]
            self.assertNotIn("target", paths)

    def test_unrelated_gen_directory_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gen = root / "app" / "gen" / "handwritten"
            gen.mkdir(parents=True)
            (gen / "api.ts").write_text("export const a = 1;")
            found = self._scan(root, aggressive=False)
            self.assertNotIn("gen", found)

    def test_vite_timestamp_config_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = root / "app"
            app.mkdir()
            (app / "vite.config.ts.timestamp-1756-abc123.mjs").write_text("// tmp")
            found = self._scan(root, aggressive=False)
            entry = next(c for c in found.values() if "timestamp-" in c.path.name)
            self.assertEqual(entry.risk, "safe")

    def test_dist_ssr_is_aggressive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = root / "app" / "dist-ssr"
            dist.mkdir(parents=True)
            (dist / "server.js").write_text("// ssr")
            found = self._scan(root)
            self.assertEqual(found["dist-ssr"].risk, "aggressive")


class BuildArtifactConfigTests(unittest.TestCase):
    """Build by-product rules are user policy: they must come from
    `config.json: build_artifacts`, not from hardcoded names in the script."""

    def _module_with_config(self, cfg: dict, tag: str):
        """Reload the script against a temporary policy file (MDC_CONFIG)."""
        cfg_dir = tempfile.mkdtemp(prefix="mdc-cfg-")
        cfg_file = Path(cfg_dir) / "config.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        previous = os.environ.get("MDC_CONFIG")
        os.environ["MDC_CONFIG"] = str(cfg_file)
        try:
            name = f"mdc_reload_{tag}"
            spec = importlib.util.spec_from_file_location(
                name, Path(__file__).resolve().parent / "mac_dev_cleanup.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        finally:
            if previous is None:
                os.environ.pop("MDC_CONFIG", None)
            else:
                os.environ["MDC_CONFIG"] = previous
        return module

    def _scan_with_config(self, cfg: dict, tag: str):
        module = self._module_with_config(cfg, tag)
        root = (Path(tempfile.mkdtemp(prefix="mdc-proj-")) / "proj").resolve()
        app = root / "app"
        (app / "src-tauri" / "gen" / "schemas").mkdir(parents=True)
        (app / "src-tauri" / "gen" / "schemas" / "s.json").write_text("{}")
        (app / "src-tauri" / "target" / "debug").mkdir(parents=True)
        (app / "dist-ssr").mkdir()
        (app / "dist-ssr" / "s.js").write_text("x")
        (app / ".vite-temp").mkdir()
        (app / ".vite-temp" / "c.js").write_text("x")
        (app / "vite.config.ts.timestamp-1756-abc.mjs").write_text("//")
        (app / "mybuild").mkdir()
        with patch.object(module, "PROJECT_ROOTS", [root]), \
                patch.object(module, "EXCLUDE_PATHS", []), \
                patch.object(module, "PROTECTED_PROJECTS", []), \
                patch.object(module, "EXCLUDE_GLOBS", ()):
            found = module.scan_projects(True)
        return {c.path.name: c for c in found.values()}

    def test_defaults_enable_tauri_and_vite_rules(self) -> None:
        found = self._scan_with_config({"build_artifacts": {}}, "d1")
        self.assertEqual(found["gen"].risk, "safe")
        self.assertEqual(found["target"].risk, "aggressive")
        self.assertEqual(found["dist-ssr"].risk, "aggressive")
        self.assertEqual(found[".vite-temp"].risk, "safe")

    def test_config_can_disable_rules(self) -> None:
        found = self._scan_with_config(
            {"build_artifacts": {"tauri_parents": [], "safe_dirs": [],
                                 "aggressive_dirs": [], "safe_file_globs": []}}, "d2")
        self.assertNotIn("gen", found)
        self.assertNotIn("dist-ssr", found)
        self.assertNotIn(".vite-temp", found)
        # `target` stays: it is a built-in rule the config can only add to.
        self.assertEqual(found["target"].risk, "aggressive")

    def test_config_can_add_custom_dirs(self) -> None:
        found = self._scan_with_config(
            {"build_artifacts": {"aggressive_dirs": ["dist-ssr", "mybuild"]}}, "d3")
        self.assertEqual(found["mybuild"].risk, "aggressive")

    def test_bundle_markers_fall_back_to_builtin(self) -> None:
        # Emptying the deliverable markers must not disable the protection.
        cfg = cleanup.validate_config({"build_artifacts": {"bundle_markers": []}})
        self.assertEqual(cfg["build_artifacts"]["bundle_markers"],
                         list(cleanup.FALLBACK_BUNDLE_MARKERS))

    def test_build_artifacts_validation(self) -> None:
        with self.assertRaises(ValueError):
            cleanup.validate_config({"build_artifacts": {"safe_dirs": "nope"}})
        with self.assertRaises(ValueError):
            cleanup.validate_config({"build_artifacts": {"nonsense": []}})
        with self.assertRaises(ValueError):
            cleanup.validate_config({"build_artifacts": [1, 2]})
        merged = cleanup.validate_config({"build_artifacts": {"safe_dirs": ["  .tmp ", ".tmp"]}})
        self.assertEqual(merged["build_artifacts"]["safe_dirs"], [".tmp"])
        # Partial override keeps the sibling defaults.
        self.assertEqual(merged["build_artifacts"]["tauri_build_dirs"], ["target"])


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
