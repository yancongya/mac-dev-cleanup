#!/usr/bin/env python3
"""Local control plane for mac-dev-cleanup.

Binds to loopback only. The dashboard may read state/config, atomically update the
validated config, trigger a read-only scan, view operation history, clear the
quarantine trash, and execute per-candidate cleanup (quarantine only, restorable).

All POST endpoints require an X-MDC-Token header whose value is a random token
regenerated at every server start and served via GET /api/health. Cross-origin
pages can neither read that response (no CORS headers are ever sent) nor attach
the custom header without passing a preflight this server never answers, so a
malicious website cannot drive the API from a victim's browser.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mac_dev_cleanup.py"
STATE_PATH = Path.home() / ".codex" / "logs" / "mac-dev-cleanup" / "state.json"
OPERATIONS_DIR = Path.home() / ".codex" / "logs" / "mac-dev-cleanup" / "operations"
QUARANTINE_DIR = Path.home() / ".Trash" / "mac-dev-cleanup"
MAX_BODY = 256 * 1024
SCAN_LOCK = threading.Lock()

# Regenerated per server start; the page reads it from /api/health (same-origin
# only) and echoes it back on every POST. See the module docstring for why a
# cross-origin page cannot obtain or use it.
API_TOKEN = secrets.token_hex(16)
CAND_ID_RE = re.compile(r"^[0-9a-f]{8,32}$")

# Live state of the at-most-one background cleanup. The CLI first does a full
# scan before cleaning, which can take minutes — that is why execution is
# async: POST /api/clean only starts it, GET /api/clean/status returns the
# captured output so the dashboard can stream progress.
EXEC_MUX = threading.Lock()
EXEC_STATE = {"running": False, "mode": "", "ids": 0, "started": 0.0,
              "lines": [], "operation_id": None, "exit_code": None}

sys.path.insert(0, str(SCRIPT.parent))
import mac_dev_cleanup as cleanup  # noqa: E402

# The CLI module owns the policy path; never re-derive it here. It resolves to
# LOG_DIR/config.json (outside the Skill directory), so a `skilldo update` that
# rebuilds the Skill directory cannot reset the panel's policy.
CONFIG_PATH = cleanup.CONFIG_PATH


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
            self.send_json(200, {
                "ok": True, "service": "mac-dev-cleanup",
                "destructive_http_actions": True, "token": API_TOKEN,
            })
            return
        if path == "/api/clean/status":
            with EXEC_MUX:
                snap = {k: (list(v) if isinstance(v, list) else v) for k, v in EXEC_STATE.items()}
            self.send_json(200, snap)
            return
        if path == "/api/operations":
            self._handle_operations_get()
            return
        if path == "/api/trash":
            self._handle_trash_get()
            return
        super().do_GET()

    def _handle_operations_get(self) -> None:
        """Return operation history from the operations directory."""
        ops = []
        if OPERATIONS_DIR.is_dir():
            for f in sorted(OPERATIONS_DIR.glob("*.json"), reverse=True):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    entries = data.get("entries", [])
                    total_bytes = sum(e.get("size", 0) for e in entries)
                    ops.append({
                        "operation_id": data.get("operation_id", f.stem),
                        "timestamp": data.get("timestamp", ""),
                        "mode": data.get("mode", ""),
                        "entry_count": len(entries),
                        "total_bytes": total_bytes,
                        "restore_command": f"python3 scripts/mac_dev_cleanup.py --restore {data.get('operation_id', f.stem)}",
                    })
                except (OSError, json.JSONDecodeError):
                    continue
        self.send_json(200, {"operations": ops})

    def _handle_trash_get(self) -> None:
        """Return quarantine trash status and size."""
        total_bytes = 0
        op_dirs = []
        if QUARANTINE_DIR.is_dir():
            for d in sorted(QUARANTINE_DIR.iterdir()):
                if d.is_dir():
                    dir_bytes = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                    op_dirs.append({"operation_id": d.name, "bytes": dir_bytes})
                    total_bytes += dir_bytes
        self.send_json(200, {"total_bytes": total_bytes, "operations": op_dirs})

    def _authorized(self) -> bool:
        if self.headers.get("X-MDC-Token") != API_TOKEN:
            self.send_json(403, {"ok": False, "error": "missing or invalid token"})
            return False
        return True

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self._authorized():
            return
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
        if path == "/api/trash/clear":
            self._handle_trash_clear()
            return
        if path == "/api/clean":
            self._handle_clean(payload if isinstance(payload, dict) else {})
            return
        self.send_json(404, {"ok": False, "error": "unknown API endpoint"})

    def _handle_clean(self, payload: dict) -> None:
        """Start per-candidate cleanup through the CLI (quarantine, restorable).

        Accepts only validated candidate ids and one of the two clean modes; the
        CLI's own safety rules (WeChat running, require_quit apps, path guards)
        apply unchanged because execution is a plain subprocess of the same
        binary the terminal uses. Runs async — progress streams via
        GET /api/clean/status.
        """
        mode = payload.get("mode")
        if mode not in ("clean-safe", "clean-aggressive"):
            self.send_json(400, {"ok": False, "error": "mode must be clean-safe or clean-aggressive"})
            return
        ids = payload.get("candidate_ids")
        if (not isinstance(ids, list) or not ids or len(ids) > 500
                or not all(isinstance(i, str) and CAND_ID_RE.match(i) for i in ids)):
            self.send_json(400, {"ok": False, "error": "candidate_ids must be a non-empty list of valid candidate ids"})
            return
        apply = payload.get("apply", True)
        if not isinstance(apply, bool):
            apply = True
        with EXEC_MUX:
            if EXEC_STATE["running"]:
                self.send_json(409, {"ok": False, "error": "another operation is running"})
                return
            EXEC_STATE.update(running=True, mode=mode, ids=len(ids), started=time.time(),
                              lines=[], operation_id=None, exit_code=None)
        argv = [sys.executable, str(SCRIPT), mode]
        for cid in ids:
            argv += ["--candidate-id", cid]
        if apply:
            argv.append("--apply")

        def worker() -> None:
            try:
                proc = subprocess.Popen(argv, cwd=ROOT, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        bufsize=1)
                assert proc.stdout is not None
                for line in proc.stdout:
                    with EXEC_MUX:
                        EXEC_STATE["lines"].append(line.rstrip("\n"))
                        if len(EXEC_STATE["lines"]) > 800:
                            del EXEC_STATE["lines"][:200]
                code = proc.wait(timeout=600)
                joined = "\n".join(EXEC_STATE["lines"])
                m = re.search(r"^operation_id:\s*(\S+)", joined, re.M)
                with EXEC_MUX:
                    EXEC_STATE["exit_code"] = code
                    EXEC_STATE["operation_id"] = m.group(1) if m else None
                    EXEC_STATE["running"] = False
            except Exception as exc:  # noqa: BLE001 — background thread, report anything
                with EXEC_MUX:
                    EXEC_STATE["exit_code"] = -1
                    EXEC_STATE["lines"].append(f"[server error] {exc}")
                    EXEC_STATE["running"] = False

        threading.Thread(target=worker, daemon=True).start()
        self.send_json(200, {"ok": True, "started": True, "mode": mode, "count": len(ids), "apply": apply})

    def _handle_trash_clear(self) -> None:
        """Delete all quarantine directories under ~/.Trash/mac-dev-cleanup/."""
        if not QUARANTINE_DIR.is_dir():
            self.send_json(200, {"ok": True, "deleted": 0, "freed_bytes": 0})
            return
        deleted = 0
        freed = 0
        for d in QUARANTINE_DIR.iterdir():
            if d.is_dir():
                dir_bytes = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                shutil.rmtree(d, ignore_errors=True)
                if not d.exists():
                    deleted += 1
                    freed += dir_bytes
        self.send_json(200, {"ok": True, "deleted": deleted, "freed_bytes": freed})


class LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True


def resolve_port(cli_port: int | None) -> int:
    """Pick the dashboard port: --port, then MDC_PORT, then the policy file.

    8765 is a common neighbour (a Codex auto-resume daemon already listens there
    on this machine), so the default lives in `config.json: dashboard_port`
    rather than being hardcoded here.
    """
    if cli_port is not None:
        return cli_port
    env = os.environ.get("MDC_PORT", "").strip()
    if env.isdigit():
        return int(env)
    return int(cleanup.CONFIG.get("dashboard_port", 8766))


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the mac-dev-cleanup dashboard and safe local API.")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="override the port (default: MDC_PORT env var, else config.json dashboard_port)",
    )
    args = parser.parse_args()
    port = resolve_port(args.port)
    server = LoopbackServer(("127.0.0.1", port), Handler)
    print(f"mac-dev-cleanup dashboard: http://127.0.0.1:{port}/dashboard.html")
    print("HTTP actions: read state/config, update validated config, read-only scan, per-candidate cleanup (quarantine only, token-guarded).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
