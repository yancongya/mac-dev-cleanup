#!/usr/bin/env python3
"""Tests for exporting the saved state without invoking the cleanup engine."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import export_summary


def valid_state() -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "clean-safe",
        "apply": False,
        "candidate_count": 3,
        "candidates": [
            {"risk": "safe", "size": 100, "path": "/private/person/cache", "id": "private-id", "reason": "private reason"},
            {"risk": "aggressive", "size": 300, "path": "/private/person/deps", "id": "other-id", "reason": "another private reason"},
            {"risk": "manual", "size": 200, "path": "/private/person/photo", "id": "third-id", "reason": "review"},
        ],
        "safe_bytes": 100,
        "aggressive_bytes": 300,
        "manual_bytes": 200,
        "selected_bytes": 100,
        "deletable_bytes": 400,
        "config": {"private_setting": "must not export"},
    }


class SavedSummaryExportTests(unittest.TestCase):
    def test_exporter_does_not_import_cleanup_engine(self) -> None:
        self.assertNotIn("mac_dev_cleanup", sys.modules)

    def test_export_is_exact_allowlist_and_uses_existing_state(self) -> None:
        state = valid_state()
        state["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "state.json"
            output = root / "summary.json"
            source.write_text(json.dumps(state), encoding="utf-8")

            summary = export_summary.export_summary(source, output)
            saved = json.loads(output.read_text(encoding="utf-8"))
            encoded = output.read_text(encoding="utf-8")

        expected_keys = {
            "schema", "timestamp", "mode", "apply", "candidateCount", "riskCounts",
            "safeBytes", "aggressiveBytes", "manualBytes", "selectedBytes",
        }
        self.assertEqual(set(summary), expected_keys)
        self.assertEqual(saved, summary)
        self.assertEqual(summary["schema"], "mac-dev-cleanup.summary.v1")
        self.assertEqual(summary["riskCounts"], {"safe": 1, "aggressive": 1, "manual": 1})
        self.assertIs(summary["apply"], False)
        for private_value in ("/private/person", "private-id", "private reason", "private_setting"):
            self.assertNotIn(private_value, encoded)

    def test_export_does_not_accept_applied_state(self) -> None:
        state = valid_state()
        state["apply"] = True
        with self.assertRaisesRegex(export_summary.SummaryError, "non-applied"):
            export_summary.build_export_summary(state)

    def test_export_rejects_bad_timestamp_mode_counts_and_totals(self) -> None:
        cases = [
            ("naive timestamp", lambda s: s.update(timestamp="2026-10-10T10:00:00"), "timezone"),
            ("unknown mode", lambda s: s.update(mode="apps"), "mode"),
            ("bool count", lambda s: s.update(candidate_count=True), "candidate_count"),
            ("negative count", lambda s: s.update(candidate_count=-1), "candidate_count"),
            ("count mismatch", lambda s: s.update(candidate_count=2), "does not match"),
            ("unknown risk", lambda s: s["candidates"][0].update(risk="unknown"), "candidate risk"),
            ("bool bytes", lambda s: s.update(safe_bytes=True), "safeBytes"),
            ("negative bytes", lambda s: s.update(manual_bytes=-1), "manualBytes"),
            ("missing candidate size", lambda s: s["candidates"][0].pop("size"), "candidate size"),
            ("risk byte mismatch", lambda s: s.update(aggressive_bytes=301, deletable_bytes=401, selected_bytes=100), "risk byte totals"),
            ("deletable mismatch", lambda s: s.update(deletable_bytes=1), "risk totals"),
            ("selected mismatch", lambda s: s.update(selected_bytes=0), "mode and risk totals"),
        ]
        for label, mutate, error in cases:
            with self.subTest(label=label):
                state = valid_state()
                mutate(state)
                with self.assertRaisesRegex(export_summary.SummaryError, error):
                    export_summary.build_export_summary(state)

    def test_export_rejects_far_future_timestamp(self) -> None:
        state = valid_state()
        state["timestamp"] = "2030-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(export_summary.SummaryError, "future"):
            export_summary.build_export_summary(state, now=datetime(2026, 10, 10, tzinfo=timezone.utc))

    def test_export_refuses_symlink_output_and_missing_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "state.json"
            source.write_text(json.dumps(valid_state()), encoding="utf-8")
            real_output = root / "real.json"
            real_output.write_text("keep", encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(real_output)
            with self.assertRaisesRegex(export_summary.SummaryError, "symbolic link"):
                export_summary.export_summary(source, link)
            with self.assertRaisesRegex(export_summary.SummaryError, "unavailable"):
                export_summary.export_summary(root / "missing.json", root / "new.json")
            self.assertEqual(real_output.read_text(encoding="utf-8"), "keep")

    def test_export_refuses_output_that_is_saved_state_path_or_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "state.json"
            original = json.dumps(valid_state())
            source.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(export_summary.SummaryError, "must not replace"):
                export_summary.export_summary(source, source)
            self.assertEqual(source.read_text(encoding="utf-8"), original)

            hardlink = root / "state-hardlink.json"
            hardlink.hardlink_to(source)
            with self.assertRaisesRegex(export_summary.SummaryError, "must not replace"):
                export_summary.export_summary(source, hardlink)
            self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_export_file_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "state.json"
            output = root / "summary.json"
            state = valid_state()
            state["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            source.write_text(json.dumps(state), encoding="utf-8")
            export_summary.export_summary(source, output)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
