---
name: mac-dev-cleanup
description: Scan, analyze, configure, and safely clean macOS developer caches with a local web control panel, JSON policy, recoverable Trash-first cleanup, operation logs, exclusions, test artifacts, build outputs, node_modules, virtualenvs, Tauri/Vite build by-products (src-tauri/target, gen schemas, dist-ssr, vite timestamp configs), Playwright traces, Rust/Flutter caches, Blender asset/render caches, app caches/logs, screenshot and screen-recorder app caches inside Application Support (PixPin recording recovery, screenshot history), WeChat caches and expired chat media (month-window), screenshots, Docker/OrbStack image and volume review, and large-file review. Use whenever the user asks to clean or inspect Mac storage, caches, developer artifacts, Tauri/Rust build outputs, Blender caches, screenshot or screen-recorder caches, WeChat caches, Docker/OrbStack disk usage, temp files, logs, stale projects, or manage cleanup settings and reports.
---

# mac-dev-cleanup

Use this skill for macOS developer storage cleanup. Prefer the bundled script over ad hoc deletion.

## Core rules

- Always run a scan or dry run before cleanup.
- The Skill is the product; `config.json` is its single configuration source and the web dashboard is only a local control plane.
- Never delete personal media/documents, app support data, source files, `.git`, package lockfiles, or user-created assets.
- Treat `node_modules`, `.venv`, `venv`, Rust `target`, `.next`, `build`, `out`, `dist`, `.dart_tool`, `.gradle` as aggressive project-generated cleanup targets.
- Treat caches, test reports, traces, coverage, logs, temp files, and package-manager caches as safe cleanup targets when generated and rebuildable.
- Skip system directories and app data unless the user explicitly asks for those. **If a target turns out to be in use, abort that entry — never warn and continue.** Moving files out from under a running process corrupts live state (a 2026-09-09 pass moved the `.hanako` app-data directory while a HanaAgent child process was running and had to be restored by hand). App-runtime data directories (`~/.hanako`, `~/.workbuddy`, `~/.codex`, `~/.claude`, container stores) are off-limits by default: quit the app first, or leave it alone. The built-in form of this rule is the WeChat hard skip; the config-driven form is `require_quit` on an app-support entry.
- The `manual` risk level is **reported but never auto-deleted** by any mode. It covers screenshots, large project dirs, archives, dumps, and large files in personal roots — these require explicit human review.
- If required tools are not installed, continue with built-in Python scanning and report missing tools in the HTML log.
- Real cleanup is Trash-first: eligible items move to `~/.Trash/mac-dev-cleanup/<operation-id>/` and an operation manifest is written for recovery. Never bypass this with ad hoc `rm` or `shutil.rmtree`.
- After cleanup (`--apply`), **automatically empty the Trash** to actually reclaim disk space. Prefer `osascript -e 'tell application "Finder" to empty trash'` running in the background with a 10-minute polling wait (Finder AppleScript times out at ~2 min for large Trash; background + extended wait is mandatory). Verify reclaim with `df -h ~` afterward. If osascript times out, report the failure but do not block the cleanup report.
- **If AppleScript is blocked, fall back to deleting the Skill's own quarantine directory.** A TCC automation denial is *not* a timeout — it returns `execution error: … 发生权限违例 (-10004)` with exit code 1 immediately. Probe it with a read-only call: `osascript -e 'tell application "Finder" to get name of startup disk'`. If that also fails, the host process (WorkBuddy / Terminal) lacks Finder automation permission under 系统设置 → 隐私与安全性 → 自动化 — nothing is wrong with the Trash itself. The verified fallback is `rm -rf ~/.Trash/mac-dev-cleanup/<operation-id>`, which only touches quarantine this Skill created and leaves the user's other Trash contents alone. Same trade-off as emptying: `--restore` stops working. Verify with `du -sh ~/.Trash/mac-dev-cleanup` — `ls ~/.Trash/` is TCC-denied, so a failed top-level `readdir` proves nothing, while `du` can read the subpath.
- **Judge an emptied Trash by `du`, never by the quarantine directory disappearing.** A successful empty leaves the (now empty) `~/.Trash/mac-dev-cleanup/` shell in place, so a polling loop that waits for the directory to vanish always burns its full timeout and then reports a failure that never happened (600 s wasted on an already-empty Trash). Poll `du -sk ~/.Trash/mac-dev-cleanup` until it reads `0`, and only then report the reclaim as confirmed.
- The local HTTP API may read state/config, atomically save validated config, and trigger scan only. Destructive HTTP endpoints are intentionally forbidden; cleanup stays in the CLI confirmation flow.

## Install layout (SkillDo-managed, one physical copy)

This Skill is managed by **SkillDo**, which keeps a single physical directory and points every AI tool at it with symlinks:

```
~/.skillshub/mac-dev-cleanup                 <- the only real directory (central)
~/.codex/skills/mac-dev-cleanup              -> symlink to it
~/.claude/skills/mac-dev-cleanup             -> symlink to it
~/.config/mimocode/skills/mac-dev-cleanup    -> symlink to it
~/.workbuddy/skills/mac-dev-cleanup          -> symlink to it
~/Desktop/OH-WorkSpace/.agents/skills/mac-dev-cleanup -> symlink to it
```

Consequences that matter when editing:

- **Edit only in the central directory.** Any symlink resolves to it, so all five tools see a change at once. Never keep a second *real* copy of the Skill: that is precisely how this install once drifted into three copies, with four tools reading a month-old mirror while only one read the new code.
- Publish with `skilldo push --skill mac-dev-cleanup -m "..."` and pull with `skilldo update`. Do not maintain a parallel hand-rolled Git checkout of the same Skill.
- **`skilldo update` rebuilds the central directory from the repository**, deleting every file the repo does not track (`remove_dir_all` + re-clone). Measured on 2026-09-23, exactly three local-only entries are lost and nothing else — tracked content comes back byte-for-byte:
  - `.workbuddy` (the notes symlink) → re-link with `ln -s ~/.codex/logs/mac-dev-cleanup/.workbuddy ~/.skillshub/mac-dev-cleanup/.workbuddy`
  - `config_data.js` and `dashboard_data.js` → regenerated by the next `scan`
  
  Everything that must survive therefore lives *outside* the Skill directory:
  - policy → `~/.codex/logs/mac-dev-cleanup/config.json` (the script's `CONFIG_PATH`)
  - state, history, reports → `~/.codex/logs/mac-dev-cleanup/`
  - this Skill's own notes → `~/.codex/logs/mac-dev-cleanup/.workbuddy/`, symlinked in
- `.gitignore` excludes `config.json`, `state.json`, `config_data.js`, `dashboard_data.js`, `*.bak.*`, `__pycache__/`, `.workbuddy` (written without a trailing slash — the slash form matches directories only and would let the *symlink* be committed with a local absolute path inside), and the deprecated `vendor/`. Machine-local state can never reach the public repository.

## Important: APFS snapshots & disk space release

Deleted files may not immediately show as freed space on macOS APFS. The container holds deleted-file space while snapshots exist:

- `com.apple.os.update-*` snapshots — created during macOS update preparation (e.g. `MSUPrepareUpdate`). These can hold many GB until the update is installed or the snapshot is cleared.
- Time Machine local snapshots (`com.apple.TimeMachine.*`) — `tmutil listlocalsnapshots /`.

After any real deletion (`--apply`), **a reboot is the most reliable way to release snapshot-held space**. Do not assume cleanup failed just because `df` does not change immediately — verify after reboot.

Verify disk space correctly (note: `df /` returns the read-only system volume on modern macOS and is misleading):

```bash
df -h ~                                          # data volume, real available space
tmutil listlocalsnapshots /System/Volumes/Data  # the real snapshot list
diskutil apfs list | grep -i "Capacity Not Allocated"
```

**Use `tmutil`, never `diskutil`, to look for snapshots.** `diskutil apfs listSnapshots /System/Volumes/Data` prints `No snapshots` on a volume that is in fact held by Time Machine local snapshots. Acting on that output sends you chasing the wrong cause. Only `tmutil listlocalsnapshots` sees them. If it lists `com.apple.os.update-*` (especially `…MSUPrepareUpdate`), a **pending macOS update** is holding every byte you just deleted — confirm with `softwareupdate --list` and let the update install. Never hand-delete an `com.apple.os.update-*` snapshot; it is the update's rollback point.

### "Not deleted" or "not accounted for"? Run the control experiment

`df` can also freeze outright: the free-space counter on some macOS 26.x APFS Data volumes stops tracking reality, so neither writing nor deleting moves it. Distinguish the two causes *before* deleting anything a second time:

```bash
df -k /System/Volumes/Data
dd if=/dev/zero of=/tmp/__spacetest__.bin bs=1m count=512 && sync
df -k /System/Volumes/Data     # rose by ~512M? the counter still works
rm -f /tmp/__spacetest__.bin && sync
df -k /System/Volumes/Data     # did NOT fall back? the counter is stuck
```

- **Write moved it, delete did not** → the accounting is stuck (pending update / reboot placeholder). This is not a failed cleanup — stop re-deleting and reboot.
- **Neither moved it** → the counter is frozen outright; trust `du` instead.

Evidence order after an `--apply`: ① `du -sh ~/.Trash/mac-dev-cleanup` back to zero (or the quarantine `rm` succeeding) proves the bytes are really gone; ② `diskutil apfs list` → `Capacity Not Allocated` trend over a few minutes; ③ reboot, then re-check `df -h ~`.

Field-tested 2026-07-31: two cleanup rounds deleted 14.6G but `df` before/after stayed at 100% full (~590M free); after reboot, used dropped 185Gi→160Gi and available jumped 590Mi→44Gi with all `com.apple.os.update-*` snapshots gone.

Field-tested 2026-09-23: 8.2G removed with `du` back to zero, yet `df -k` never moved; a 512M control write moved it by <1M and the delete moved it not at all — a frozen counter plus a pending update, not a failed delete.

## Risk levels

| risk | behavior | examples |
|---|---|---|
| `safe` | deleted by `clean-safe` and `clean-aggressive` (with `--apply`) | `__pycache__`, pip/npm/uv cache, playwright temp, project logs, coverage, `app-support-cache` |
| `aggressive` | deleted only by `clean-aggressive` (with `--apply`) | `node_modules`, `.venv`, `build`, `dist`, Codex/Trae caches, large app caches/logs, `stale-deps`, `wechat-cache`, `wechat-media` |
| `manual` | never auto-deleted; shown in report as "needs review" | screenshots, large dirs, archives, dumps, large personal files, `stale-model`, `app-support-manual` |

Cleaning `aggressive` is not automatically worth it: **updater/runtime caches are deleted and re-downloaded the same day**, so a pass over them costs bandwidth and changes nothing. Field-observed 2026-09-22: an aggressive run removed `~/.cache/codex-runtimes` (1.6G), `hanako-updater` (437M) and `com.google.antigravity` (352M), and all three were back within hours. Spend aggressive effort on build output (`target`, `build`, `dist`, `.venv`, `node_modules`) instead, and leave self-updating runtime caches alone unless space is genuinely critical.

## Categories recognized

`global-cache`, `app-cache`, `app-log`, `app-support-cache`, `app-support-manual`, `project-generated`, `log-file`, `temp-browser`, `temp-file`, `test-artifact`, `screenshot`, `large-dir`, `large-file`, `stale-deps`, `stale-model`, `wechat-cache`, `wechat-media`

## Tauri / Vite build by-products (config-driven)

A Tauri app keeps its Rust workspace in `<project>/src-tauri`, and `tauri build` leaves several GB behind. These shapes are matched **anchored on the `src-tauri` parent**, so a generic name like `gen` elsewhere in a project is never touched.

| path | risk | why |
|---|---|---|
| `src-tauri/gen/` (capability schemas) | `safe` | regenerated by `tauri-build` on every `cargo build`, seconds to rebuild |
| `src-tauri/target/` | `aggressive` | Rust/cargo build tree, expensive to rebuild |
| `src-tauri/target/release/bundle/**` containing an installer | `manual` | `.dmg/.app/.msi/.exe/.deb/.rpm/.AppImage` are deliverables, not caches — the whole target tree is demoted so an aggressive run cannot wipe a built package |
| `dist/`, `dist-ssr/` | `aggressive` | Vite build output |
| `vite.config.ts.timestamp-*.mjs` | `safe` | throwaway config copies Vite writes on every run |
| `.vite-temp/` | `safe` | Vite dependency pre-bundle temp dir |

The bundle check is shallow (only `release/bundle/**` a few levels deep) so a multi-GB target tree is never fully walked to answer it, and the stale-project pass re-checks it — an idle project's packaged target stays `manual` instead of being promoted back to `stale-deps`.

**These names are policy, not safety boundaries, so they live in `config.json` under `build_artifacts`** and are editable in the dashboard's Settings panel. Only the immutably built-in sets (`SAFE_DIR_NAMES`, `AGGRESSIVE_DIR_NAMES`, `PRUNE_PATHS`, …) stay hardcoded; custom entries are unioned onto them and can never shrink them.

```jsonc
"build_artifacts": {
  "safe_dirs": [".vite-temp"],              // unioned onto SAFE_DIR_NAMES
  "aggressive_dirs": ["dist-ssr"],          // unioned onto AGGRESSIVE_DIR_NAMES
  "safe_file_globs": ["vite.config.*.timestamp-*.mjs"],  // fnmatch on basename
  "tauri_parents": ["src-tauri"],           // anchor dir for the two below
  "tauri_gen_dirs": ["gen"],                // -> safe
  "tauri_build_dirs": ["target"],           // -> aggressive
  "bundle_markers": [".dmg", ".app", ".msi", ".exe", ".deb", ".rpm", ".AppImage"]
}
```

Editing rules:
- Emptying `tauri_parents` (or the gen/build dir lists) simply disables those rules — the generic `target` rule still applies.
- Emptying `bundle_markers` falls back to the built-in list: that field is protection, not preference.
- Unknown keys and non-string values are rejected by `validate_config` before anything is written.
- Set `MDC_CONFIG=/path/to/config.json` to point a run at an alternate policy file (used by the tests).

## WeChat cleanup (whitelist-only)

WeChat data lives in `~/Library/Containers/com.tencent.xinWeChat` (pruned by default). The skill exempts **only** these shapes:

- `wechat-cache` (aggressive): pure caches WeChat rebuilds — `app_data/radium` (applet runtime), `app_data/log`, `app_data/crashinfo`, `Data/Library/Caches`, plus account `cache/YYYY-MM` months outside the keep window.
- `wechat-media` (aggressive): chat media month dirs strictly matching `YYYY-MM` under `<account>/msg/{attach,video,file}/` older than the keep window (`wechat_media_keep_months`, default `1` = keep current month only). Message text stays in the databases; old media simply shows as expired, matching WeChat's own semantics.

Never touched under any mode: message databases (`db_storage`), account `config`, `favorite`, `Backup/`, `all_users` — the shape check makes them structurally unmatchable.

Hard rule: if WeChat is running, `--apply` **skips all WeChat candidates** (`skipped: WeChat is running`) because moving files inside a live container risks database corruption. Quit WeChat and re-run. Note the nightly `clean-safe` automation never touches WeChat — both categories are aggressive-only.

## App-support whitelist (config-driven, shape-checked)

`~/Library/Application Support` is pruned wholesale because it holds live app data — which means an app that parks a multi-GB temp cache there is invisible to every scan. This rule mirrors the WeChat whitelist, except the shape list comes from `config.json`, so onboarding a new app is a config edit rather than a code change.

Only the **exact relative paths named in an entry** are ever exempted, and the check is a string comparison at runtime: an app's databases, settings, licences, and every other path under its root stay behind the prune wall.

```jsonc
"app_support_whitelist": [
  {
    "name": "PixPin",                                   // shown in reports
    "root": "~/Library/Application Support/PixPin",       // must sit under a PRUNE_PATHS root
    "safe": ["Temp/RecordingRecovery", "Crashpad", "pixpin.log"],
    "manual": ["History"],
    "require_quit": "PixPin.app/Contents/MacOS/PixPin"
  }
]
```

- `safe` → category `app-support-cache`, risk `safe`: temp, recording-recovery, crash-dump, and run-log data the app rebuilds on demand. Reclaimed by `clean-safe`.
- `manual` → category `app-support-manual`, risk `manual`: user-visible data such as a screenshot history. Reported for review and **never** auto-deleted — surface it explicitly in the report and ask the user before touching it.
- `require_quit` (optional) → a process match for `pgrep -f`. While that process runs, the entry's `safe` paths may be live state (a recording in progress, a log being appended), so `--apply` **skips** them and prints `skipped: <name> is running`. Quit the app and re-run to reclaim.

`_validate_app_support_whitelist` refuses anything that would widen the blast radius:

- a `root` outside every `PRUNE_PATHS` root — otherwise the whitelist would become a route to arbitrary app data;
- an absolute path, a `~`-prefixed path, or anything containing `..` — nothing may escape the entry root;
- the same path listed as both `safe` and `manual`;
- an entry with neither list, a missing or blank `name`/`root`, or an unknown key.

Onboarding one app is a config edit. The bundled PixPin entry exists because that app's recording-recovery cache reached **2.2G in a single orphaned file** (2026-09-23) while being entirely invisible to the scanner; its `History/_ScreenshotRecord` (43 files / 106M) sits beside it as `manual`, so a screenshot history is never deleted without being asked.

This key is deliberately **not** in the dashboard's Settings form: it is a list of objects, which the flat `SETTINGS_SCHEMA` ↔ `flatConfig()` mapping cannot express. Maintain it with `--set-config` or by editing `config.json` directly.

## Stale project detection

A project is **stale** when its newest real development activity is older than `--stale-days` (default 90). Activity is measured as the max of:

- newest mtime of **source files only** (`.ts/.js/.py/.rs/.go/.dart/.md/.toml/...`, see `CODE_EXTENSIONS` in the script) — `.DS_Store`, lockfiles, build info, and tool metadata dirs (`.workbuddy`, `.planning`, `.wrangler`, ...) are explicitly excluded so they don't masquerade as activity.
- last git commit timestamp parsed from `.git/logs/HEAD` (no subprocess).

For stale projects:
- dependency/build dirs (`node_modules`, `.venv`, `build`, `dist`, `target`, ...) become `stale-deps` (aggressive) — safe to remove since the project is idle.
- model/weight files (`.pth`, `.safetensors`, `.onnx`, `.bin`, `.pt`, ...) become `stale-model` (manual) — large and need re-download, so review before deleting.

The stale pass runs last in `collect` so `stale-deps`/`stale-model` labels win over generic `project-generated`/`large-file` for the same paths. Tune the threshold with `--stale-days`; use `30` for a stricter "long idle" view, `90` (default) for conservative.

## Script

Run:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py scan
```

Safe dry run:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-safe
```

Safe cleanup (moves eligible items to the Skill quarantine inside Trash):

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-safe --apply
```

The command prints an `operation_id` and an exact restore command. List and restore operations:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py --list-operations
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py --restore <operation-id>
```

Aggressive dry run:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-aggressive
```

Aggressive cleanup:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-aggressive --apply
```

Prefer a precise plan when the user names specific targets. Candidate IDs are included in `state.json` and may be repeated; category filters are also repeatable:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-safe --candidate-id <id> --apply
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-aggressive --category global-cache --apply
```

Stale-aware scan with a custom idle threshold (e.g. 30 days for a stricter "long idle" view):

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py scan --stale-days 30
```

## Configuration (config.json)

User-tunable settings live in `~/.codex/logs/mac-dev-cleanup/config.json` — deliberately **outside** the Skill directory, because `skilldo update` rebuilds that directory from the repository and would delete a policy file kept there, silently resetting this machine's settings. An install that still carries the legacy `<skill>/config.json` has it **moved** into place on first run (`adopt_legacy_config`; it never overwrites an existing policy and never runs while `MDC_CONFIG` is set). The script reads the file on every run; if missing, defaults are written. The web dashboard edits this same file via the Settings panel — `web_server.py` reuses the module's `CONFIG_PATH` rather than re-deriving its own.

```json
{
  "stale_days": 90,
  "thresholds": {
    "app_cache_min_mb": 50,
    "app_log_min_mb": 10,
    "large_dir_mb": 100,
    "large_file_mb": 50
  },
  "scan_roots": ["~/工作/开发", "~/Desktop/OH-WorkSpace", "~/Documents", "~/Developer", "~/dev", "~/workspace"],
  "personal_roots": ["~/Desktop", "~/Pictures", "~/Downloads"],
  "exclude_paths": [],
  "exclude_globs": [],
  "protected_projects": [],
  "protected_categories": [],
  "trash_retention_days": 30,
  "wechat_media_keep_months": 1,
  "build_artifacts": { "...": "see Tauri / Vite build by-products" },
  "app_support_whitelist": [ { "...": "see App-support whitelist" } ]
}
```

Read current config:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py --show-config
```

Write config (validated, normalized, and atomically replaced; unknown keys are rejected):

```bash
echo '{"stale_days":30}' | python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py --set-config
```

System-level safety sets (`GLOBAL_SAFE_PATHS`, `PRUNE_PATHS`, `SAFE_DIR_NAMES`, `MODEL_SUFFIXES`, `CODE_EXTENSIONS`, etc.) are hardcoded and not exposed via config because they are immutable safety boundaries. User exclusions only add protection; they cannot weaken those boundaries.

## Local web control panel

Start the Skill's loopback-only control server:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/web_server.py
```

Open:

```text
http://127.0.0.1:8765/dashboard.html
```

When served this way, the dashboard can:

- read the latest state and current `config.json`;
- edit thresholds, scan roots, exclusions, protected projects/categories, and retention preference;
- validate and atomically write `config.json`;
- trigger a new read-only scan and refresh the page state.

Opening `dashboard.html` directly with `file://` remains supported as a read-only fallback. In that mode, config editing generates a CLI command instead of silently pretending the file was saved.

## Modes

- `scan`: no cleanup. Reports safe, aggressive, and manual candidates plus tool self-check. `potentially_cleanable` reflects safe + aggressive capacity even in scan mode; `selected_in_mode` remains zero.
- `clean-safe`: deletes only safe generated artifacts when `--apply` is present.
- `clean-aggressive`: includes safe targets plus project dependency/build directories when `--apply` is present. `manual` items are never deleted.

## Scan roots

- Project roots (walked recursively): `~/工作/开发`, `~/Desktop/OH-WorkSpace`, `~/Documents`, `~/Developer`, `~/dev`, `~/workspace`
- Personal roots (top level only, for screenshots / large files): `~/Desktop`, `~/Pictures`, `~/Downloads`
- App roots (top level only): `~/Library/Caches` (entries ≥50M), `~/Library/Logs` (entries ≥10M)
- Temp roots: `/tmp`, `/var/folders` (Playwright/puppeteer/chrome profiles)

## Pruned (never walked)

`~/Library/Application Support`, `~/Library/Containers`, `~/Library/Group Containers`, `~/Library/Mobile Documents`, `~/Music`, `~/Movies`, `~/.Trash`, `~/.pub-cache`, `~/go/pkg/mod`. `.git`/`.svn`/`.hg` are skipped inside project walks. Two shape-checked exceptions: the WeChat whitelist above (four cache dirs plus `YYYY-MM` media months) and the app-support whitelist (only the exact relative paths named in `config.json`).

**Mount points are also never walked.** Every traversal goes through `safe_walk()`, which prunes any directory that is an active mount point (detected by string comparison against the `mount` table, so no filesystem I/O is added). This exists because a **stale network mount hangs the entire scan forever**: a dead SMB/NFS share (e.g. `//host/share` on `/tmp/<name>` whose backing service was stopped) blocks indefinitely on the first `stat()` inside it — the process shows 0% CPU with no open directory handles and never finishes. If `scan` appears stuck with no output, run `mount | grep -E "smbfs|nfs"` and check for a dead share under a scan root (`/tmp` is a scan root), then either `docker start` the service that exports it or force-unmount it. Do **not** "fix" this by patching `pruned()` — `pruned()` calls `Path.resolve()`, which stats, and would hang the same way.

The same dead mount defeats *any* recursive walk of `/tmp`, not just this Skill's: a recursive glob (`**/*`), a bare `find /tmp`, or a disk-usage tool hangs identically. Even `diskutil unmount force` can hang, because an orphaned kernel mount has no `mount_smbfs` process left to kill. The real fix is to bring the exporting side back (`docker start <container>`) or force-unmount it — and never probe `/tmp` recursively while a stale share is mounted.

## Dashboard and state

The dashboard is generated from a design template on every scan:

```text
~/.codex/skills/mac-dev-cleanup/dashboard_template.html   # design + tokens (committed)
~/.codex/skills/mac-dev-cleanup/dashboard.html            # generated, self-contained (do not edit by hand)
```

Each run overwrites the latest state file instead of creating a new HTML file:

```text
~/.codex/logs/mac-dev-cleanup/state.json
```

A compact append-only history is kept at:

```text
~/.codex/logs/mac-dev-cleanup/history.jsonl
```

State includes `deletable_bytes` (potential safe + aggressive capacity), separate `safe_bytes` / `aggressive_bytes` / `selected_bytes`, `manual_bytes`, category totals, stable candidate IDs, and per-candidate `category`/`risk`/`action`. Open the dashboard if the user asks for the visual status page.

Cleanup operations are stored under:

```text
~/.codex/logs/mac-dev-cleanup/operations/<operation-id>.json
```

Each manifest records original path, quarantine path, reason, risk, size, identity fingerprint, and restore status.

The dashboard is a **single self-contained file** with zero runtime dependencies: no CDN, no `vendor/` libraries, no Alpine/Tailwind, no separate `dashboard_data.js` / `config_data.js` `<script src>` loads. `write_state()` reads `dashboard_template.html`, inlines the current scan state and config into the `/*__DATA__*/` / `/*__CONFIG__*/` tokens, and writes the final `dashboard.html`. This is mandatory: the WorkBuddy preview webview (and `file://`) fail to boot pages that depend on sibling script files or inlined frameworks, which previously caused the "仪表盘脚本加载失败" error.

Constraints when editing the dashboard UI:
- Keep it dependency-free vanilla HTML/CSS/JS. Do NOT reintroduce Alpine, Tailwind, CDN links, or external `vendor/` scripts.
- Keep the two injection tokens `/*__DATA__*/null` and `/*__CONFIG__*/null` in the template (the build replaces them with JSON).
- In offline (`file://`) mode the scan button and settings-save fall back to generating a CLI command / downloading `config.json`; the live POST API only activates when served by `web_server.py`.
- Validate after UI changes with a headless render (jsdom) to confirm zero runtime errors and that all sections render:

  ```bash
  python3 scripts/check_dashboard.py                     # static + syntax gate
  npm i jsdom
  node scripts/check_dashboard_dom.mjs dashboard.html    # 31 headless assertions
  # or: MDC_JSDOM=/path/to/jsdom/lib/api.js node scripts/check_dashboard_dom.mjs dashboard.html
  ```

Dashboard conventions worth preserving:
- **Never re-render the toolbar.** Filtering/search swaps only `#listview`; rebuilding the card destroyed the search input on every keystroke (focus loss + broken IME composition).
- **UI copy is Chinese.** Reason strings arrive in English from the engine and are translated by `REASON_RULES` (regex → Chinese template, `$1`/`$2` substitution); unmatched strings fall back to the original. Add a rule there whenever the engine gains a new reason template.
- **Settings are schema-driven.** `SETTINGS_SCHEMA` describes groups/fields; `flatConfig()` maps config ↔ form, with `ba_*` ids nested into `build_artifacts`. Adding a config key means adding a schema entry, not new markup.
- **Transient feedback goes to the toast**, not the status line inside the collapsible settings panel (which the user may never open).
- Guard optional browser APIs (`fetch`, `navigator.clipboard`) with `typeof` checks — the page must degrade quietly instead of throwing.

If the runtime fails to boot, the page must show a visible diagnostic instead of silently removing `x-cloak` and leaving inert `<template>` blocks.

## Project hygiene (项目内结构整理)

Beyond disk-level cache cleanup, this skill also handles **in-project hygiene** — tidying scattered files, removing stale artifacts, and normalizing directory structure within a single project root.

### When to trigger

- User says "整理项目", "清理项目内文件", "规范目录结构", "项目内散文件", or names a specific project for cleanup.
- After a disk-level scan reveals a project with many empty dirs, scattered scripts, or AI IDE residue.

### Scan checklist

Run a Python or shell pass over the project tree to find:

| Category | What to look for | Action |
|---|---|---|
| **Empty directories** | `find . -type d -empty` | Delete |
| **macOS metadata** | `.DS_Store` files | Delete |
| **Backup files** | `*.bak`, `*.backup`, `*.orig`, `*.swp` | Delete |
| **Git keepers** | `.gitkeep` in dirs that now have content | Delete |
| **AI IDE residue** | `.agents/`, `.claude/`, `.iflow/`, `.opencode/`, `.superpowers/`, `.workflow/` | Delete (these are per-AI-tool work dirs, not project code) |
| **Tool lock files** | `skills-lock.json`, etc. when the tool is uninstalled | Delete |
| **Scattered scripts** | `migrate_*.py`, `fix_*.py`, `init_*.py` in project root or `apps/api/` root | Move to `scripts/` |
| **Scattered tests** | `test_*.py` in project root or `apps/api/` root when a `tests/` dir exists | Move to `tests/` |
| **Redundant docs** | `README_LAN.md`, `LAN_ACCESS.md` duplicating `README.md` | Merge into `README.md`, delete originals |
| **Config in wrong place** | `playwright.config.ts` in root when tests live in `tests/` | Move to `tests/` |

### Rules

1. **Git-aware moves**: prefer `git mv` over plain `mv` to preserve history. Fall back to `mv` if the file is untracked.
2. **Git-aware deletes**: use `git rm` for tracked files, plain `rm` for untracked junk.
3. **Never touch**: `.git/`, `.gitignore`, source code, database files (`.db`), lockfiles (`pnpm-lock.yaml`, `package-lock.json`, `Cargo.lock`), `.env.example` files, or anything the user explicitly wants to keep.
4. **Merge before delete**: for redundant docs (e.g. `README_LAN.md`), always merge content into the primary doc first. Never delete without merging.
5. **Idempotent**: re-running on an already-tidy project should be a no-op (no errors, no moves).

### Suggested directory conventions

For a typical monorepo project:

```
project/
├── README.md              ← single source of truth
├── CHANGELOG.md
├── package.json / pyproject.toml
├── docker-compose.*.yml
├── start-*.command / start-*.sh   ← launch scripts
├── apps/
│   ├── web/               ← frontend
│   └── api/               ← backend
│       ├── src/           ← source code
│       ├── scripts/       ← migrate, fix, init, verify scripts
│       └── tests/         ← test files
├── scripts/               ← project-level scripts (NAS, CI, etc.)
├── tests/                 ← integration/e2e tests
├── data/                  ← runtime data (DB, caches)
└── docs/ or <name>-docs/  ← documentation site
```

### Post-cleanup verification

After reorganizing, verify:
- No empty directories remain: `find . -type d -empty -not -path './.git/*'`
- No `.DS_Store` left: `find . -name '.DS_Store'`
- Git status is clean or only shows expected renames: `git status`

## Docker / OrbStack (never blind-prune)

Container runtimes hide tens of GB in images, build cache, and volumes, but their own prune commands are the most dangerous thing in this document — several of them delete **running services**, not caches.

**Never run:**

- `docker container prune` — removes stopped containers, including service containers that simply are not running right now. A stopped `n8n` container is a service, not junk: `docker start <name>` it, never prune it.
- `docker volume prune` — deletes volumes no *running* container claims. Business data sitting in a mounted-but-idle volume (e.g. OrbStack's `bwvault-data`) is indistinguishable from garbage to this command.
- `docker system prune -a` — everything above, plus every unused image.

**Safe sequence:**

```bash
docker system df            # what is actually reclaimable, first
docker image prune          # dangling images only (no -a)
docker builder prune        # build cache only
docker image rm <id>        # remove one specific known-stale image
```

**Where the bytes live depends on the host:**

- **This Mac (OrbStack)** — driven from the host, so `docker` works normally. Keep business data volumes out of every prune. Inspect volumes by name before deciding anything: `docker volume ls` then `docker volume inspect <name>`.
- **NAS (`tyconfn`)** — the Docker root lives on `/vol1` (≈900G), **not** the ≈20G system disk. A "disk full" alert is a `/vol1` question, so do not troubleshoot the system volume. Reach it over SSH rather than from this Mac's Docker context, and confirm what a container does before touching it.

Docker sits deliberately outside the scan's candidate model: this Skill reports and removes *files*, and these are runtime objects. Treat the commands above as a human-confirmed, host-specific step, and always bracket them with `docker system df`.

## Useful follow-up checks

If the script reports large skipped targets, inspect manually before deleting:

```bash
ncdu ~
ncdu ~/Library/Caches
ncdu ~/Library/Logs
ncdu ~/.cache
```
