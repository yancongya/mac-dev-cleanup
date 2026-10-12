#!/usr/bin/env python3
"""JSON CLI for a read-only inventory of commands visible in PATH."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import cli_inventory


def run(argv: Sequence[str] | None = None, *, inventory: Any | None = None) -> int:
    parser = argparse.ArgumentParser(description="List executable commands resolved through PATH as JSON.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list available CLI tools without executing them")
    parser.parse_args(argv)
    try:
        result = (inventory or cli_inventory).list_cli_tools()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except OSError:
        print(json.dumps({"ok": False, "error": "unable to scan PATH directories"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
