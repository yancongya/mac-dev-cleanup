#!/usr/bin/env python3
"""Local control plane for mac-dev-cleanup.

Binds to loopback only. The dashboard may read state/config, atomically update the
validated config, and trigger a read-only scan. Destructive cleanup is
intentionally unavailable over HTTP.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac_dev_cleanup.py"
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = Path.home() / ".codex" / "logs" / "mac-dev-cleanup" / "state.json"
MAX_BODY = 256 * 1024
SCAN_LOCK = threading.Lock()

sys.path.insert(0, str(SCRIPT.parent))
import mac_dev_cleanup as cleanup  # noqa: E402


def read_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


class Handler(SimpleHTTPRequestHandler):
    server_version = "mac-dev-cleanup/2.0"

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[web] {self.address_string()} {fmt % args}")

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> object:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if length <= 0 or length > MAX_BODY:
            raise ValueError("request body is empty or too large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/config":
            self.send_json(200, read_json(CONFIG_PATH, cleanup.DEFAULT_CONFIG))
            return
        if path == "/api/state":
            state = read_json(STATE_PATH, None)
            self.send_json(200 if state else 404, state or {"error": "state unavailable; run a scan first"})
            return
        if path == "/api/health":
            self.send_json(200, {"ok": True, "service": "mac-dev-cleanup", "destructive_http_actions": False})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = self.read_body()
        except ValueError as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})
            return
        if path == "/api/config":
            try:
                normalized = cleanup.validate_config(payload)
                cleanup.save_config(normalized)
            except (ValueError, OSError) as exc:
                self.send_json(400, {"ok": False, "error": str(exc)})
                return
            self.send_json(200, {"ok": True, "config": normalized})
            return
        if path == "/api/scan":
            if not SCAN_LOCK.acquire(blocking=False):
                self.send_json(409, {"ok": False, "error": "scan already running"})
                return
            try:
                mode = payload.get("mode", "scan") if isinstance(payload, dict) else "scan"
                if mode != "scan":
                    self.send_json(400, {"ok": False, "error": "HTTP control plane only permits read-only scan"})
                    return
                proc = subprocess.run(
                    [sys.executable, str(SCRIPT), "scan", "--limit", "0"],
                    cwd=ROOT, text=True, capture_output=True, timeout=300,
                )
                if proc.returncode != 0:
                    self.send_json(500, {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()})
                    return
                self.send_json(200, {"ok": True, "state": read_json(STATE_PATH, {}), "output": proc.stdout})
            except subprocess.TimeoutExpired:
                self.send_json(504, {"ok": False, "error": "scan timed out"})
            finally:
                SCAN_LOCK.release()
            return
        self.send_json(404, {"ok": False, "error": "unknown API endpoint"})


class LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the mac-dev-cleanup dashboard and safe local API.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = LoopbackServer(("127.0.0.1", args.port), Handler)
    print(f"mac-dev-cleanup dashboard: http://127.0.0.1:{args.port}/dashboard.html")
    print("HTTP actions: read state/config, update validated config, read-only scan. Cleanup remains CLI-only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
