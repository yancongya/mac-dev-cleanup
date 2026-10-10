#!/usr/bin/env python3
"""Export a validated, path-free summary from the latest saved scan state.

This module intentionally does not import the cleanup engine: importing that
module can load policy and inspect the local mount table. Exporting a summary
must only read the existing state file and write the explicitly requested
allowlisted artifact.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


STATE_PATH = Path.home() / ".codex" / "logs" / "mac-dev-cleanup" / "state.json"
SCHEMA = "mac-dev-cleanup.summary.v1"
MODES = {"scan", "clean-safe", "clean-aggressive"}
RISKS = ("safe", "aggressive", "manual")
BYTE_FIELDS = {
    "safeBytes": "safe_bytes",
    "aggressiveBytes": "aggressive_bytes",
    "manualBytes": "manual_bytes",
    "selectedBytes": "selected_bytes",
}
MAX_STATE_BYTES = 32 * 1024 * 1024
MAX_FUTURE_SKEW = dt.timedelta(minutes=5)


class SummaryError(ValueError):
    """A saved state cannot be safely projected into the summary schema."""


def _non_negative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SummaryError(f"invalid {field}")
    return value


def build_export_summary(state: Any, *, now: dt.datetime | None = None) -> dict[str, Any]:
    """Validate existing state and return exactly the public summary fields."""
    if not isinstance(state, dict):
        raise SummaryError("saved state must be an object")

    timestamp = state.get("timestamp")
    if not isinstance(timestamp, str):
        raise SummaryError("invalid timestamp")
    try:
        scanned_at = dt.datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise SummaryError("invalid timestamp") from exc
    if scanned_at.tzinfo is None or scanned_at.utcoffset() is None:
        raise SummaryError("timestamp must include a timezone")
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise SummaryError("validation clock must include a timezone")
    if scanned_at.astimezone(dt.timezone.utc) > current.astimezone(dt.timezone.utc) + MAX_FUTURE_SKEW:
        raise SummaryError("timestamp is too far in the future")

    mode = state.get("mode")
    if not isinstance(mode, str) or mode not in MODES:
        raise SummaryError("invalid mode")
    if state.get("apply") is not False:
        raise SummaryError("only non-applied scan state can be exported")

    candidates = state.get("candidates")
    if not isinstance(candidates, list):
        raise SummaryError("invalid candidates")
    candidate_count = _non_negative_int(state.get("candidate_count"), "candidate_count")
    if candidate_count != len(candidates):
        raise SummaryError("candidate count does not match saved candidates")

    risk_counts = {risk: 0 for risk in RISKS}
    risk_bytes = {risk: 0 for risk in RISKS}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise SummaryError("invalid candidate entry")
        risk = candidate.get("risk")
        if not isinstance(risk, str) or risk not in risk_counts:
            raise SummaryError("invalid candidate risk")
        size = candidate.get("size")
        if not isinstance(size, int) or isinstance(size, bool):
            raise SummaryError("invalid candidate size")
        risk_counts[risk] += 1
        # The cleanup engine uses negative sizes (currently -1) for candidates
        # whose size could not be measured, and excludes those from all totals.
        if size >= 0:
            risk_bytes[risk] += size
    if sum(risk_counts.values()) != candidate_count:
        raise SummaryError("risk counts do not match candidate count")

    byte_totals = {
        public_name: _non_negative_int(state.get(source_name), public_name)
        for public_name, source_name in BYTE_FIELDS.items()
    }
    safe = byte_totals["safeBytes"]
    aggressive = byte_totals["aggressiveBytes"]
    selected = byte_totals["selectedBytes"]
    if (safe, aggressive, byte_totals["manualBytes"]) != (
        risk_bytes["safe"], risk_bytes["aggressive"], risk_bytes["manual"]
    ):
        raise SummaryError("risk byte totals do not match saved candidates")
    deletable = _non_negative_int(state.get("deletable_bytes"), "deletable_bytes")
    if deletable != safe + aggressive:
        raise SummaryError("deletable bytes do not match risk totals")
    expected_selected = {
        "scan": 0,
        "clean-safe": safe,
        "clean-aggressive": safe + aggressive,
    }[mode]
    if selected != expected_selected:
        raise SummaryError("selected bytes do not match mode and risk totals")

    # Construct an allowlist projection. Never copy candidate records, config,
    # dashboard data, or arbitrary top-level state keys into the export.
    return {
        "schema": SCHEMA,
        "timestamp": timestamp,
        "mode": mode,
        "apply": False,
        "candidateCount": candidate_count,
        "riskCounts": risk_counts,
        **byte_totals,
    }


def write_export(path: Path, summary: dict[str, Any]) -> None:
    """Atomically write a private artifact to the caller-selected path."""
    if path.is_symlink():
        raise SummaryError("output must not be a symbolic link")
    if path.exists() and not path.is_file():
        raise SummaryError("output must be a regular file")
    if not path.parent.is_dir():
        raise SummaryError("output directory does not exist")

    payload = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=".mac-cleanup-summary-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def export_summary(state_path: Path, output_path: Path) -> dict[str, Any]:
    """Read the saved state and export its safe summary; never scans or cleans."""
    if state_path.is_symlink() or not state_path.is_file():
        raise SummaryError("saved scan state is unavailable")
    try:
        same_path = state_path.resolve(strict=False) == output_path.resolve(strict=False)
        same_file = state_path.exists() and output_path.exists() and os.path.samefile(state_path, output_path)
    except OSError as exc:
        raise SummaryError("unable to compare input and output paths") from exc
    if same_path or same_file:
        raise SummaryError("output must not replace the saved scan state")
    try:
        if state_path.stat().st_size > MAX_STATE_BYTES:
            raise SummaryError("saved scan state exceeds the size limit")
        state = json.loads(state_path.read_text(encoding="utf-8"), object_pairs_hook=_state_object)
    except SummaryError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise SummaryError("saved scan state is unreadable or malformed") from exc
    summary = build_export_summary(state)
    write_export(output_path, summary)
    return summary


def _state_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Discard private fields while decoding the saved state object tree."""
    value = dict(pairs)
    # Candidate paths and descriptions are private. Keep only risk and size,
    # which are needed to validate the aggregate counts and byte totals.
    if "risk" in value:
        return {key: value.get(key) for key in ("risk", "size") if key in value}
    for key in ("config", "dashboard", "disk_before", "disk_after"):
        value.pop(key, None)
    return value


def main(argv: list[str] | None = None, *, state_path: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a path-free summary from the latest saved Mac cleanup state; does not scan or clean."
    )
    parser.add_argument("--output", required=True, metavar="PATH", help="Destination JSON file (must be in an existing directory).")
    args = parser.parse_args(argv)
    try:
        export_summary(state_path or STATE_PATH, Path(args.output).expanduser())
    except SummaryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("error: unable to read saved state or write summary", file=sys.stderr)
        return 2
    print(f"exported {SCHEMA} from saved state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
