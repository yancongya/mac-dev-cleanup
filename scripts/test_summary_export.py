#!/usr/bin/env python3
"""Tests for exporting the saved state without invoking the cleanup engine."""

from __future__ import annotations

import io
import contextlib
import json
import ssl
import sys
import subprocess
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        probe = (
            "import importlib.util, sys; "
            "spec = importlib.util.spec_from_file_location('isolated_export_summary', sys.argv[1]); "
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "raise SystemExit('mac_dev_cleanup' in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe, str(Path(export_summary.__file__).resolve())],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

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
            ("byte total exceeds Agent Ops integer limit",
             lambda s: s.update(safe_bytes=export_summary.MAX_SUMMARY_INTEGER + 1), "safeBytes"),
            ("candidate size exceeds Agent Ops integer limit",
             lambda s: s["candidates"][0].update(size=export_summary.MAX_SUMMARY_INTEGER + 1), "candidate size"),
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

    def test_export_rejects_safe_and_aggressive_total_overflow(self) -> None:
        state = valid_state()
        limit = export_summary.MAX_SUMMARY_INTEGER
        state["candidates"][0]["size"] = limit
        state["candidates"][1]["size"] = 1
        state.update(safe_bytes=limit, aggressive_bytes=1, deletable_bytes=limit + 1,
                     selected_bytes=limit)
        with self.assertRaisesRegex(export_summary.SummaryError, "Agent Ops summary limit"):
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

    def test_upload_posts_only_allowlist_with_dedicated_token_and_verified_tls(self) -> None:
        state = valid_state()
        captured = {}

        class Response:
            status = 202
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def read(self, limit):
                self.limit = limit
                return json.dumps({
                    "schema": "agent-ops-mac/v1", "accepted": True, "state": "stored"
                }).encode("utf-8")

        def fake_open(request, *, context, timeout):
            captured["url"] = request.full_url
            captured["headers"] = request.header_items()
            captured["payload"] = json.loads(request.data)
            captured["context"] = context
            captured["timeout"] = timeout
            return Response()

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.json"
            source.write_text(json.dumps(state), encoding="utf-8")
            export_summary.upload_summary(
                source, "https://collector.example/v1/mac/summary", "dedicated-ingest-secret", opener=fake_open
            )

        self.assertEqual(captured["url"], "https://collector.example/v1/mac/summary")
        headers = dict(captured["headers"])
        self.assertEqual(headers["X-mac-ingest-token"], "dedicated-ingest-secret")
        self.assertTrue(captured["context"].check_hostname)
        self.assertEqual(captured["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(captured["timeout"], 15)
        self.assertNotIn("candidates", captured["payload"])
        self.assertNotIn("config", captured["payload"])

    def test_default_transport_installs_tls_context_blocks_redirects_and_uses_timeout(self) -> None:
        captured = {}

        class Response:
            status = 202
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def read(self, _limit):
                return b'{"schema":"agent-ops-mac/v1","accepted":true,"state":"stored"}'

        class Transport:
            def open(self, request, *, timeout):
                captured["url"] = request.full_url
                captured["timeout"] = timeout
                return Response()

        def build_opener(*handlers):
            captured["handlers"] = handlers
            return Transport()

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.json"
            source.write_text(json.dumps(valid_state()), encoding="utf-8")
            with patch.object(export_summary.urllib.request, "build_opener", side_effect=build_opener):
                export_summary.upload_summary(
                    source, "https://collector.example/v1/mac/summary", "dedicated-token"
                )

        self.assertEqual(captured["timeout"], 15)
        https_handler, redirect_handler = captured["handlers"]
        self.assertIsInstance(https_handler, export_summary.urllib.request.HTTPSHandler)
        self.assertIsInstance(redirect_handler, export_summary._NoRedirect)
        self.assertTrue(https_handler._context.check_hostname)
        self.assertEqual(https_handler._context.verify_mode, ssl.CERT_REQUIRED)

    def test_stdin_token_read_is_byte_bounded(self) -> None:
        class TrackingStream(io.BytesIO):
            requested_size = None
            def read(self, size=-1):
                self.requested_size = size
                return super().read(size)

        exact_limit = TrackingStream(b"x" * export_summary.MAX_TOKEN_BYTES + b"\r\n")
        self.assertEqual(len(export_summary.read_ingest_token(exact_limit)), export_summary.MAX_TOKEN_BYTES)
        self.assertEqual(exact_limit.requested_size, export_summary.MAX_TOKEN_BYTES + 2)

        for raw in (
            b"x" * (export_summary.MAX_TOKEN_BYTES + 1) + b"\n",
            b"x" * (export_summary.MAX_TOKEN_BYTES + 1),
        ):
            with self.subTest(raw_length=len(raw)):
                stream = TrackingStream(raw)
                with self.assertRaisesRegex(export_summary.SummaryError, "size limit"):
                    export_summary.read_ingest_token(stream)
                self.assertEqual(stream.requested_size, export_summary.MAX_TOKEN_BYTES + 2)

    def test_upload_rejects_non_https_or_wrong_route_before_network(self) -> None:
        for endpoint in (
            "http://collector.example/v1/mac/summary",
            "https://collector.example/other",
            "https://user:pass@collector.example/v1/mac/summary",
            "https://collector.example/v1/mac/summary?debug=1",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(export_summary.SummaryError):
                    export_summary.validate_endpoint(endpoint)

    def test_upload_rejects_header_unsafe_token_and_redirects(self) -> None:
        for token in ("", "contains space", "bad\nvalue", "é", "x" * 8193):
            with self.subTest(token=token[:20]):
                with self.assertRaises(export_summary.SummaryError):
                    export_summary.upload_summary(
                        Path("unused"), "https://collector.example/v1/mac/summary", token,
                        opener=lambda *_args, **_kwargs: self.fail("network must not be called"),
                    )
        self.assertIsNone(export_summary._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example/"))

    def test_upload_command_reads_token_only_from_stdin_and_requires_explicit_endpoint(self) -> None:
        with patch.object(export_summary.sys, "stdin", io.StringIO("secret-value\n")):
            # Missing endpoint is rejected by argument validation before any state access.
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit):
                    export_summary.main(["--upload", "--token-stdin"])
            self.assertNotIn("secret-value", stderr.getvalue())

    def test_upload_cli_accepts_pipe_stdin_without_printing_token(self) -> None:
        token = "pipe-only-secret"
        stdin = SimpleNamespace(buffer=io.BytesIO(token.encode("ascii") + b"\n"))
        with patch.object(export_summary.sys, "stdin", stdin), \
                patch.object(export_summary, "upload_summary") as upload, \
                contextlib.redirect_stdout(io.StringIO()) as stdout, \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            result = export_summary.main([
                "--upload", "--token-stdin", "--endpoint", "https://collector.example/v1/mac/summary"
            ])
        self.assertEqual(result, 0)
        self.assertEqual(upload.call_args.args[2], token)
        self.assertNotIn(token, stdout.getvalue())
        self.assertNotIn(token, stderr.getvalue())

    def test_upload_failure_does_not_include_token_in_error(self) -> None:
        token = "never-print-this-token"
        def failing_open(*_args, **_kwargs):
            raise urllib.error.URLError("connection failed")

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "state.json"
            source.write_text(json.dumps(valid_state()), encoding="utf-8")
            with self.assertRaises(export_summary.SummaryError) as error:
                export_summary.upload_summary(
                    source, "https://collector.example/v1/mac/summary", token, opener=failing_open
                )
        self.assertEqual(str(error.exception), "HTTPS upload failed")
        self.assertNotIn(token, str(error.exception))

    def test_upload_requires_exact_agent_ops_acceptance_response(self) -> None:
        token = "never-print-this-token"
        responses = [
            (202, b'{"schema":"other/v1","accepted":true,"state":"stored"}'),
            (202, b'{"schema":"agent-ops-mac/v1","accepted":false,"state":"stored"}'),
            (202, b'{"schema":"agent-ops-mac/v1","accepted":true,"state":"rejected"}'),
            (202, b'{"schema":"agent-ops-mac/v1","accepted":1,"state":"stored"}'),
            (202, b'{"private":"response detail"}'),
            (202, b"not-json"),
            (202, b"x" * (export_summary.MAX_RESPONSE_BYTES + 1)),
            (400, b'{"private":"response detail"}'),
        ]

        for status, body in responses:
            with self.subTest(status=status, body_prefix=body[:24]):
                class Response:
                    def __enter__(self):
                        return self
                    def __exit__(self, *_args):
                        return False
                    def read(self, _limit):
                        return body
                response = Response()
                response.status = status

                with tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / "state.json"
                    source.write_text(json.dumps(valid_state()), encoding="utf-8")
                    with self.assertRaises(export_summary.SummaryError) as error:
                        export_summary.upload_summary(
                            source,
                            "https://collector.example/v1/mac/summary",
                            token,
                            opener=lambda *_args, **_kwargs: response,
                        )
                self.assertEqual(str(error.exception), "ingest response was not accepted")
                self.assertNotIn(token, str(error.exception))
                self.assertNotIn("private", str(error.exception))


if __name__ == "__main__":
    unittest.main()
