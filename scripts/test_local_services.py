#!/usr/bin/env python3
from __future__ import annotations

import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import local_services as services


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.loaded: set[str] = set()
        self.disabled: set[str] = set()

    def __call__(self, argv: list[str], **_kwargs: object) -> SimpleNamespace:
        self.calls.append(list(argv))
        if argv[:2] == ["launchctl", "print"]:
            target = argv[2]
            label = target.rsplit("/", 1)[-1]
            if label in self.loaded:
                return SimpleNamespace(returncode=0, stdout="state = running\n", stderr="")
            return SimpleNamespace(returncode=113, stdout="", stderr="not found")
        if argv[:2] == ["launchctl", "print-disabled"]:
            domain = argv[2]
            text = "\n".join(f'    "{label}" => {"disabled" if label in self.disabled else "enabled"}'
                              for label in {"com.example.worker", "com.example.stranger"})
            return SimpleNamespace(returncode=0, stdout=text, stderr="")
        if argv[:2] == ["launchctl", "bootstrap"]:
            self.loaded.add("com.example.worker")
        elif argv[:2] == ["launchctl", "kickstart"]:
            self.loaded.add("com.example.worker")
        elif argv[:2] == ["launchctl", "bootout"]:
            self.loaded.discard("com.example.worker")
        elif argv[:2] == ["launchctl", "disable"]:
            self.disabled.add("com.example.worker")
        elif argv[:2] == ["launchctl", "enable"]:
            self.disabled.discard("com.example.worker")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class LocalServicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="managed-launchagent-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "LaunchAgents"
        self.root.mkdir()
        self.registry = Path(self.temp.name) / "registry" / "managed-services.json"
        self.runner = FakeRunner()
        self.manager = services.LocalServices(runner=self.runner, uid=501,
                                              launch_agents=self.root, registry_path=self.registry)
        self.plist = self.root / "com.example.worker.plist"
        self.write_plist("com.example.worker")

    def write_plist(self, label: str, **extra: object) -> None:
        payload = {"Label": label, "ProgramArguments": ["/usr/bin/python3", "--token", "secret-value"],
                   "RunAtLoad": True, "KeepAlive": False, **extra}
        with self.plist.open("wb") as stream:
            plistlib.dump(payload, stream)

    def test_register_requires_exact_label_and_safe_regular_plist(self) -> None:
        with self.assertRaises(services.LocalServiceError):
            self.manager.register_service("../com.example.worker")
        with self.assertRaises(services.LocalServiceError):
            self.manager.register_service("com.apple.launchd")
        self.write_plist("com.example.other")
        with self.assertRaises(services.LocalServiceError):
            self.manager.register_service("com.example.worker")
        self.write_plist("com.example.worker")
        self.plist.unlink()
        outside = Path(self.temp.name) / "outside.plist"
        with outside.open("wb") as stream:
            plistlib.dump({"Label": "com.example.worker"}, stream)
        self.plist.symlink_to(outside)
        with self.assertRaises(services.LocalServiceError):
            self.manager.register_service("com.example.worker")
        self.assertEqual(self.runner.calls, [], "rejections must not invoke launchctl")

    def test_register_stores_only_label_and_verified_path(self) -> None:
        result = self.manager.register_service("com.example.worker")
        data = json.loads(self.registry.read_text(encoding="utf-8"))
        self.assertEqual(data["services"], {"com.example.worker": str(self.plist.resolve())})
        encoded = json.dumps(result)
        self.assertNotIn("ProgramArguments", encoded)
        self.assertNotIn("secret-value", encoded)
        self.assertEqual(result["service"]["scope"], "user")

    def test_unregistered_unknown_system_and_invalid_action_are_rejected(self) -> None:
        with self.assertRaises(services.LocalServiceError):
            self.manager.service_action("com.example.worker", "stop")
        with self.assertRaises(services.LocalServiceError):
            self.manager.service_action("com.apple.some-service", "start")
        with self.assertRaises(services.LocalServiceError):
            self.manager.service_action("com.example.worker", "restart")
        self.assertEqual(self.runner.calls, [])

    def test_start_bootstraps_when_unloaded_and_kickstarts_when_loaded(self) -> None:
        self.manager.register_service("com.example.worker")
        self.runner.calls.clear()
        result = self.manager.service_action("com.example.worker", "start")
        self.assertIn(["launchctl", "bootstrap", "gui/501", str(self.plist.resolve())], self.runner.calls)
        self.assertTrue(result["service"]["loaded"])
        self.assertTrue(result["service"]["running"])
        self.runner.calls.clear()
        self.manager.service_action("com.example.worker", "start")
        self.assertIn(["launchctl", "kickstart", "gui/501/com.example.worker"], self.runner.calls)

    def test_stop_and_autostart_policy_are_independent_commands(self) -> None:
        self.manager.register_service("com.example.worker")
        self.runner.calls.clear()
        self.manager.service_action("com.example.worker", "stop")
        self.assertIn(["launchctl", "bootout", "gui/501/com.example.worker"], self.runner.calls)
        self.assertFalse(any(call[:2] == ["launchctl", "disable"] for call in self.runner.calls))
        self.runner.calls.clear()
        self.manager.service_action("com.example.worker", "disable")
        self.assertIn(["launchctl", "disable", "user/501/com.example.worker"], self.runner.calls)
        self.assertNotIn(["launchctl", "bootout", "gui/501/com.example.worker"], self.runner.calls)
        self.runner.calls.clear()
        self.manager.service_action("com.example.worker", "enable")
        self.assertIn(["launchctl", "enable", "user/501/com.example.worker"], self.runner.calls)

    def test_items_must_be_scanned_user_path_and_are_not_trusted_as_plist_data(self) -> None:
        self.manager.register_service("com.example.worker")
        result = self.manager.list_services([
            {"scope": "user", "path": str(self.plist.resolve()), "label": "com.example.worker",
             "program": "leaked-argument", "ProgramArguments": ["secret-value"]},
            {"scope": "local-daemons", "path": str(self.plist), "label": "com.example.worker"},
            {"scope": "user", "path": str(Path(self.temp.name) / "elsewhere.plist"), "label": "com.example.worker"},
        ])
        self.assertEqual(len(result["services"]), 1)
        service = result["services"][0]
        self.assertEqual(service["program"], "python3")
        self.assertTrue(service["registered"])
        self.assertNotIn("ProgramArguments", json.dumps(result))
        self.assertNotIn("secret-value", json.dumps(result))

    def test_registry_path_symlink_is_rejected(self) -> None:
        self.manager.register_service("com.example.worker")
        target = Path(self.temp.name) / "real-registry.json"
        target.write_text(self.registry.read_text(encoding="utf-8"), encoding="utf-8")
        self.registry.unlink()
        self.registry.symlink_to(target)
        with self.assertRaises(services.LocalServiceError):
            self.manager.service_action("com.example.worker", "stop")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    unittest.main()
