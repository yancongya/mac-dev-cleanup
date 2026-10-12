#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import cli_inventory
import local_cli_tools_cli


class CliInventoryTests(unittest.TestCase):
    def test_lists_executables_in_path_order_and_never_executes_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second, relative = root / "first", root / "second", root / "relative"
            for directory in (first, second, relative):
                directory.mkdir()
            for directory, name in ((first, "shared"), (second, "shared"), (second, "only-second")):
                path = directory / name
                path.write_text("this is not executed", encoding="utf-8")
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
            (first / "not-executable").write_text("ignored", encoding="utf-8")
            (first / "a-directory").mkdir()

            result = cli_inventory.list_cli_tools(os.pathsep.join((str(first), str(second), "relative", str(first / "missing"))))

        self.assertTrue(result["ok"])
        self.assertEqual(result["scannedDirectories"], 2)
        by_name = {item["name"]: item for item in result["tools"]}
        self.assertEqual(set(by_name), {"shared", "only-second"})
        self.assertEqual(by_name["shared"]["sourceDirectory"], str(first.resolve()))
        self.assertEqual(by_name["shared"]["path"], str((first / "shared").resolve()))
        self.assertEqual(by_name["only-second"]["sourceDirectory"], str(second.resolve()))

    def test_cli_outputs_json_and_forwards_only_the_read_operation(self) -> None:
        inventory = Mock()
        inventory.list_cli_tools.return_value = {"ok": True, "commandCount": 1, "tools": []}
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = local_cli_tools_cli.run(["list"], inventory=inventory)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"ok": True, "commandCount": 1, "tools": []})
        self.assertEqual(stderr.getvalue(), "")
        inventory.list_cli_tools.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
