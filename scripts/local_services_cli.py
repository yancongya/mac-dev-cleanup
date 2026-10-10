#!/usr/bin/env python3
"""JSON CLI for explicitly managed per-user LaunchAgents."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import local_services


_ACTION_BY_COMMAND = {
    "start": "start",
    "stop": "stop",
    "enable-autostart": "enable",
    "disable-autostart": "disable",
}


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        # Avoid echoing arbitrary invalid argument text into machine-readable output.
        payload = {"ok": False, "error": "invalid command arguments; see --help"}
        self.exit(2, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        description="List and manage explicitly registered user LaunchAgents as JSON."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list user LaunchAgents and their registration/runtime status")
    for name, help_text in (
        ("status", "show one user LaunchAgent status"),
        ("register", "explicitly register an existing user LaunchAgent for management"),
        ("start", "start an explicitly registered user LaunchAgent"),
        ("stop", "stop an explicitly registered user LaunchAgent"),
        ("enable-autostart", "enable login startup for an explicitly registered service"),
        ("disable-autostart", "disable login startup for an explicitly registered service"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("label", help="exact LaunchAgent Label, for example com.example.worker")
    return parser


def run(argv: Sequence[str] | None = None, *, manager: Any | None = None) -> int:
    args = _parser().parse_args(argv)
    services = manager if manager is not None else local_services.LocalServices()
    try:
        if args.command == "list":
            result = services.list_services()
        elif args.command == "status":
            result = services.service_status(args.label)
        elif args.command == "register":
            result = services.register_service(args.label)
        else:
            result = services.service_action(args.label, _ACTION_BY_COMMAND[args.command])
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (local_services.LocalServiceError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
