#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import unittest
from unittest.mock import Mock

import login_items


class LoginItemsTests(unittest.TestCase):
    def test_lists_traditional_items_without_mutating_macos_state(self) -> None:
        output = login_items.FIELD_SEPARATOR.join(
            ("Example App", "/Applications/Example.app", "应用程序", "false")
        ) + login_items.ROW_SEPARATOR + login_items.FIELD_SEPARATOR.join(
            ("Hidden task", "", "UNKNOWN", "true")
        )
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, output + "\n", ""))

        result = login_items.list_login_items(runner=runner)

        self.assertTrue(result["ok"])
        self.assertTrue(result["readOnly"])
        self.assertEqual(result["scope"], "Open at Login")
        self.assertEqual([item["name"] for item in result["items"]], ["Example App", "Hidden task"])
        self.assertEqual(result["items"][0]["kind"], "application")
        self.assertEqual(result["items"][0]["path"], "/Applications/Example.app")
        self.assertIsNone(result["items"][1]["path"])
        self.assertTrue(result["items"][1]["hidden"])
        self.assertTrue(all(item["enabled"] and item["control"] == "system-settings" for item in result["items"]))
        args, kwargs = runner.call_args
        self.assertEqual(args[0][:2], ["/usr/bin/osascript", "-e"])
        self.assertNotIn("shell", kwargs)
        self.assertIn("toggle another app", result["limitations"][1])

    def test_empty_list_is_valid(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "\n", ""))
        self.assertEqual(login_items.list_login_items(runner=runner)["items"], [])

    def test_automation_denial_is_redacted_and_actionable(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 1, "", "private path and app name"))
        with self.assertRaises(login_items.LoginItemsError) as raised:
            login_items.list_login_items(runner=runner)
        self.assertNotIn("private path", str(raised.exception))
        self.assertIn("System Events", str(raised.exception))

    def test_malformed_delimited_record_fails_closed(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "broken\n", ""))
        with self.assertRaises(login_items.LoginItemsError):
            login_items.list_login_items(runner=runner)

    def test_timeout_has_settings_fallback(self) -> None:
        runner = Mock(side_effect=subprocess.TimeoutExpired("osascript", 10))
        with self.assertRaisesRegex(login_items.LoginItemsError, "Login Items settings"):
            login_items.list_login_items(runner=runner)


if __name__ == "__main__":
    unittest.main()
