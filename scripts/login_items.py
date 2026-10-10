#!/usr/bin/env python3
"""Read macOS Open at Login entries through System Events (no mutations)."""
from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from typing import Any


FIELD_SEPARATOR = "\x1f"
ROW_SEPARATOR = "\x1e"
SETTINGS_URL = "x-apple.systempreferences:com.apple.LoginItems-Settings.extension"

# System Events exposes the user's traditional Open at Login list through its
# native Apple Events interface. App Background Activity and extensions are a
# separate macOS surface and are intentionally not inferred from this list.
_APPLESCRIPT = r'''tell application "System Events"
    set fieldSeparator to ASCII character 31
    set rowSeparator to ASCII character 30
    set outputItems to {}
    repeat with loginItem in every login item
        set itemName to name of loginItem as text
        set itemPath to ""
        try
            set pathValue to path of loginItem
            if pathValue is not missing value then set itemPath to pathValue as text
        end try
        set itemKind to ""
        try
            set itemKind to kind of loginItem as text
        end try
        set itemHidden to "false"
        try
            set itemHidden to hidden of loginItem as text
        end try
        set end of outputItems to itemName & fieldSeparator & itemPath & fieldSeparator & itemKind & fieldSeparator & itemHidden
    end repeat
    set AppleScript's text item delimiters to rowSeparator
    set outputText to outputItems as text
    set AppleScript's text item delimiters to ""
    return outputText
end tell'''


class LoginItemsError(RuntimeError):
    """System Events inventory could not be read safely."""


def _parse_rows(output: str) -> list[dict[str, Any]]:
    output = output.rstrip("\r\n")
    if not output:
        return []
    items: list[dict[str, Any]] = []
    for row in output.split(ROW_SEPARATOR):
        fields = row.split(FIELD_SEPARATOR)
        if len(fields) != 4 or not fields[0].strip():
            raise LoginItemsError("System Events returned an invalid login item record")
        name, path, kind, hidden = fields
        stable_id = hashlib.sha256((name + "\0" + path).encode("utf-8")).hexdigest()[:20]
        normalized_kind = "application" if path.lower().endswith(".app") else (kind or "unknown")
        items.append({
            "id": stable_id,
            "name": name,
            "path": path or None,
            "kind": normalized_kind,
            "hidden": hidden.strip().lower() == "true",
            "enabled": True,
            "scope": "open-at-login",
            "control": "system-settings",
        })
    return items


def list_login_items(
    *, runner: Callable[..., Any] = subprocess.run,
    timeout: float = 10,
) -> dict[str, Any]:
    """Return traditional Login Items; never changes login or background state."""
    try:
        result = runner(
            ["/usr/bin/osascript", "-e", _APPLESCRIPT],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LoginItemsError("System Events did not respond; use macOS Login Items settings") from exc
    except OSError as exc:
        raise LoginItemsError("AppleScript is unavailable; use macOS Login Items settings") from exc
    if result.returncode != 0:
        # Do not echo Apple Event error text; it can contain machine paths or app names.
        raise LoginItemsError("Login Items could not be read; allow the local dashboard to access System Events or use macOS settings")
    return {
        "ok": True,
        "readOnly": True,
        "source": "System Events",
        "scope": "Open at Login",
        "items": _parse_rows(result.stdout),
        "settingsUrl": SETTINGS_URL,
        "limitations": [
            "App Background Activity and extensions are not included.",
            "macOS does not provide a public API for this dashboard to toggle another app's login registration; use Login Items & Extensions settings.",
        ],
    }
