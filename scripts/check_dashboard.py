#!/usr/bin/env python3
"""Validate the dashboard template, its generated copy, and the inline JavaScript.

The dashboard is a data-free shell. `dashboard_template.html` is the only tracked file;
`dashboard.html` is regenerated from it by every scan (a plain copy, hence byte-identical)
and is gitignored, so its absence is not a failure.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "dashboard_template.html"
HTML = ROOT / "dashboard.html"
STATE = Path.home() / ".codex" / "logs" / "mac-dev-cleanup" / "state.json"


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


# The only sibling scripts the page may load. Both are gitignored (machine-specific) and
# emitted next to the HTML by scan — which is exactly what keeps the HTML itself data-free.
ALLOWED_EXTERNAL_SCRIPTS = {"dashboard_data.js", "config_data.js"}

# Fallback tokens the page needs when the sibling data scripts are absent (fresh clone,
# GitHub). Real data must never replace them: scan writes it to the two JS files instead.
DATA_TOKENS = ("/*__DATA__*/null", "/*__CONFIG__*/null")


def check_shell(path: Path) -> str:
    """Assert the shape every copy of the page must have (template and generated alike)."""
    if not path.exists() or path.stat().st_size == 0:
        fail(f"missing or empty dashboard: {path}")
    html = path.read_text(encoding="utf-8")
    lowered = html.lower()
    if "cdn.jsdelivr.net" in lowered or "unpkg.com" in lowered:
        fail(f"dashboard depends on a remote runtime: {path}")
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html, re.I):
        if src not in ALLOWED_EXTERNAL_SCRIPTS:
            fail(
                f"dashboard loads unexpected external script ({src}); only "
                f"{sorted(ALLOWED_EXTERNAL_SCRIPTS)} are allowed: {path}"
            )
    if re.search(r"alpine|tailwind", lowered):
        fail(f"deprecated framework reference found: {path}")
    # Real scan data must never be inlined. Only the null fallback tokens are allowed, so a
    # data object literal (`const DATA = {...}` / `const CONFIG = [...]`) is a hard failure.
    # This is the single rule the old checker stated twice with opposite polarity.
    if re.search(r"const DATA\s*=\s*[\{\[]", html):
        fail(f"dashboard inlines real DATA; keep it data-free (reference dashboard_data.js): {path}")
    if re.search(r"const CONFIG\s*=\s*[\{\[]", html):
        fail(f"dashboard inlines real CONFIG; keep it data-free (reference config_data.js): {path}")
    missing_tokens = [token for token in DATA_TOKENS if token not in html]
    if missing_tokens:
        fail(f"dashboard fallback token(s) missing ({', '.join(missing_tokens)}): {path}")
    if 'id="boot-error"' not in html:
        fail(f"visible boot failure fallback is missing: {path}")
    return html


def check_inline_js(html: str) -> None:
    """`node --check` every inline <script> block; a syntax error would break the page."""
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


def main() -> None:
    template_html = check_shell(TEMPLATE)
    check_inline_js(template_html)

    if HTML.exists():
        html = check_shell(HTML)
        if html != template_html:
            fail(
                "dashboard.html differs from dashboard_template.html, but the build is a plain "
                "copy — either regenerate it with `scan` or delete it; do not hand-edit it"
            )
        checked = "template + generated copy"
    else:
        print("[note] dashboard.html absent (gitignored build output) — run `scan` to generate it")
        checked = "template only"

    if not STATE.exists():
        fail("state.json missing; run scan first")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("candidate_count") != len(state.get("candidates", [])):
        fail("state candidate_count does not match candidates")

    print(f"[OK] {checked}, state, and inline JavaScript are valid ({state['candidate_count']} candidates)")


if __name__ == "__main__":
    main()
