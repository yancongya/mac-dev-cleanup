"""Explicitly managed per-user LaunchAgents for mac-dev-cleanup.

This module intentionally exposes only a small allowlist workflow. A LaunchAgent
is controllable only after the user registers its exact Label, and every action
revalidates the plist path and contents before invoking launchctl.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


class LocalServiceError(ValueError):
    """A service request violates the local-service safety policy."""


_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,254}$")
_ACTIONS = {"start", "stop", "enable", "disable"}
_DEFAULT_HOME = Path.home()
_DEFAULT_LAUNCH_AGENTS = _DEFAULT_HOME / "Library" / "LaunchAgents"
_DEFAULT_REGISTRY = _DEFAULT_HOME / ".codex" / "logs" / "mac-dev-cleanup" / "managed-services.json"
Runner = Callable[..., Any]


def _valid_label(label: object) -> str:
    if not isinstance(label, str) or not _LABEL_RE.fullmatch(label) or label.startswith("com.apple."):
        raise LocalServiceError("invalid or protected service label")
    return label


def _default_runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, **kwargs)


class LocalServices:
    """Manage user-approved LaunchAgents. All dependencies are injectable."""

    def __init__(self, *, runner: Runner | None = None, uid: int | None = None,
                 launch_agents: Path | str | None = None,
                 registry_path: Path | str | None = None) -> None:
        self.runner = runner or _default_runner
        self.uid = os.getuid() if uid is None else int(uid)
        if self.uid <= 0:
            raise LocalServiceError("invalid user id")
        self.launch_agents = Path(launch_agents) if launch_agents is not None else _DEFAULT_LAUNCH_AGENTS
        self.registry_path = Path(registry_path) if registry_path is not None else _DEFAULT_REGISTRY

    @property
    def domain(self) -> str:
        return f"gui/{self.uid}"

    @property
    def persistent_domain(self) -> str:
        return f"user/{self.uid}"

    def _run(self, argv: list[str]) -> tuple[int, str]:
        # argv is constructed internally; never accept command fragments from callers.
        result = self.runner(argv, capture_output=True, text=True, timeout=10, check=False)
        return int(getattr(result, "returncode", 1)), str(getattr(result, "stdout", "") or "") + str(getattr(result, "stderr", "") or "")

    def _candidate(self, label: str) -> tuple[Path, dict[str, Any]]:
        label = _valid_label(label)
        root = self.launch_agents
        try:
            if root.is_symlink() or not root.is_dir():
                raise LocalServiceError("LaunchAgents directory unavailable or unsafe")
            root_real = root.resolve(strict=True)
            # Resolve the candidate from an actual directory scan so callers can
            # never manufacture an arbitrary plist path.
            matches = [entry for entry in root.glob("*.plist") if entry.name == f"{label}.plist"]
            if len(matches) != 1:
                raise LocalServiceError("service plist not found in LaunchAgents scan")
            path = matches[0]
            if path.is_symlink() or not path.is_file():
                raise LocalServiceError("service plist not found as a regular file")
            resolved = path.resolve(strict=True)
            if resolved.parent != root_real or path.name != f"{label}.plist":
                raise LocalServiceError("service plist escapes LaunchAgents directory")
            with resolved.open("rb") as stream:
                raw = plistlib.load(stream)
        except LocalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 — malformed plist must fail closed
            raise LocalServiceError("service plist is unreadable or invalid") from exc
        if not isinstance(raw, dict) or raw.get("Label") != label:
            raise LocalServiceError("plist Label does not exactly match registered label")
        if label.startswith("com.apple."):
            raise LocalServiceError("system services cannot be managed")
        return resolved, raw

    def _registry(self) -> dict[str, str]:
        try:
            if self.registry_path.is_symlink():
                raise LocalServiceError("service registry must not be a symlink")
            if not self.registry_path.exists():
                return {}
            value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except LocalServiceError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise LocalServiceError("service registry is unreadable or invalid") from exc
        if not isinstance(value, dict) or value.get("schema") != "mac-dev-cleanup.managed-services.v1" or not isinstance(value.get("services"), dict):
            raise LocalServiceError("service registry schema is invalid")
        result: dict[str, str] = {}
        for key, registered_path in value["services"].items():
            if not isinstance(key, str) or not isinstance(registered_path, str):
                continue
            try:
                checked_label = _valid_label(key)
                checked_path, _ = self._candidate(checked_label)
            except LocalServiceError:
                continue
            if str(checked_path) == registered_path:
                result[checked_label] = registered_path
        return result

    def _save_registry(self, services: dict[str, str]) -> None:
        path = self.registry_path
        if path.is_symlink():
            raise LocalServiceError("service registry must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise LocalServiceError("service registry directory must not be a symlink")
        payload = {"schema": "mac-dev-cleanup.managed-services.v1", "services": dict(sorted(services.items()))}
        fd, temporary = tempfile.mkstemp(prefix=".managed-services-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _state(self, label: str, path: Path, raw: dict[str, Any], registered: bool) -> dict[str, Any]:
        domain_label = f"{self.domain}/{label}"
        code, printed = self._run(["launchctl", "print", domain_label])
        loaded = code == 0
        enabled_code, disabled_text = self._run(["launchctl", "print-disabled", self.persistent_domain])
        # launchctl print-disabled returns a mapping; treat unknown output as unknown.
        disabled_match = re.search(r"[\"']?" + re.escape(label) + r"[\"']?\s*=>\s*(true|false|disabled|enabled)", disabled_text, re.IGNORECASE)
        disabled = disabled_match.group(1).lower() in {"true", "disabled"} if enabled_code == 0 and disabled_match else None
        running = bool(re.search(r"\bstate\s*=\s*running\b", printed, re.IGNORECASE)) if loaded else False
        program = raw.get("Program")
        if not isinstance(program, str):
            args = raw.get("ProgramArguments")
            program = args[0] if isinstance(args, list) and args and isinstance(args[0], str) else ""
        # Display only a safe executable basename; argument vectors and arbitrary
        # plist strings are never reflected through the JSON API.
        program_name = Path(program).name if program and not any(ch.isspace() for ch in program) else ""
        if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,128}", program_name):
            program_name = ""
        return {
            "label": label,
            "program": program_name,
            "scope": "user",
            "path": str(path),
            "registered": registered,
            "loaded": loaded,
            "running": running,
            "enabled": None if disabled is None else not disabled,
            "run_at_load": raw.get("RunAtLoad") is True,
            "keep_alive": bool(raw.get("KeepAlive")),
            "reason": None if registered else "仅允许显式登记的用户 LaunchAgent 执行管理操作",
        }

    def list_services(self, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """List candidate LaunchAgents; unknown/system scope entries remain read-only."""
        registered = self._registry()
        if items is None:
            candidates: list[dict[str, Any]] = []
            try:
                if self.launch_agents.is_dir() and not self.launch_agents.is_symlink():
                    candidates = [{"path": str(p), "scope": "user"} for p in sorted(self.launch_agents.glob("*.plist"))]
            except OSError:
                candidates = []
        else:
            candidates = items
        services: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates:
            if not isinstance(item, dict) or item.get("scope") != "user":
                continue
            candidate_path = item.get("path")
            if not isinstance(candidate_path, str):
                continue
            try:
                path = Path(candidate_path)
                # Require exact canonical path derived from label; do not trust the supplied path.
                label = _valid_label(item.get("label") or path.stem)
                verified_path, raw = self._candidate(label)
                if path != verified_path or label in seen:
                    continue
                seen.add(label)
                is_registered = registered.get(label) == str(verified_path)
                services.append(self._state(label, verified_path, raw, is_registered))
            except (LocalServiceError, OSError):
                continue
        return {"ok": True, "services": services}

    def register_service(self, label: str) -> dict[str, Any]:
        label = _valid_label(label)
        path, raw = self._candidate(label)
        registered = self._registry()
        registered[label] = str(path)
        self._save_registry(registered)
        return {"ok": True, "service": self._state(label, path, raw, True)}

    def create_service(self, label: str, program: str, arguments: list[str],
                       working_directory: str | None = None,
                       run_at_load: bool = False, keep_alive: bool = False) -> dict[str, Any]:
        """Create a user LaunchAgent from an explicit argv vector (never a shell string)."""
        label = _valid_label(label)
        if not isinstance(program, str) or not os.path.isabs(program) or "\x00" in program:
            raise LocalServiceError("program must be an absolute executable path")
        executable = Path(program)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise LocalServiceError("program must exist and be executable")
        if not isinstance(arguments, list) or len(arguments) > 128 or any(
                not isinstance(arg, str) or "\x00" in arg or len(arg) > 4096 for arg in arguments):
            raise LocalServiceError("arguments must be a list of plain strings")
        if type(run_at_load) is not bool or type(keep_alive) is not bool:
            raise LocalServiceError("startup options must be booleans")
        cwd: Path | None = None
        if working_directory is not None:
            if not isinstance(working_directory, str) or "\x00" in working_directory or not os.path.isabs(working_directory):
                raise LocalServiceError("working directory must be an absolute path")
            cwd = Path(working_directory)
            if cwd.is_symlink() or not cwd.is_dir():
                raise LocalServiceError("working directory must be a real directory")
        root = self.launch_agents
        if root.is_symlink() or not root.is_dir():
            raise LocalServiceError("LaunchAgents directory unavailable or unsafe")
        target = root / f"{label}.plist"
        if target.exists() or target.is_symlink():
            raise LocalServiceError("a LaunchAgent with this label already exists")
        registry = self._registry()
        if label in registry:
            raise LocalServiceError("service is already registered")
        plist: dict[str, Any] = {
            "Label": label,
            "Program": str(executable),
            "ProgramArguments": [str(executable), *arguments],
            "RunAtLoad": run_at_load,
            "KeepAlive": keep_alive,
        }
        if cwd is not None:
            plist["WorkingDirectory"] = str(cwd)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                plistlib.dump(plist, stream, fmt=plistlib.FMT_XML, sort_keys=True)
            checked_path, raw = self._candidate(label)
            registry[label] = str(checked_path)
            self._save_registry(registry)
        except Exception:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        return {"ok": True, "service": self._state(label, checked_path, raw, True)}

    def service_action(self, label: str, action: str) -> dict[str, Any]:
        label = _valid_label(label)
        if action not in _ACTIONS:
            raise LocalServiceError("unsupported service action")
        registered = self._registry()
        path, raw = self._candidate(label)  # runtime path and exact Label revalidation
        if registered.get(label) != str(path):
            raise LocalServiceError("service is not explicitly registered")
        target = f"{self.domain}/{label}"
        persistent_target = f"{self.persistent_domain}/{label}"
        if action == "start":
            code, _ = self._run(["launchctl", "print", target])
            if code == 0:
                argv = ["launchctl", "kickstart", target]
            else:
                argv = ["launchctl", "bootstrap", self.domain, str(path)]
        elif action == "stop":
            argv = ["launchctl", "bootout", target]
        elif action == "enable":
            argv = ["launchctl", "enable", persistent_target]
        else:  # disable controls future launch policy; it does not stop a running job.
            argv = ["launchctl", "disable", persistent_target]
        code, output = self._run(argv)
        if code != 0:
            raise LocalServiceError("launchctl operation failed")
        return {"ok": True, "action": action, "service": self._state(label, path, raw, True)}


_DEFAULT = LocalServices()


def list_services(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _DEFAULT.list_services(items)


def register_service(label: str) -> dict[str, Any]:
    return _DEFAULT.register_service(label)


def create_service(label: str, program: str, arguments: list[str],
                   working_directory: str | None = None,
                   run_at_load: bool = False, keep_alive: bool = False) -> dict[str, Any]:
    return _DEFAULT.create_service(label, program, arguments, working_directory, run_at_load, keep_alive)


def service_action(label: str, action: str) -> dict[str, Any]:
    return _DEFAULT.service_action(label, action)
