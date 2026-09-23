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


class ConfigLocationTests(unittest.TestCase):
    """config.json must live outside the Skill directory.

    SkillDo manages that directory as a content-only mirror of the Git repo and
    `skilldo update` rebuilds it wholesale, so a policy file kept there would be
    deleted — silently resetting this machine's settings to defaults.
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="mdc-cfg-loc-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_config_path_is_outside_the_skill_directory(self) -> None:
        if os.environ.get("MDC_CONFIG"):
            self.skipTest("MDC_CONFIG overrides the policy path by design")
        skill_dir = Path(cleanup.__file__).resolve().parent.parent
        self.assertEqual(cleanup.CONFIG_PATH.parent, cleanup.LOG_DIR)
        self.assertEqual(cleanup.LEGACY_CONFIG_PATH, skill_dir / "config.json")
        self.assertNotEqual(cleanup.CONFIG_PATH, cleanup.LEGACY_CONFIG_PATH)

    def test_legacy_config_is_adopted_once(self) -> None:
        legacy = self.root / "skill" / "config.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text('{"stale_days": 7}', encoding="utf-8")
        target = self.root / "logs" / "config.json"

        self.assertTrue(cleanup.adopt_legacy_config(legacy, target))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["stale_days"], 7)
        self.assertFalse(legacy.exists(), "legacy policy should be moved, not duplicated")

    def test_existing_target_wins_over_legacy(self) -> None:
        legacy = self.root / "config.json"
        legacy.write_text('{"stale_days": 7}', encoding="utf-8")
        target = self.root / "logs" / "config.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"stale_days": 11}', encoding="utf-8")

        self.assertFalse(cleanup.adopt_legacy_config(legacy, target))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["stale_days"], 11)
        self.assertTrue(legacy.exists(), "a live policy must never be clobbered")

    def test_missing_legacy_is_a_noop(self) -> None:
        target = self.root / "logs" / "config.json"
        self.assertFalse(cleanup.adopt_legacy_config(self.root / "absent.json", target))
        self.assertFalse(target.exists())

    def test_save_config_creates_missing_parent(self) -> None:
        target = self.root / "nested" / "config.json"
        with patch.object(cleanup, "CONFIG_PATH", target):
            written = cleanup.save_config({"stale_days": 42})
        self.assertEqual(written, target)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["stale_days"], 42)


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


class AppSupportWhitelistTests(unittest.TestCase):
    """App-support trees stay pruned; a config whitelist may carve out exact
    relative paths only. Live app data must remain unreachable, and manual
    entries must never reach an auto-delete path."""

    def _reload(self, cfg: dict, tag: str):
        """Reload the script against a temporary policy file (MDC_CONFIG)."""
        cfg_dir = tempfile.mkdtemp(prefix="mdc-appcfg-")
        cfg_file = Path(cfg_dir) / "config.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        previous = os.environ.get("MDC_CONFIG")
        os.environ["MDC_CONFIG"] = str(cfg_file)
        try:
            name = f"mdc_app_reload_{tag}"
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

    def _entry(self, module, root: Path, safe=(), manual=()):
        return module.AppSupportEntry("TestApp", root, tuple(safe), tuple(manual), "")

    def test_default_config_ships_pixpin_entry(self) -> None:
        entry = next((e for e in cleanup.APP_SUPPORT_ENTRIES if e.name == "PixPin"), None)
        self.assertIsNotNone(entry, "default config must whitelist PixPin")
        self.assertIn("Temp/RecordingRecovery", entry.safe)
        self.assertIn("History", entry.manual)
        self.assertTrue(entry.require_quit, "live recording recovery needs a quit guard")

    def test_exempt_covers_only_listed_relative_paths(self) -> None:
        module = self._reload({}, "exempt1")
        entry = next(e for e in module.APP_SUPPORT_ENTRIES if e.name == "PixPin")
        self.assertTrue(module.app_support_exempt(entry.root / "Temp" / "RecordingRecovery"))
        self.assertTrue(module.app_support_exempt(entry.root / "History" / "_ScreenshotRecord" / "a.his"))
        # Everything not named in the entry stays behind the prune wall.
        for unreachable in (entry.root, entry.root / "Data", entry.root / "Config",
                            entry.root / "Temp", entry.root / "OcrModel"):
            self.assertFalse(module.app_support_exempt(unreachable), str(unreachable))

    def test_pruned_respects_exemption_and_wall(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            module = self._reload({}, "prune1")
            app = (Path(temp) / "App").resolve()
            (app / "Temp" / "RecordingRecovery").mkdir(parents=True)
            (app / "Data").mkdir()
            entry = self._entry(module, app, safe=["Temp/RecordingRecovery"], manual=["History"])
            with patch.object(module, "PRUNE_PATHS", [app]), \
                    patch.object(module, "APP_SUPPORT_ENTRIES", (entry,)):
                self.assertFalse(module.pruned(app / "Temp" / "RecordingRecovery"))
                self.assertTrue(module.pruned(app / "Data"))
                self.assertTrue(module.pruned(app))

    def test_rejects_root_outside_pruned_paths(self) -> None:
        for bad_root in ("~/Documents/NotPruned", "/etc", "~/Library/Caches"):
            with self.assertRaises(ValueError):
                cleanup.validate_config({"app_support_whitelist": [
                    {"name": "X", "root": bad_root, "safe": ["cache"]}]})

    def test_rejects_escaping_relative_paths(self) -> None:
        for bad_rel in ("../../etc", "/etc/passwd", "~/secret", "a/../../b"):
            with self.assertRaises(ValueError):
                cleanup.validate_config({"app_support_whitelist": [
                    {"name": "X", "root": "~/Library/Application Support/X", "safe": [bad_rel]}]})

    def test_rejects_overlap_empty_and_unknown_keys(self) -> None:
        good_root = "~/Library/Application Support/X"
        with self.assertRaises(ValueError):  # same path safe and manual
            cleanup.validate_config({"app_support_whitelist": [
                {"name": "X", "root": good_root, "safe": ["cache"], "manual": ["cache"]}]})
        with self.assertRaises(ValueError):  # neither list populated
            cleanup.validate_config({"app_support_whitelist": [{"name": "X", "root": good_root}]})
        with self.assertRaises(ValueError):  # unknown entry key
            cleanup.validate_config({"app_support_whitelist": [
                {"name": "X", "root": good_root, "safe": ["c"], "surprise": 1}]})
        with self.assertRaises(ValueError):  # missing name
            cleanup.validate_config({"app_support_whitelist": [
                {"root": good_root, "safe": ["c"]}]})

    def test_manual_entry_is_never_auto_deleted(self) -> None:
        module = self._reload({}, "manual1")
        entry = next(e for e in module.APP_SUPPORT_ENTRIES if e.name == "PixPin")
        history = module.Candidate(entry.root / "History", 1 << 20,
                                   module.APP_SUPPORT_MANUAL_CATEGORY, "manual", "x")
        self.assertFalse(module.is_eligible(history, "clean-safe"))
        self.assertFalse(module.is_eligible(history, "clean-aggressive"))
        self.assertFalse(module.should_delete(history, "clean-aggressive"))

    def test_scan_labels_paths_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            module = self._reload({}, "scan1")
            app = (Path(temp) / "App").resolve()
            (app / "Temp" / "RecordingRecovery").mkdir(parents=True)
            (app / "Temp" / "RecordingRecovery" / "s.srndata").write_bytes(b"x" * 8)
            (app / "History").mkdir()
            if not hasattr(module, "TRASH_ROOT"):  # pragma: no cover - sanity
                self.fail("module failed to load")
            entry = self._entry(module, app, safe=["Temp/RecordingRecovery"], manual=["History"])
            with patch.object(module, "PRUNE_PATHS", [app]), \
                    patch.object(module, "APP_SUPPORT_ENTRIES", (entry,)), \
                    patch.object(module, "EXCLUDE_PATHS", []), \
                    patch.object(module, "PROTECTED_PROJECTS", []), \
                    patch.object(module, "EXCLUDE_GLOBS", ()), \
                    patch.object(module, "PROTECTED_CATEGORIES", set()):
                found = module.scan_app_support()
        by_name = {c.path.name: c for c in found.values()}
        self.assertEqual(by_name["RecordingRecovery"].category, "app-support-cache")
        self.assertEqual(by_name["RecordingRecovery"].risk, "safe")
        self.assertEqual(by_name["RecordingRecovery"].size, 8)
        self.assertEqual(by_name["History"].category, "app-support-manual")
        self.assertEqual(by_name["History"].risk, "manual")


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
