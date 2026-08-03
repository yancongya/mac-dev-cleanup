#!/usr/bin/env python3
"""Validate that the static dashboard can boot fully offline."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "dashboard.html"
STATE = Path.home() / ".codex" / "logs" / "mac-dev-cleanup" / "state.json"
REQUIRED_ASSETS = [
    ROOT / "vendor" / "tailwind-play.js",
    ROOT / "vendor" / "alpine.min.js",
    ROOT / "dashboard_data.js",
    ROOT / "config_data.js",
]


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not HTML.exists():
        fail(f"missing {HTML}")
    for asset in REQUIRED_ASSETS:
        if not asset.exists() or asset.stat().st_size == 0:
            fail(f"missing or empty asset: {asset}")

    html = HTML.read_text(encoding="utf-8")
    if "cdn.jsdelivr.net" in html or "http://" in html or "https://" in html:
        fail("dashboard still depends on remote runtime assets")
    if 'src="vendor/alpine.min.js"' not in html:
        fail("local Alpine runtime is not loaded")
    if 'src="vendor/tailwind-play.js"' not in html:
        fail("local Tailwind runtime is not loaded")
    if "x-collapse" in html:
        fail("x-collapse is used without the Alpine Collapse plugin")
    if 'id="boot-error"' not in html or "__DASHBOARD_BOOTED__" not in html:
        fail("visible boot failure fallback is missing")

    if not STATE.exists():
        fail("state.json missing; run scan first")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("candidate_count") != len(state.get("candidates", [])):
        fail("state candidate_count does not match candidates")

    inline_scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.S)
    with tempfile.TemporaryDirectory(prefix="mac-clean-dashboard-") as temp:
        for index, source in enumerate(inline_scripts):
            if not source.strip():
                continue
            path = Path(temp) / f"inline-{index}.js"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
            if result.returncode != 0:
                fail(f"inline JavaScript syntax error: {result.stderr.strip()}")

    print(f"[OK] offline dashboard assets, state, and inline JavaScript are valid ({state['candidate_count']} candidates)")


if __name__ == "__main__":
    main()
