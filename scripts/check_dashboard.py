#!/usr/bin/env python3
"""Validate the generated dashboard and its dependency-free template."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "dashboard.html"
TEMPLATE = ROOT / "dashboard_template.html"
STATE = Path.home() / ".codex" / "logs" / "mac-dev-cleanup" / "state.json"


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


# Local data files the dashboard may reference. They are gitignored (machine-specific),
# emitted next to dashboard.html by scan, and make the committed HTML a data-free shell.
ALLOWED_EXTERNAL_SCRIPTS = {"dashboard_data.js", "config_data.js"}


def check_html(path: Path, *, generated: bool) -> str:
    if not path.exists() or path.stat().st_size == 0:
        fail(f"missing or empty dashboard: {path}")
    html = path.read_text(encoding="utf-8")
    lowered = html.lower()
    if "cdn.jsdelivr.net" in lowered or "unpkg.com" in lowered:
        fail(f"dashboard depends on a remote runtime: {path}")
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html, re.I):
        if src not in ALLOWED_EXTERNAL_SCRIPTS:
            fail(f"dashboard loads unexpected external script ({src}); only {sorted(ALLOWED_EXTERNAL_SCRIPTS)} are allowed: {path}")
    if re.search(r"alpine|tailwind", lowered):
        fail(f"deprecated framework reference found: {path}")
    # The committed HTML must not inline the real scan data/config. It may keep the
    # /*__DATA__*/null / /*__CONFIG__*/null placeholder (a no-op fallback), but must
    # never inline a data object literal (const DATA = {...} / const CONFIG = [...]).
    if generated and re.search(r"const DATA\s*=\s*[\{\[]", html):
        fail("generated dashboard inlines real DATA; keep it data-free (reference dashboard_data.js)")
    if generated and re.search(r"const CONFIG\s*=\s*[\{\[]", html):
        fail("generated dashboard inlines real CONFIG; keep it data-free (reference config_data.js)")
    if not generated and ("/*__DATA__*/null" not in html or "/*__CONFIG__*/null" not in html):
        fail("dashboard template injection tokens are missing")
    if 'id="boot-error"' not in html:
        fail(f"visible boot failure fallback is missing: {path}")
    return html


def main() -> None:
    template_html = check_html(TEMPLATE, generated=False)
    html = check_html(HTML, generated=True)
    if not STATE.exists():
        fail("state.json missing; run scan first")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("candidate_count") != len(state.get("candidates", [])):
        fail("state candidate_count does not match candidates")
    if "const DATA =" not in html or "const CONFIG =" not in html:
        fail("generated dashboard does not contain inlined DATA and CONFIG")
    if "const DATA =" not in template_html or "const CONFIG =" not in template_html:
        fail("dashboard template does not define DATA and CONFIG")

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

    print(f"[OK] dependency-free dashboard template, generated page, state, and inline JavaScript are valid ({state['candidate_count']} candidates)")


if __name__ == "__main__":
    main()
