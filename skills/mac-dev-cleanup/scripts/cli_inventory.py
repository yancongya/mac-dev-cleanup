#!/usr/bin/env python3
"""Read-only inventory of executable commands resolved through the current PATH."""
from __future__ import annotations

import os
from pathlib import Path


MAX_COMMANDS = 2000


def list_cli_tools(path_value: str | None = None) -> dict:
    """List commands visible in PATH without executing them or changing system state.

    For duplicate command names, only the first executable is returned, matching
    normal shell lookup order. Relative and empty PATH entries are ignored so a
    dashboard request cannot accidentally inventory the current working folder.
    """
    raw_path = os.environ.get("PATH", "") if path_value is None else path_value
    directories: list[Path] = []
    seen_dirs: set[str] = set()
    for value in raw_path.split(os.pathsep):
        if not value:
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        key = str(resolved)
        if resolved.is_dir() and key not in seen_dirs:
            seen_dirs.add(key)
            directories.append(resolved)

    tools: list[dict[str, str]] = []
    seen_names: set[str] = set()
    inaccessible = 0
    truncated = False
    for directory in directories:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name in seen_names:
                        continue
                    try:
                        if not entry.is_file(follow_symlinks=True) or not os.access(entry.path, os.X_OK):
                            continue
                        resolved_file = Path(entry.path).resolve(strict=True)
                    except OSError:
                        continue
                    if not resolved_file.is_file():
                        continue
                    if len(tools) >= MAX_COMMANDS:
                        truncated = True
                        break
                    seen_names.add(entry.name)
                    tools.append({
                        "name": entry.name,
                        "path": str(resolved_file),
                        "sourceDirectory": str(directory),
                    })
        except OSError:
            inaccessible += 1
        if truncated:
            break

    tools.sort(key=lambda item: item["name"].casefold())
    return {
        "ok": True,
        "source": "PATH",
        "scannedDirectories": len(directories),
        "inaccessibleDirectories": inaccessible,
        "commandCount": len(tools),
        "truncated": truncated,
        "tools": tools,
    }
