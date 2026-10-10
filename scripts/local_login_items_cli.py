#!/usr/bin/env python3
"""Read macOS Open at Login entries as JSON; mutations remain in System Settings."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import login_items


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.exit(2, json.dumps({"ok": False, "error": "invalid command arguments; see --help"}) + "\n")


def run(argv: Sequence[str] | None = None, *, reader: Any = login_items) -> int:
    parser = _JsonArgumentParser(description="Read or refresh the current user's macOS Open at Login inventory as JSON.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="read traditional Open at Login items through System Events")
    commands.add_parser("refresh", help="read through System Events and save a private dashboard snapshot")
    args = parser.parse_args(argv)
    try:
        result = reader.list_login_items()
        if args.command == "refresh":
            result = reader.save_dashboard_snapshot(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except login_items.LoginItemsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
