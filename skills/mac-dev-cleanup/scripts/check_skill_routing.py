#!/usr/bin/env python3
"""Check that Docker guidance in SKILL.md respects the ownership boundary."""

from pathlib import Path
import re
import sys


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"
ROOT = SKILL.parent
text = SKILL.read_text(encoding="utf-8")
readme_path = ROOT / "README.md"
readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""

required = (
    "local Mac OrbStack capacity only",
    "docker system df",
    "NAS Docker is managed only through Agent Ops",
    "status, logs, start, stop, restart, update, and rollback",
    "Do not SSH to the NAS for Docker work",
    "no registered local OrbStack lifecycle capability",
    "agent-ops status --scope mac --json",
    "does not run a scan or cleanup",
    "Keep cleanup execution in this Skill's explicit `--apply` path",
    "Do not empty Trash automatically after cleanup",
    "literal `EMPTY TRASH` confirmation and API token",
)
missing = [phrase for phrase in required if phrase not in text]
if missing:
    print(f"[FAIL] Missing Docker ownership rule(s): {', '.join(missing)}", file=sys.stderr)
    raise SystemExit(1)

service_cli_required = (
    "scripts/local_services_cli.py list",
    "scripts/local_services_cli.py register",
    "only the exact Label",
    "Agent Ops remains the owner of NAS container lifecycle",
)
missing_service_cli = [phrase for phrase in service_cli_required if phrase not in text]
if missing_service_cli:
    print(f"[FAIL] Missing local service CLI guidance: {', '.join(missing_service_cli)}", file=sys.stderr)
    raise SystemExit(1)

if (
    "sole editable source" not in text
    or "python3 scripts/build_skilldo_package.py build" not in text
    or "skills/mac-dev-cleanup/" not in text
    or "skilldo track-local --skill mac-dev-cleanup --path skills/mac-dev-cleanup --yes" not in text
    or "skilldo repair source --skill mac-dev-cleanup" not in text
    or "skilldo update --skill mac-dev-cleanup --yes" not in text
    or "Edit only in the central directory" in text
):
    print("[FAIL] SKILL.md does not describe the repository-to-SkillDo update chain", file=sys.stderr)
    raise SystemExit(1)

if readme and (
    "本 Skill 只读查看 Mac OrbStack 容量" not in readme
    or "NAS Docker 状态、日志和生命周期操作统一经 Agent Ops" not in readme
    or "python3 scripts/build_skilldo_package.py build" not in readme
    or "skilldo track-local --skill mac-dev-cleanup --path skills/mac-dev-cleanup --yes" not in readme
    or "skilldo repair source --skill mac-dev-cleanup" not in readme
    or "scripts/local_services_cli.py list" not in readme
):
    print("[FAIL] README.md update, source route, or Docker route conflicts with SKILL.md", file=sys.stderr)
    raise SystemExit(1)

forbidden = (
    r"docker\s+(?:container|image|volume|system|builder)\s+prune\b",
    r"docker\s+(?:container|image|volume)\s+rm\b",
    r"docker\s+rm\b",
    r"docker\s+(?:start|stop|restart|pull)\b",
    r"docker\s+compose\b",
    r"reach it over ssh",
)
found = [
    pattern
    for pattern in forbidden
    if re.search(pattern, text, re.IGNORECASE) or re.search(pattern, readme, re.IGNORECASE)
]
if found:
    print(f"[FAIL] Direct Docker write example(s) remain: {', '.join(found)}", file=sys.stderr)
    raise SystemExit(1)

if "rm -rf ~/.Trash/mac-dev-cleanup" in text or "quarantine `rm` succeeding" in text:
    print("[FAIL] Skill still recommends irreversible quarantine deletion", file=sys.stderr)
    raise SystemExit(1)

print("[OK] SKILL.md routes NAS Docker operations to Agent Ops and limits OrbStack to read-only capacity review")
