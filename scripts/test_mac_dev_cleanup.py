#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt  # noqa: F401  (kept for parity with production imports)
import importlib.util
import json
import os
import sys
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import mac_dev_cleanup as cleanup
import web_server


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


class DashboardPortTests(unittest.TestCase):
    """The dashboard port is policy, not a hardcoded constant.

    8765 is often already taken on a developer Mac, so the default must live in
    config.json (overridable by --port / MDC_PORT) and an unusable value must be
    rejected rather than producing a server that cannot bind.
    """

    def test_default_port_avoids_the_crowded_8765(self) -> None:
        self.assertEqual(cleanup.DEFAULT_CONFIG["dashboard_port"], 8766)
        self.assertNotEqual(cleanup.DEFAULT_CONFIG["dashboard_port"], 8765)

    def test_port_is_part_of_the_validated_config(self) -> None:
        cfg = cleanup.validate_config({"dashboard_port": 9000})
        self.assertEqual(cfg["dashboard_port"], 9000)
        # An untouched policy still exposes the key, so the server never has to
        # invent its own fallback.
        self.assertIn("dashboard_port", cleanup.validate_config({}))

    def test_unusable_ports_are_rejected(self) -> None:
        for bad in (80, 0, -1, 70000, "8766", 8766.5, None, True):
            with self.subTest(port=bad):
                with self.assertRaises(ValueError):
                    cleanup.validate_config({"dashboard_port": bad})


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

    def test_scan_wechat_skips_while_wechat_running(self) -> None:
        # Field-tested 2026-09-24: with WeChat running, opendir() into the
        # sandboxed container blocks indefinitely — the nightly clean-safe hung
        # 7.5h in collect(). The scan phase must not walk the container at all.
        with patch.object(cleanup, "wechat_running", return_value=True), \
             patch.object(cleanup, "WECHAT_CACHE_DIRS", {}), \
             patch.object(cleanup, "WECHAT_FILES", Path("/nonexistent-wechat-files")):
            self.assertEqual(cleanup.scan_wechat(1), {})

    def test_scan_app_support_skips_running_require_quit_entry(self) -> None:
        entry = cleanup.AppSupportEntry(
            name="TestApp", root=Path("/nonexistent-testapp"), safe=["Cache"], manual=[],
            require_quit="TestApp.app/Contents/MacOS/TestApp")
        with patch.object(cleanup, "APP_SUPPORT_ENTRIES", [entry]), \
             patch.object(cleanup, "process_running", return_value=True):
            self.assertEqual(cleanup.scan_app_support(), {})

    def test_cutoff_spans_year_boundary(self) -> None:
        def fake_today(year: int, month: int):
            day = MagicMock()
            day.year = year
            day.month = month
            return day

        with patch.object(cleanup, "dt") as mock_dt:
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


class AppUninstallTests(unittest.TestCase):
    """App uninstall: name validation, traversal guards, related-file discovery."""

    def test_app_name_regex_allows_localized_names_and_bans_separators(self) -> None:
        self.assertTrue(cleanup.APP_NAME_RE.match("Foo.app"))
        self.assertTrue(cleanup.APP_NAME_RE.match("剪映专业版.app"))
        self.assertFalse(cleanup.APP_NAME_RE.match("foo/bar.app"))
        self.assertFalse(cleanup.APP_NAME_RE.match("..app"))
        self.assertFalse(cleanup.APP_NAME_RE.match(".app"))

    def test_find_app_bundle_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Foo.app").mkdir()
            with patch.object(cleanup, "APP_DIRS", (root,)):
                self.assertIsNotNone(cleanup.find_app_bundle("Foo.app"))
                self.assertIsNone(cleanup.find_app_bundle("../Foo.app"))
                self.assertIsNone(cleanup.find_app_bundle("sub/Foo.app"))
                self.assertIsNone(cleanup.find_app_bundle("Missing.app"))

    def test_app_related_paths_covers_conventional_locations(self) -> None:
        rel = cleanup.app_related_paths("Foo.app", "com.foo.bar")
        joined = [str(p) for p in rel]
        self.assertIn(str(cleanup.HOME / "Library/Preferences/com.foo.bar.plist"), joined)
        self.assertIn(str(cleanup.HOME / "Library/Containers/com.foo.bar"), joined)
        self.assertIn(str(cleanup.HOME / "Library/Group Containers/group.com.foo.bar"), joined)
        self.assertIn(str(cleanup.HOME / "Library/Application Support/Foo"), joined)
        self.assertIn(str(cleanup.HOME / "Library/Caches/Foo"), joined)

    def test_move_path_to_quarantine_refuses_paths_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "victim.txt"
            outside.write_text("x")
            ok, message, entry = cleanup.move_path_to_quarantine(outside, "op", "uninstall test")
            self.assertFalse(ok)
            self.assertIn("refused", message)
            self.assertIsNone(entry)
            self.assertTrue(outside.exists())  # untouched


class P0SecurityTests(unittest.TestCase):
    """Immune zone + TOCTOU guard added with the P0 category expansion."""

    def test_immune_credential_paths_are_always_excluded(self) -> None:
        # Code-level protection, independent of user config: scanners must
        # never propose anything under credential stores or mail data.
        for p in (
            cleanup.HOME / ".ssh" / "id_rsa",
            cleanup.HOME / ".aws" / "credentials",
            cleanup.HOME / ".gnupg" / "pubring.kbx",
            cleanup.HOME / ".kube" / "config",
            cleanup.HOME / "Library" / "Keychains" / "login.keychain-db",
            cleanup.HOME / "Library" / "Cookies",
        ):
            self.assertTrue(cleanup.excluded(p), p)

    def test_move_to_quarantine_refuses_swapped_path(self) -> None:
        real_fp = cleanup.fingerprint
        calls = {"n": 0}

        def flaky_fp(p):
            calls["n"] += 1
            result = real_fp(p)
            if calls["n"] == 2:  # second stat = right before shutil.move
                return {**result, "inode": result["inode"] + 1}
            return result

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(cleanup, "TRASH_ROOT", Path(tmp) / "trash"):
            victim = Path(tmp) / "victim.txt"
            victim.write_text("x")
            with patch.object(cleanup, "fingerprint", flaky_fp):
                ok, message, entry = cleanup.move_to_quarantine(
                    cleanup.Candidate(victim, 1, "dev-cache", "safe", "test"), "op-test")
            self.assertFalse(ok)
            self.assertIn("TOCTOU", message)
            self.assertIsNone(entry)
            self.assertTrue(victim.exists())  # untouched

    def test_move_path_to_quarantine_refuses_swapped_path(self) -> None:
        real_fp = cleanup.fingerprint
        calls = {"n": 0}

        def flaky_fp(p):
            calls["n"] += 1
            result = real_fp(p)
            if calls["n"] == 2:
                return {**result, "inode": result["inode"] + 1}
            return result

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(cleanup, "TRASH_ROOT", Path(tmp) / "trash"):
            outside_roots = Path(tmp) / "app.app"  # refused by root check first
            outside_roots.mkdir()
            ok, message, _ = cleanup.move_path_to_quarantine(outside_roots, "op", "t")
            self.assertFalse(ok)  # root check fires before fingerprinting


class P0OrphanScanTests(unittest.TestCase):
    def _make_root(self, entries: dict[str, int]) -> Path:
        root = Path(tempfile.mkdtemp(prefix="mdc-orphans-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for name, kb in entries.items():
            d = root / name
            d.mkdir()
            (d / "blob.bin").write_bytes(b"\0" * (kb * 1024))
        return root

    def test_orphans_flag_unclaimed_entries_and_skip_known_owners(self) -> None:
        root = self._make_root({
            "RemovedApp": 2048,          # no installed app claims it -> flagged
            "com.apple.ubd": 2048,       # com.apple -> skipped
            "GeoServices": 2048,         # Apple service without the prefix -> skipped
            "Bun": 2048,                 # dev-tool cache -> skipped
            "0123456789abcdef0123456789abcdef": 2048,  # UUID -> skipped
            "Tiny": 1,                   # below 1MB -> skipped
        })
        with patch.object(cleanup, "ORPHAN_SCAN_ROOTS", (root,)), \
             patch.object(cleanup, "_installed_identifiers", return_value={"googlechrome"}):
            result = cleanup.scan_orphans()
        self.assertEqual([c.path.name for c in result.values()], ["RemovedApp"])
        cand = next(iter(result.values()))
        self.assertEqual(cand.category, "orphan")
        self.assertEqual(cand.risk, "manual")  # never auto-cleaned

    def test_orphans_match_installed_identifiers_both_directions(self) -> None:
        root = self._make_root({"WeChatHelperCache": 2048, "MysteryTool": 2048})
        with patch.object(cleanup, "ORPHAN_SCAN_ROOTS", (root,)), \
             patch.object(cleanup, "_installed_identifiers", return_value={"wechat"}):
            result = cleanup.scan_orphans()
        # identifier contained in entry ("wechat" in "wechathelpercache") -> skip
        self.assertEqual([c.path.name for c in result.values()], ["MysteryTool"])

    def test_orphan_identifiers_read_apps_json_when_available(self) -> None:
        payload = {"apps": [{"name": "Foo.app", "bundle_id": "com.foo.bar"}, "bad"]}
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "apps.json"
            state.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(cleanup, "APPS_STATE_PATH", state):
                idents = cleanup._installed_identifiers()
        self.assertIn("foo", idents)
        self.assertIn("comfoobar", idents)


class P0CategoryScanTests(unittest.TestCase):
    def test_scan_xcode_skips_while_xcode_running(self) -> None:
        with patch.object(cleanup, "process_running", return_value=True):
            self.assertEqual(cleanup.scan_xcode(), {})

    def test_scan_xcode_risk_tiers(self) -> None:
        with patch.object(cleanup, "process_running", return_value=False):
            result = cleanup.scan_xcode()
        for c in result.values():  # empty on hosts without Xcode dirs — fine
            self.assertEqual(c.category, "xcode")
            self.assertIn(c.risk, {"safe", "aggressive", "manual"})

    def test_scan_dev_global_guards_live_toolchains(self) -> None:
        with patch.object(cleanup, "process_running_exact", return_value=True):
            result = cleanup.scan_dev_global()
        for c in result.values():
            text = c.path.as_posix().lower()
            self.assertNotIn("gradle", text)
            self.assertFalse(any(part == "go" for part in c.path.parts))

    def test_scan_ai_caches_keeps_newest_claude_version(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="mdc-claude-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        for v in ("1.0.9", "1.0.10", "1.1.0"):
            (base / v).mkdir()
        with patch.object(cleanup, "CLAUDE_VERSIONS_DIR", base), \
             patch.object(cleanup, "AI_SAFE_PATHS", []), \
             patch.object(cleanup, "AI_AGGRESSIVE_PATHS", []), \
             patch.object(cleanup, "AI_MANUAL_PATHS", []):
            result = cleanup.scan_ai_caches()
        flagged = sorted(c.path.name for c in result.values())
        self.assertEqual(flagged, ["1.0.10", "1.0.9"])  # lexicographic; 1.1.0 (newest) kept
        self.assertTrue(all(c.risk == "aggressive" for c in result.values()))


class P1LargeFileTests(unittest.TestCase):
    def _make_file(self, root: Path, name: str, size: int, age_days: float = 0) -> Path:
        path = root / name
        path.write_bytes(b"\0" * size)
        if age_days:
            stamp = time.time() - age_days * 86400
            os.utime(path, (stamp, stamp))
        return path

    def _scan(self, root: Path, **overrides: object) -> dict:
        patches = {"PROJECT_ROOTS": [root], "LARGE_FILE_MIN_BYTES": 1024,
                   "LARGE_FILE_OLD_BYTES": 512, "LARGE_FILE_OLD_DAYS": 365}
        patches.update(overrides)
        with patch.multiple(cleanup, **patches):  # type: ignore[arg-type]
            return cleanup.scan_large_files()

    def test_large_files_flag_big_and_old_only(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="mdc-large-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self._make_file(root, "big.bin", 2048)                       # >1KB, new -> large-file
        self._make_file(root, "old.bin", 600, age_days=400)          # >512B, old -> old-large-file
        self._make_file(root, "small-new.bin", 600)                  # >512B but fresh -> skip
        self._make_file(root, "tiny.bin", 100)                       # below both bars -> skip
        link = root / "symlink.bin"
        os.symlink(root / "big.bin", link)                           # symlinks never flagged
        (root / ".DS_Store").write_bytes(b"\0" * 4096)               # noise file -> skip
        result = self._scan(root)
        by_reason = {}
        for c in result.values():
            by_reason.setdefault(c.reason, []).append(c.path.name)
        self.assertEqual(sorted(by_reason.get("large-file", [])), ["big.bin"])
        self.assertEqual(by_reason.get("old-large-file"), ["old.bin"])
        self.assertTrue(all(c.risk == "manual" for c in result.values()))
        self.assertTrue(all(c.category == "large-files" for c in result.values()))

    def test_large_files_skip_paths_covered_by_earlier_passes(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="mdc-large-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        covered_dir = root / "DerivedData"
        covered_dir.mkdir()
        self._make_file(covered_dir, "inside.bin", 2048)
        self._make_file(root, "outside.bin", 2048)
        covered = {covered_dir.resolve(): cleanup.Candidate(
            covered_dir.resolve(), 1, "xcode", "safe", "test")}
        patches = {"PROJECT_ROOTS": [root], "LARGE_FILE_MIN_BYTES": 1024,
                   "LARGE_FILE_OLD_BYTES": 512, "LARGE_FILE_OLD_DAYS": 365}
        with patch.multiple(cleanup, **patches):  # type: ignore[arg-type]
            result = cleanup.scan_large_files(covered=covered)
        self.assertEqual([c.path.name for c in result.values()], ["outside.bin"])

    def test_large_files_respect_item_cap(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="mdc-large-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for i in range(5):
            self._make_file(root, f"f{i}.bin", 2048)
        result = self._scan(root, LARGE_FILE_MAX_ITEMS=3)
        self.assertEqual(len(result), 3)


class WebTrashStatusTests(unittest.TestCase):
    """collect_trash_status: quarantine + system blocks, TCC degradation."""

    def _make_trash(self, entries: dict[str, int]) -> tuple[Path, Path]:
        base = Path(tempfile.mkdtemp(prefix="mdc-webtrash-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        trash = base / "Trash"
        quarantine = trash / "mac-dev-cleanup"
        quarantine.mkdir(parents=True)
        (quarantine / "op1").mkdir()
        (quarantine / "op1" / "f.bin").write_bytes(b"\0" * 4096)
        for name, size in entries.items():
            p = trash / name
            p.mkdir()
            (p / "data.bin").write_bytes(b"\0" * size)
        return trash, quarantine

    def test_system_block_excludes_quarantine_and_sums_sizes(self) -> None:
        trash, quarantine = self._make_trash({"BigDir": 8192, "SmallDir": 1024})
        with patch.object(web_server, "TRASH_DIR", trash), \
             patch.object(web_server, "QUARANTINE_DIR", quarantine):
            status = web_server.collect_trash_status()
        self.assertTrue(status["system"]["available"])
        self.assertEqual(status["system"]["count"], 2)
        self.assertEqual(status["system"]["total_bytes"], 9216)
        self.assertEqual(status["system"]["items"][0]["name"], "BigDir")  # size desc
        self.assertEqual(status["quarantine"]["total_bytes"], 4096)
        self.assertNotIn("mac-dev-cleanup", [i["name"] for i in status["system"]["items"]])
        self.assertEqual(status["grand_total_bytes"], 9216 + 4096)
        # legacy top-level keys survive
        self.assertEqual(status["total_bytes"], 4096)

    def test_permission_denied_degrades_to_unavailable(self) -> None:
        trash, _quarantine = self._make_trash({"Dir": 1024})
        # Standalone quarantine outside ~/.Trash: proves the blocks degrade
        # independently (in production it lives inside the Trash and dies with it).
        standalone_q = trash.parent / "quarantine"
        (standalone_q / "op1").mkdir(parents=True)
        (standalone_q / "op1" / "f.bin").write_bytes(b"\0" * 2048)
        trash.chmod(0o000)  # simulate TCC denial on ~/.Trash
        self.addCleanup(trash.chmod, 0o755)
        with patch.object(web_server, "TRASH_DIR", trash), \
             patch.object(web_server, "QUARANTINE_DIR", standalone_q):
            status = web_server.collect_trash_status()
        self.assertFalse(status["system"]["available"])
        self.assertEqual(status["system"]["items"], [])
        self.assertTrue(status["quarantine"]["available"])  # separate block unaffected
        self.assertEqual(status["quarantine"]["total_bytes"], 2048)

    def test_empty_system_requires_exact_confirm_string(self) -> None:
        # The gate lives in the handler; verified via regex on source so the
        # literal confirm contract cannot silently drift.
        src = (Path(__file__).parent / "web_server.py").read_text(encoding="utf-8")
        self.assertIn('payload.get("confirm") != "EMPTY TRASH"', src)


class P1Batch2Tests(unittest.TestCase):
    """Browser profile caches / installer sweep / iOS backup report."""

    # -- browser caches -------------------------------------------------------
    def test_browser_caches_flag_profile_dirs_skip_running_browser(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="mdc-browsers-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        chrome = base / "Chrome"
        (chrome / "Default" / "Code Cache").mkdir(parents=True)
        (chrome / "Default" / "Service Worker" / "CacheStorage").mkdir(parents=True)
        (chrome / "OptGuideOnDeviceModel").mkdir()
        (chrome / "ShaderCache").mkdir()
        edge = base / "Edge"
        (edge / "Default" / "GPUCache").mkdir(parents=True)
        ff = base / "FirefoxProfiles"
        (ff / "abc123.default" / "cache2").mkdir(parents=True)

        def running(name: str) -> bool:
            return name == "Google Chrome"  # Chrome is up: skip it entirely

        browsers = (
            ("Google Chrome", chrome, ("Google Chrome",)),
            ("Microsoft Edge", edge, ("Microsoft Edge",)),
        )
        with patch.object(cleanup, "BROWSERS", browsers), \
             patch.object(cleanup, "FIREFOX_PROFILES_ROOT", ff), \
             patch.object(cleanup, "process_running_exact", running):
            result = cleanup.scan_browser_caches()
        texts = [str(c.path) for c in result.values()]
        self.assertFalse(any("Chrome" in t for t in texts))       # running -> skipped
        self.assertFalse(any("Service Worker" in t for t in texts))  # site data: never
        self.assertFalse(any("OptGuideOnDeviceModel" in t for t in texts))
        self.assertIn("safe", {c.risk for c in result.values()})
        edge_code = next(c for c in result.values() if c.path.name == "GPUCache")
        self.assertEqual((edge_code.risk, edge_code.reason), ("safe", "browser-profile-cache"))
        self.assertTrue(any(c.path.name == "cache2" for c in result.values()))  # firefox
        # model store under a non-running browser is aggressive
        with patch.object(cleanup, "BROWSERS",
                          (("Google Chrome", chrome, ("Google Chrome",)),)), \
             patch.object(cleanup, "FIREFOX_PROFILES_ROOT", ff), \
             patch.object(cleanup, "process_running_exact", lambda n: False):
            chrome_result = cleanup.scan_browser_caches()
        model = next(c for c in chrome_result.values()
                     if c.path.name == "OptGuideOnDeviceModel")
        self.assertEqual(model.risk, "aggressive")

    # -- installer sweep ------------------------------------------------------
    def _make_zip(self, path: Path, names: list[str]) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            for n in names:
                zf.writestr(n, b"x")

    def test_installers_flag_packages_and_payload_zips(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="mdc-inst-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "App.dmg").write_bytes(b"\0" * 2048)
        (root / "Tool.pkg").write_bytes(b"\0" * 512)
        (root / "readme.txt").write_bytes(b"hi")
        self._make_zip(root / "plain.zip", ["docs/readme.txt"])
        self._make_zip(root / "bundle.zip", ["Foo.app/Contents/MacOS/Foo"])
        (root / "nested").mkdir()
        (root / "nested" / "Inner.xip").write_bytes(b"\0" * 128)
        (root / "deep").mkdir()
        (root / "deep" / "too-far.dmg").write_bytes(b"\0" * 128)      # depth 2: allowed
        (root / "deep" / "deeper").mkdir()
        (root / "deep" / "deeper" / "way-down.dmg").write_bytes(b"\0" * 128)  # depth 3: excluded
        os.symlink(root / "App.dmg", root / "link.dmg")
        with patch.object(cleanup, "INSTALLER_SCAN_ROOT", root):
            result = cleanup.scan_installers()
        by_name = {c.path.name: c for c in result.values()}
        self.assertEqual(by_name["App.dmg"].reason, "installer-package")
        self.assertEqual(by_name["App.dmg"].risk, "manual")
        self.assertEqual(by_name["bundle.zip"].reason, "installer-zip")
        self.assertEqual(by_name["Inner.xip"].reason, "installer-package")
        self.assertIn("too-far.dmg", by_name)  # depth 2 = allowed by find -maxdepth 2
        for absent in ("way-down.dmg", "plain.zip", "readme.txt", "link.dmg"):
            self.assertNotIn(absent, by_name)

    # -- iOS backup report ----------------------------------------------------
    def test_ios_backups_reported_manual(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="mdc-ios-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        backup_root = base / "Backup"
        (backup_root / "udid-aaaa").mkdir(parents=True)
        (backup_root / "udid-bbbb").mkdir()
        (backup_root / "udid-aaaa" / "Manifest.db").write_bytes(b"\0" * 256)
        with patch.object(cleanup, "IOS_BACKUP_ROOT", backup_root):
            result = cleanup.scan_ios_backups()
        self.assertEqual(len(result), 2)
        self.assertTrue(all(c.risk == "manual" and c.category == "ios-backup"
                            for c in result.values()))

    def test_ios_backups_absent_when_no_directory(self) -> None:
        with patch.object(cleanup, "IOS_BACKUP_ROOT",
                          Path(tempfile.gettempdir()) / "mdc-no-such-backup"):
            self.assertEqual(cleanup.scan_ios_backups(), {})

    def test_ios_backups_tcc_denial_degrades_to_empty(self) -> None:
        # MobileSync is TCC-protected; EACCES on iterdir must not abort a scan.
        locked = Path(tempfile.mkdtemp(prefix="mdc-ios-locked-"))
        self.addCleanup(shutil.rmtree, locked, ignore_errors=True)
        locked.chmod(0o000)
        with patch.object(cleanup, "IOS_BACKUP_ROOT", locked):
            self.assertEqual(cleanup.scan_ios_backups(), {})


if __name__ == "__main__":
    unittest.main()
