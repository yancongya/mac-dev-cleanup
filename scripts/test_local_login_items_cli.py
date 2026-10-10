#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import Mock

import login_items
import local_login_items_cli


class LoginItemsCliTests(unittest.TestCase):
    def test_list_outputs_structured_read_only_json(self) -> None:
        reader = Mock()
        reader.list_login_items.return_value = {"ok": True, "readOnly": True, "items": []}
        output = StringIO()
        with redirect_stdout(output):
            result = local_login_items_cli.run(["list"], reader=reader)
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue()), reader.list_login_items.return_value)
        reader.list_login_items.assert_called_once_with()

    def test_system_events_failure_is_json_and_nonzero(self) -> None:
        reader = Mock()
        reader.list_login_items.side_effect = login_items.LoginItemsError("System Events unavailable")
        error = StringIO()
        with redirect_stderr(error):
            result = local_login_items_cli.run(["list"], reader=reader)
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(error.getvalue()), {"ok": False, "error": "System Events unavailable"})

    def test_mutation_commands_are_not_available(self) -> None:
        for command in ("enable", "disable", "remove"):
            error = StringIO()
            with self.subTest(command=command), redirect_stderr(error):
                with self.assertRaises(SystemExit) as raised:
                    local_login_items_cli.run([command], reader=Mock())
            self.assertEqual(raised.exception.code, 2)
            self.assertNotIn("Traceback", error.getvalue())


if __name__ == "__main__":
    unittest.main()
