#!/usr/bin/env python3
"""Tests for the JSON entrypoint over the local LaunchAgent safety layer."""
from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import Mock, call

import local_services
import local_services_cli


class LocalServicesCliTests(unittest.TestCase):
    def invoke(self, argv: list[str], manager: Mock) -> tuple[int, dict[str, object], str]:
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = local_services_cli.run(argv, manager=manager)
        output = stdout.getvalue() or stderr.getvalue()
        return code, json.loads(output), output

    def test_list_and_status_use_the_service_safety_layer(self) -> None:
        manager = Mock()
        manager.list_services.return_value = {"ok": True, "services": []}
        manager.service_status.return_value = {"ok": True, "service": {"label": "com.example.worker"}}

        code, result, _ = self.invoke(["list"], manager)
        self.assertEqual(code, 0)
        self.assertEqual(result, {"ok": True, "services": []})
        manager.list_services.assert_called_once_with()

        code, result, _ = self.invoke(["status", "com.example.worker"], manager)
        self.assertEqual(code, 0)
        self.assertEqual(result["service"], {"label": "com.example.worker"})
        manager.service_status.assert_called_once_with("com.example.worker")

    def test_register_and_actions_are_forwarded_as_fixed_operations(self) -> None:
        manager = Mock()
        manager.register_service.return_value = {"ok": True, "service": {"registered": True}}
        manager.service_action.return_value = {"ok": True}

        code, _, _ = self.invoke(["register", "com.example.worker"], manager)
        self.assertEqual(code, 0)
        manager.register_service.assert_called_once_with("com.example.worker")

        expected = {
            "start": "start",
            "stop": "stop",
            "enable-autostart": "enable",
            "disable-autostart": "disable",
        }
        for command, action in expected.items():
            with self.subTest(command=command):
                code, result, _ = self.invoke([command, "com.example.worker"], manager)
                self.assertEqual(code, 0)
                self.assertTrue(result["ok"])
        self.assertEqual(manager.service_action.call_args_list, [
            call("com.example.worker", action) for action in expected.values()
        ])

    def test_service_policy_errors_are_json_and_nonzero(self) -> None:
        manager = Mock()
        manager.service_action.side_effect = local_services.LocalServiceError("service is not explicitly registered")
        code, result, output = self.invoke(["start", "com.example.worker"], manager)
        self.assertEqual(code, 2)
        self.assertEqual(result, {"ok": False, "error": "service is not explicitly registered"})
        self.assertNotIn("Traceback", output)

    def test_cli_does_not_offer_arbitrary_restart_or_plist_paths(self) -> None:
        for argv in (
            ["restart", "com.example.worker"],
            ["start", "com.example.worker", "/tmp/arbitrary.plist"],
        ):
            stderr = StringIO()
            with self.subTest(argv=argv), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    local_services_cli.run(argv, manager=Mock())
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(json.loads(stderr.getvalue())["ok"])
            self.assertNotIn("/tmp/arbitrary.plist", stderr.getvalue())


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    unittest.main()
