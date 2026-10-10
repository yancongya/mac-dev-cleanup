---
name: mac-dev-cleanup
description: Scan, analyze, configure, and safely clean macOS developer caches with a local web control panel, JSON policy, recoverable Trash-first cleanup, operation logs, exclusions, test artifacts, build outputs, node_modules, virtualenvs, Tauri/Vite build by-products (src-tauri/target, gen schemas, dist-ssr, vite timestamp configs), Playwright traces, Rust/Flutter caches, Blender asset/render caches, app caches/logs, screenshot and screen-recorder app caches inside Application Support (PixPin recording recovery, screenshot history), WeChat caches and expired chat media (month-window), screenshots, and large-file review. Use whenever the user asks to clean or inspect Mac storage, caches, developer artifacts, Tauri/Rust build outputs, Blender caches, screenshot or screen-recorder caches, WeChat caches, temp files, logs, stale projects, or manage cleanup settings and reports. Route all NAS Docker operations to Agent Ops.
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
- Cleanup with `--apply` only moves eligible candidates into the recoverable quarantine and writes an operation manifest. **Do not empty Trash automatically after cleanup.** Emptying is a separate irreversible action and requires the user's explicit request plus the dashboard's literal `EMPTY TRASH` confirmation and API token; it preserves the cleanup quarantine by default.
- If Finder automation is blocked, leave the quarantine intact and report that disk space has not been reclaimed. Do not use `rm`, `shutil.rmtree`, or another deletion fallback against the quarantine: that destroys the restore path. A read-only probe such as `osascript -e 'tell application "Finder" to get name of startup disk'` can distinguish a TCC denial from a timeout; grant automation access only if the user wants Finder-controlled Trash emptying.
- **Judge an emptied Trash by `du`, never by the quarantine directory disappearing.** A successful empty leaves the (now empty) `~/.Trash/mac-dev-cleanup/` shell in place, so a polling loop that waits for the directory to vanish always burns its full timeout and then reports a failure that never happened (600 s wasted on an already-empty Trash). Poll `du -sk ~/.Trash/mac-dev-cleanup` until it reads `0`, and only then report the reclaim as confirmed.
- The local HTTP API may read state/config, atomically save validated config, trigger scan, and execute **per-candidate cleanup** (`POST /api/clean`). Cleanup via HTTP is token-guarded and constrained: every POST requires an `X-MDC-Token` header whose random value is regenerated at each server start and only served same-origin via `/api/health` (no CORS headers are ever sent, and cross-origin custom headers require a preflight this server never answers — so a malicious website can neither read the token nor fire a valid request). `/api/clean` accepts only `clean-safe`/`clean-aggressive` plus validated candidate-id lists (no arbitrary paths), and it shells out to the same CLI the terminal uses, so all built-in guards (WeChat running, `require_quit` apps, path pruning) apply unchanged and results are quarantine-only/restorable. The dashboard UI adds a two-click confirm ("确认执行？再次点击") before sending.
- **App uninstall (`apps` / `uninstall --app-name "Foo.app" --apply`)** lists installed .app bundles (plus per-app `~/Library` leftovers: Application Support, Caches, Preferences, Containers, Group Containers, HTTPStorages, Saved Application State, WebKit, Logs) with sizes in `apps.json`, and uninstalls by quarantining the bundle + leftovers into a standard operation (restorable via `--restore`). Guardrails: bundle must resolve directly under `/Applications` or `~/Applications` (traversal structurally refused), a running app is refused (exit 1), everything is move-to-quarantine — never `rm`. The dashboard 应用 view wraps this with the same token/two-click-confirm model (`POST /api/uninstall`, name-validated; listing built asynchronously via `GET /api/apps`). The view shows stat cards (count / total size / apps with leftovers / running), search by name or bundle id, sort by size / name / leftovers-first, and real app icons via `GET /api/app/icon?name=<exact name from apps.json>` — the server extracts `Contents/Resources/*.icns` with `sips` into `~/.codex/logs/mac-dev-cleanup/icon-cache/` (cache key = md5 of the bundle path, refreshed when the icns is newer) and serves it as PNG; the bundle path always comes from the scan state, never from the request, so there is no traversal surface, and a 404 makes the UI fall back to a letter avatar.

## Install layout (repository source + SkillDo-managed copy)

The Git repository is the sole editable source. Build the generated, Git-tracked Skill bundle at `skills/mac-dev-cleanup/` from the repository root, then use SkillDo to materialize it as the central Skill directory. Do not edit the generated bundle directly. SkillDo points each AI tool at that installed directory with symlinks:

```
mac-dev-cleanup/SKILL.md                     <- authoritative source
mac-dev-cleanup/skills/mac-dev-cleanup/      <- generated, Git-tracked Skill bundle
~/.skillshub/mac-dev-cleanup                 <- SkillDo-installed bundle
~/.codex/skills/mac-dev-cleanup              -> symlink to it
~/.claude/skills/mac-dev-cleanup             -> symlink to it
~/.config/mimocode/skills/mac-dev-cleanup    -> symlink to it
~/.workbuddy/skills/mac-dev-cleanup          -> symlink to it
~/Desktop/OH-WorkSpace/.agents/skills/mac-dev-cleanup -> symlink to it
```

Build and update after editing:

- Edit the repository root files, then run `python3 scripts/build_skilldo_package.py build`. This deterministically projects the Skill and its required runtime/support files into `skills/mac-dev-cleanup/`; it excludes Git data, machine policy/state/history, generated dashboard data, and dependencies.
- Register or repoint the local copy with `skilldo track-local --skill mac-dev-cleanup --path skills/mac-dev-cleanup --yes`, then run `skilldo update --skill mac-dev-cleanup --yes`. This local registration keeps the GitHub URL as provenance, but is not yet a portable Git source. After this subtree is committed and exists on GitHub, use `skilldo repair source --skill mac-dev-cleanup --url https://github.com/yancongya/mac-dev-cleanup.git --subpath skills/mac-dev-cleanup --apply` to register the cross-device Git source. Do not force that repair before the remote subtree exists.
- Do not edit the central copy or use `skilldo push` for this locally tracked source. Publish repository changes through the repository's normal Git review process; `skilldo update` only materializes the already-built local bundle.
- **`skilldo update` replaces the active central directory with the bundle's content.** The current CLI first stages the bundle, then renames the old center to a recoverable sibling named `~/.skillshub/.skilldo-old-<uuid>` before installing the new center. On failure it restores the old center; after success the sibling remains available for recovery. Local-only files are therefore absent from the active Skill until restored or regenerated. Older update paths were observed to delete loose files and symlinks; don't rely on an in-place merge.

  After updating, restore the notes link. The scan state and file dashboard now live outside the installed Skill, so an update does not erase them or require a rescan. If the persistent web server was already running, restart it so it loads the updated bundled code.

  ```bash
  ln -sfn ~/.codex/logs/mac-dev-cleanup/.workbuddy ~/.skillshub/mac-dev-cleanup/.workbuddy
  ```

  Tracked bundle files come back byte-for-byte. The private dashboard directory and current scan state remain in place.

  Everything that must survive therefore lives *outside* the installed Skill directory:
  - policy → `~/.codex/logs/mac-dev-cleanup/config.json` (the script's `CONFIG_PATH`)
  - state, history, reports → `~/.codex/logs/mac-dev-cleanup/`
  - private `file://` dashboard and its data scripts → `~/.codex/logs/mac-dev-cleanup/dashboard/` (directory mode 0700; files mode 0600)
  - this Skill's own notes → `~/.codex/logs/mac-dev-cleanup/.workbuddy/`, symlinked in
- **CLI `update` respects symlink targets** (fixed 2026-09-23 in SkillDo, `src-tauri/src/core/installer.rs`). The CLI path used to re-sync *all* targets through `sync_dir_copy_with_overwrite` regardless of the recorded mode, so one `skilldo update` silently turned these five symlinks into five independent copies — and it left the database still claiming `mode=symlink`, so `skilldo list` reported a link that was no longer there. It now skips any target that is already a correct link, re-materialises copy targets (plus Cursor, which cannot use symlinks), and repairs a link that is missing or pointing elsewhere — the same semantics the GUI path always had. On a SkillDo build older than that fix, restore the layout by hand:

  ```bash
  for t in codex claude_code mimocode workbuddy "custom:$HOME/Desktop/OH-WorkSpace/.agents/skills"; do
    skilldo sync --skill mac-dev-cleanup --tool "$t"
  done
  ```

  `skilldo push` never touches targets at all.
- `.gitignore` retains exclusions for legacy machine-local `config.json`, `state.json`, `config_data.js`, `dashboard_data.js`, and `dashboard.html` files at the repository root. Current scans write dashboard artifacts only under `~/.codex/logs/mac-dev-cleanup/dashboard/`; none belong in the repository or installed Skill. It also excludes `*.bak.*`, `__pycache__/`, `.workbuddy` (written without a trailing slash — the slash form matches directories only and would let the *symlink* be committed with a local absolute path inside), and the deprecated `vendor/`.

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
- **Both moved it, yet an earlier deletion never showed up** → the counter is healthy, so you have a *concurrent consumer*, not a failed delete: the freed blocks were re-allocated by something else on the volume while you worked. Do not delete a second time. Look for the writer with `ps -A -o pid,%cpu,rss,etime,comm | sort -k2 -nr | head`, and remember that these grow silently: sparse virtual-machine disk images (`*.img.raw`; check real usage with `du`, not `ls`, since the apparent size can be hundreds of GB), the APFS swap volume (`diskutil apfs list` → role `VM`), and always-on monitor history databases (iStat Menus `history.db` ≈ 250 MB).

Also test **both file shapes** — one big file and a few thousand small files can behave differently, and a Cargo `target/` tree is the second shape:

```bash
# many-small-files shape (matches a Rust/Cargo target/ tree)
mkdir -p /tmp/__manytest__
for i in $(seq 1 2000); do dd if=/dev/zero of=/tmp/__manytest__/f$i bs=1m count=1 2>/dev/null; done
# then df -k, rm -rf /tmp/__manytest__, df -k again
```

After an `--apply`, the operation remains recoverable in quarantine. Do not claim disk space was reclaimed until the user separately empties Trash through the explicitly gated system-Trash action; then verify with `du -sh ~/.Trash/mac-dev-cleanup`, `diskutil apfs list`, and, when APFS snapshots hold space, a post-reboot `df -h ~` check.

Field-tested 2026-07-31: two cleanup rounds deleted 14.6G but `df` before/after stayed at 100% full (~590M free); after reboot, used dropped 185Gi→160Gi and available jumped 590Mi→44Gi with all `com.apple.os.update-*` snapshots gone.

Field-tested 2026-09-23, *same machine, two sessions with opposite results*:
- 12:xx — 8.2G removed with `du` back to zero, yet `df -k` never moved; a 512M control write moved it by <1M and the delete moved it not at all → frozen counter plus a pending update, not a failed delete.
- 14:xx — 4.87G of Cargo `target/` removed (`du` 5.1G → 233M, file listing confirmed) and `df` again did not move, **but both control shapes moved the counter exactly in both directions**. The counter was healthy, so the freed blocks had been re-allocated elsewhere; no second deletion was warranted.

The lesson: the same machine can present a stuck counter in one session and a healthy one in the next (a reboot or a completed update resets it). Always run the control experiment instead of assuming, and read "healthy counter + unchanged free space" as *someone else is writing* — never as *the cleanup failed*.

## Risk levels

| risk | behavior | examples |
|---|---|---|
| `safe` | deleted by `clean-safe` and `clean-aggressive` (with `--apply`) | `__pycache__`, pip/npm/uv cache, playwright temp, project logs, coverage, `app-support-cache`, Xcode/swiftpm caches, Homebrew downloads, pnpm/go stores, browser profile caches (Code Cache/GPUCache/shader caches, browser not running) |
| `aggressive` | deleted only by `clean-aggressive` (with `--apply`) | `node_modules`, `.venv`, `build`, `dist`, Codex/Trae caches, large app caches/logs, `stale-deps`, `wechat-cache`, `wechat-media`, Xcode DerivedData/DeviceSupport, go mod, conda pkgs, superseded Claude Code versions, browser on-device AI model stores |
| `manual` | never auto-deleted; shown in report as "needs review" | screenshots, large dirs, archives, dumps, large personal files, `stale-model`, `app-support-manual`, Xcode Archives & simulator Devices, ollama models, `orphan`, `large-files`, `installer`, `ios-backup` |

Cleaning `aggressive` is not automatically worth it: **updater/runtime caches are deleted and re-downloaded the same day**, so a pass over them costs bandwidth and changes nothing. Field-observed 2026-09-22: an aggressive run removed `~/.cache/codex-runtimes` (1.6G), `hanako-updater` (437M) and `com.google.antigravity` (352M), and all three were back within hours. Spend aggressive effort on build output (`target`, `build`, `dist`, `.venv`, `node_modules`) instead, and leave self-updating runtime caches alone unless space is genuinely critical.

## Categories recognized

`global-cache`, `app-cache`, `app-log`, `app-support-cache`, `app-support-manual`, `project-generated`, `log-file`, `temp-browser`, `temp-file`, `test-artifact`, `screenshot`, `large-dir`, `large-file`, `large-files`, `stale-deps`, `stale-model`, `wechat-cache`, `wechat-media`, `xcode`, `dev-cache`, `ai-cache`, `orphan`, `browser-cache`, `installer`, `ios-backup`

## P0 expansion (2026-09-27): Xcode / dev caches / AI caches / orphans

- **`xcode`**: DerivedData, iOS/tvOS/watchOS/macOS DeviceSupport, XCTestDevices (aggressive); `com.apple.dt.Xcode` cache, CoreSimulator Caches, swiftpm, Previews (safe); **Archives and CoreSimulator/Devices are manual** — release dSYMs and simulator state are unrecoverable. The whole category is skipped while Xcode runs (deleting build state under a live IDE corrupts it).
- **`dev-cache`**: Homebrew downloads + build logs, pnpm store, go mod download cache, mise (safe); go mod tree, conda pkgs (aggressive). Gradle/go paths are skipped while `GradleDaemon`/`go`/`gopls` processes are live (deleting a store mid-build breaks the build).
- **`ai-cache`**: ollama/LM Studio logs (safe), ollama web cache (aggressive), **ollama models are manual** (re-download = gigabytes). Claude Code: `~/.local/share/claude/versions` children are semver-sorted and only superseded versions are flagged aggressive — the newest is always kept.
- **`orphan`**: reverse scan of volatile Library roots only (`Caches`, `Logs`, `Saved Application State`, `HTTPStorages`, `WebKit`) — first-level entries whose normalized name matches no installed app identifier (bundle id or app name, both directions, ≥5 chars). Skips: `com.apple.*`, Apple services without the prefix (GeoServices/PassKit/Animoji/…), dev-tool cache names (bun/gradle/…), pure-UUID dirs, entries < 1 MB. Always `manual`. Identifiers come from `apps.json` when present, else a live `/Applications` scan.
- **Security hardening shipped with the same change**: `IMMUNE_PATHS` (`.ssh/.aws/.gnupg/.kube/.docker`, `Library/Keychains|Cookies|Mail`) are excluded by code regardless of config — never proposed, never quarantined; both quarantine paths re-stat the target right before `shutil.move` and refuse on device/inode mismatch (TOCTOU guard, parity with PureMac).

## P1 expansion (2026-09-27): large files / trash management / treemap

- **`large-files`** (read-only inventory, OmniDiskSweeper-style): individual files inside the configured scan roots that are **> 100 MB at any age** (`large-file`) or **> 10 MB untouched for > 12 months** (`old-large-file`). Always `manual` — no clean mode ever auto-selects them; removal happens only via an explicit dashboard checkbox and lands in the restorable quarantine. Files already covered by an earlier pass (inside DerivedData, a dev cache, …) keep the more specific label and are not double-reported; symlinks are never flagged; capped at the 200 largest. Verified first real run: 10 files / 2.1 GB, all genuine targets (`.git` packfiles, `node_modules` binaries, an old font).
- **System trash management**: `GET /api/trash` now returns `quarantine` + `system` blocks (legacy top-level keys kept). `system` lists `~/.Trash` contents (name/size/mtime, top 100 by size) **excluding** the quarantine dir, which stays restorable. `POST /api/trash/empty-system` requires the literal body `{"confirm": "EMPTY TRASH"}`; by default the quarantine area is preserved (`include_quarantine: true` overrides). This is a real deletion, not quarantine — Trash contents are already discarded data. `~/.Trash` is TCC-protected: when the serving context lacks permission the endpoint degrades to `"available": false` instead of erroring, and the dashboard explains the fix (grant Full Disk Access to the serving context).
- **Dashboard treemap**: overview gained a squarified treemap of category totals (top 12 + "other"), pure SVG, no new dependencies, theme-aware.

## P1 batch 2 (2026-09-27): browser caches / installer sweep / iOS backups

- **`browser-cache`** (Mole browser parity): Chromium/Firefox profile caches under `~/Library/Application Support` — the one place the wholesale App Support prune made them invisible (`~/Library/Caches/<Browser>` is already covered by `app-cache`). Only exact subdir names are ever proposed: profile-level `Application Cache`/`Code Cache`/`GPUCache`/`DawnCache`/`GrShaderCache`/`GraphiteDawnCache`/`Crashpad/completed`, root-level `ShaderCache`/`component_crx_cache`/`extensions_crx_cache` (safe); Chrome `OptGuideOnDeviceModel`/`OptGuideOnDeviceClassifierModel`/`optimization_guide_model_store` are **aggressive** (may re-download gigabytes). **Service Worker CacheStorage/ScriptCache is never touched** — that is site data, not cache. A browser that is running skips its whole group (`pgrep -x`). Chrome/Edge/Brave/Vivaldi/Arc covered; Edge/Vivaldi share the Chromium layout.
- **`installer`** (Mole installer parity, scoped): leftover `.dmg/.pkg/.mpkg/.iso/.xip` in `~/Downloads` (depth 2, `find -maxdepth` semantics) plus ZIPs whose first 50 entries contain an `.app/.pkg/.dmg/.xip` payload (pure-Python `zipfile` check, no subprocess). Mole also walks Desktop/Documents/Public/Shared/iCloud — deliberately scoped out to keep the personal-file surface minimal. Always `manual`.
- **`ios-backup`**: read-only inventory of `~/Library/Application Support/MobileSync/Backup/<UDID>` — a full device restore point, always `manual`. MobileSync is TCC-protected: when the listing raises, the category degrades to absent instead of aborting the scan (same degradation as the web panel's trash API).

## P2 reports (2026-09-27): duplicates / launch items / TM snapshots

- **`dupes` subcommand** (also served at `GET /api/dupes`, background-built on first access, `POST /api/dupes/refresh`): progressive duplicate detection — exact size → 64 KB head SHA-256 → full SHA-256; hard links (same device+inode) count once; `.git` skipped (content-addressed churn, not actionable); default roots are the configured scan roots (`--roots` repeatable), default threshold 10 MB (`--min-size` bytes). Writes `~/.codex/logs/mac-dev-cleanup/dupes.json` (groups with `wasted = size × (copies − 1)`, capped at 200, wasted-desc) and prints the top 20. Report-only by design: choosing which copy to keep is a human call. First real run: 25 groups / **2.1 GB** wasted (a backup tree keeping the same .blend ×5).
- **Launch items and local services** (`GET /api/launch`, `/api/services`): inventory reports third-party LaunchAgents/LaunchDaemons; system-scope jobs remain read-only. Exact user LaunchAgents can be registered in a local mode-0600 allowlist and then started/stopped for the current GUI session or enabled/disabled for future logins from the dashboard. Each mutation is confirmation- and API-token-gated; the backend uses fixed `launchctl` argument arrays and revalidates the registered plist label/path. Terminal-hosted services can be added as user LaunchAgents with an absolute executable, JSON argument array, and optional working directory. `local_login_items_cli.py list` reads traditional “Open at Login” entries through System Events in the interactive terminal; use `local_login_items_cli.py refresh` to save a private mode-0600 snapshot for the dashboard. `GET /api/login-items` reads that snapshot only; the LaunchAgent does not invoke Apple Events because it cannot reliably show an interactive macOS Automation prompt. If the first terminal read is denied, allow the terminal app to control System Events under System Settings → Privacy & Security → Automation, then retry. Arbitrary third-party app registrations cannot be toggled through the public `SMAppService` API, so use System Settings for changes. Application removal remains a separate workflow. Never create a scheduled cleanup job that automatically empties Trash or clears the recoverable quarantine.
- **TM local snapshots** (`GET /api/snapshots`, `POST /api/snapshot/delete`): `tmutil listlocalsnapshots /System/Volumes/Data` parsed, header line ignored. Deletion accepts ONLY strict date-format names (`YYYY-MM-DD-HHMMSS`) plus the literal confirm string `DELETE SNAPSHOT` — `com.apple.os.update-*` rollback points never match the pattern and are refused by code; only a reboot installing the update may reclaim them. Remind users: snapshot space may not show in `df` until the update installs.

## Scheduled execution (2026-09-28): cron-managed 计划任务 tab

- **Dashboard 计划任务 view** (`GET/POST /api/schedule`): configure unattended runs from the panel. Two schedulable jobs only — `scan` (weekly, weekday selectable) and `clean-safe` (daily HH:MM, runs with `--apply`). **`clean-aggressive` is deliberately not schedulable** (400 from the API): aggressive cleanup removes rebuild-costly trees (`node_modules`, virtualenvs) and requires per-candidate human confirmation.
- **Crontab coexistence contract**: only lines carrying a trailing `# mdc-managed:<job>` marker are ever read or rewritten; the rest of the user's crontab is untouched. A disabled job stays in the crontab as a commented line, so the configured time survives a toggle. Pure functions `build_managed_cron_line` / `parse_managed_crontab` (round-trip tested) live in the CLI module; the web layer only shells out to `/usr/bin/crontab -l` / `crontab -`. Logs append to `~/.codex/logs/mac-dev-cleanup/cron-<job>.log`. A serving context without crontab access degrades to `crontab_available: false` and the panel disables its controls with an explanation.

## Apps-listing self-healing (2026-09-28)

- Uninstalling an app used to leave it in the dashboard listing forever (and its icon-cache PNG on disk): a present-but-stale `apps.json` short-circuited the rebuild path, and the `force` flag from the front end had no backend effect. Now `prune_stale_app_records()` (a) drops the uninstalled app's record and its md5-keyed icon-cache PNG right after a successful `--apply` uninstall, (b) runs on every `GET /api/apps` so externally deleted bundles self-heal, and (c) `prune_orphan_icons()` sweeps icon-cache PNGs whose bundle left apps.json after every rebuild.

## Explicitly managed user LaunchAgents (2026-10-10)

- The System view lists third-party LaunchAgents and LaunchDaemons. System-scope entries remain read-only. A user LaunchAgent can be managed only after its exact plist Label is registered in the local allowlist at `~/.codex/logs/mac-dev-cleanup/managed-services.json` (mode 0600). Registration records the canonical plist path and does not start the service or change login behavior.
- Dashboard controls are separate: start/stop affects the current GUI session; enable/disable affects future login behavior and disabling does not stop a running service. Every change requires confirmation and the local API token. The backend constructs fixed `launchctl` argv and revalidates the plist/Label on every operation; callers cannot supply a path or shell command.
- A terminal service can be added from the panel with an absolute executable path, a JSON string array of arguments, and an optional working directory. This writes a mode-0600 LaunchAgent plist plus the local allowlist; it does not start the service immediately. If the same service is already running in a terminal, stop that copy first to avoid a duplicate. Do not put credentials in arguments; retrieve secrets through BWVault-backed service wrappers.
- After `skilldo update`, old center-local dashboard copies are discarded with the replaced Skill directory. The private file dashboard and scan state under `~/.codex/logs/mac-dev-cleanup/` persist; the local server serves the bundled template and hydrates from the existing state API without a rescan.
- The app-login inventory covers the traditional “Open at Login” list exposed by System Events. It does not include App Background Activity or extensions. No public API lets this unrelated dashboard safely toggle another app's login registration; users change individual entries in System Settings > General > Login Items & Extensions. App uninstall remains separate. Tests mock System Events and launchctl; they must never change host login or service state.

## LaunchAgent service + one-click restore (2026-09-28)

- **`service --service-action install|uninstall|status`**: writes `~/Library/LaunchAgents/com.yancongya.mac-dev-cleanup.plist` (RunAtLoad + KeepAlive, system `/usr/bin/python3`, logs under `LOG_DIR/service/`). `launchctl bootstrap` **from IDE/agent host contexts is refused by macOS with "Input/output error" (5)** — even for minimal valid plists; only a real Terminal login shell can load it. The installer therefore writes the plist, verifies the load, and prints the exact Terminal command when refused. `~/.Trash`, `MobileSync`, Safari caches and the dashboard schedule tab all need this persistent, FDA-granted context.
- **`bootstrap` error 5 is ambiguous — two distinct causes**: (a) host-context refusal (see above), (b) **the service was already loaded** (e.g. by an earlier `launchctl load -w`, which can "fail" with rc=0 yet still register the label). Before re-running bootstrap in Terminal, always check `launchctl print gui/<uid>/com.yancongya.mac-dev-cleanup` first: if it prints a job dict the service IS loaded — bootstrap is unnecessary and re-running it just reproduces the misleading error 5. Then `launchctl kickstart -k` to (re)start.
- **Port conflict crash-loop**: if another process already listens on the dashboard port, the launchd service hits `OSError 48 Address already in use` on every spawn (visible in `LOG_DIR/service/err.log`) and KeepAlive restarts it forever. The squatter is usually either a leftover **session-spawned `web_server.py`** or — more insidiously — an **orphan of this very service**: a process that `launchctl bootout` failed to kill (e.g. while the P0 test bug was silently unloading the production service) and that launchd has since lost track of, so it keeps the port and never dies on its own. Either way the dashboard still responds HTTP 200 (from the squatter!), masking the failure — and if the squatter is a pre-FDA process, `GET /api/trash` returns `available: false`, which looks exactly like a lost FDA grant but is **not**. Diagnose with `lsof -nP -i :<port>`: the launchd-owned process shows as `Python` (system interpreter). Kill the squatter (`kill <pid>` — a same-uid signal works), then **if launchd does not auto-take-over, force it**: `launchctl kickstart -k gui/$(id -u)/com.yancongya.mac-dev-cleanup`. Do NOT assume the auto-takeover — verify the port is now held by a fresh `Python` process and `/api/trash` reads `available: true`.

## Dashboard IA reorganization (2026-09-29, staged)

- **7 → 6 tabs**: 概览（纯只读仪表盘，勾选/执行入口全部移除，预览行只跳转）/ 清理（唯一执行域：「整模式清理」面板明确标注忽略勾选 + 按勾选精确清理 + 重复文件，报告→行动闭环）/ 系统（应用卸载 + 启动项 + TM 快照，原「应用」与「报告」合并）/ 还原（操作与看板执行记录合并为统一时间线，来源标注「看板执行」，废纸篓面板随附）/ 计划任务 / 设置（含工具自检）。原独立「报告」tab 撤销。
- **P0 semantics fixed**: POST `/api/trash/clear` now requires the literal confirm `"CLEAR QUARANTINE"` (clearing the quarantine destroys every restorable operation — the UI modal says so with actual counts); the shared confirm layer `#app-confirm` replaces the last native `confirm()`; irreversible modals (system trash / snapshots) carry a「不可恢复」badge.
- **State polish**: candidate selection persists in `localStorage` (`mdc.selection.v1`, re-validated against the inventory on boot); `refreshAfterClean` re-polls on `state.timestamp` change (2 s × 15) instead of a fixed 6 s sleep; the service/FDA degradation guidance renders once in a global `#svc-banner` (panels keep only local disabled notes).
- **Gate sync**: `check_dashboard_dom.mjs` rewritten alongside each stage (105 assertions); `npm test` runs the engine/export unit suites and Skill routing check. Run both the unit and DOM gates after dashboard template changes.

## FDA grant for the service interpreter (2026-09-29, verified on this machine)

- **TCC attributes the grant to the executable that actually runs, not the shim.** The plist's `/usr/bin/python3` is an 118 KB xcode-select stub that execs the CLT interpreter; the running process's real identity is `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9`. Granting FDA to `/usr/bin/python3` (or the symlink `.../CommandLineTools/usr/bin/python3`) has **zero effect** — the dashboard keeps showing 未授权 and `/api/trash` keeps returning `available: false`.
- **The FDA "+" picker greys out `python3.9`** — Launch Services misparses the trailing `.9` as a file extension and classifies the binary as a document; `Cmd+Shift+G` in the picker also refuses to jump into hidden paths or follow symlinks. **The only reliable method**: in Finder press `Cmd+Shift+G`, enter the framework `bin/` directory above, then **drag the `python3.9` file directly onto the Full Disk Access list** in System Settings and toggle it on. Never route the drag through a drag-shelf utility (Yoink, Dropover, …) — that attaches `com.apple.quarantine` and the service then gets SIGKILLed on every spawn.
- **CLT upgrades silently revoke the grant** (TCC matches the ad-hoc-signed binary at its exact path). Symptom: trash/crontab flip back to 未授权 after an Xcode CLT update — repeat the Finder drag once.
- Verification after granting + `launchctl kickstart -k`: `GET /api/trash` → `system.available: true`; `GET /api/schedule` → `crontab_available: true`; a full rescan then surfaces Safari-cache and iOS-backup candidates in the dashboard.
- **Diagnosing `available: false` — two distinct causes, do not conflate**:
  1. **The serving process has no FDA** (the crash-loop squatter above): the *currently running* process was started before the grant (or is the orphan), so it cannot read `~/.Trash` even though the grant itself is valid. **Fix: `kill` the squatter + `launchctl kickstart -k`** — a freshly spawned process inherits the grant and `available` flips to `true`.
  2. **The grant itself was revoked** (CLT upgrade): even a fresh process cannot read `~/.Trash`. **Fix: repeat the Finder drag**, then `kickstart -k`.
  - **How to tell which**: after `kickstart -k`, a *new* process reading `available: true` ⇒ cause 1 (grant was fine); still `false` ⇒ cause 2 (grant gone).
  - **⚠️ Never probe FDA from a restricted agent/Bash shell.** The WorkBuddy/IDE Bash tool runs *without* FDA of its own (`ps` and `launchctl list` are denied there), so a child `python3 -c "os.listdir('~/.Trash')"` returns `PermissionError` regardless of whether the grant is valid — a false negative that misdiagnoses a healthy grant as revoked. Always verify through the *service* endpoint (`GET /api/trash` `available`), never by `stat`ing `~/.Trash` from the agent shell.
- **One-click restore**: `POST /api/operations/restore` (id regex-gated, 404 on unknown ids) wraps the CLI `--restore`; the operations panel lists file previews (`original_path` — note the manifest key is NOT `path`) with a two-click armed restore button.
- **State-integrity guard (root cause of "everything went empty")**: the dashboard's clean runs use `--candidate-id` filters against a possibly stale inventory. When the ids no longer match (e.g. the nightly job cleaned them first), collect() returns empty and `write_state` would overwrite the good inventory with 0 candidates — collapsing the whole dashboard. Filtered runs now **never** write `state.json` (zero-match case prints a warning and leaves state untouched); the web server fires a full `scan --limit 0` after every applied clean to refresh the inventory, and the UI re-polls state after 6 s.

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

Hard rule: while WeChat is running, `opendir()` into the sandboxed container **blocks indefinitely** (kernel-level wait, not EPERM) — field-tested 2026-09-24, the nightly `clean-safe --apply` hung 7.5 h in `collect()` this way because WeChat had been left running overnight. So **both** phases skip WeChat while it runs: `scan_wechat()` returns no candidates (the scan/walk phase never touches the container), and `--apply` reports `skipped: WeChat is running`. Quit WeChat and re-run. Note the nightly `clean-safe` automation never touches WeChat anyway — both categories are aggressive-only.

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
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py scan --summary-json /tmp/mac-cleanup-summary.json
```

Safe dry run:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-safe
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-safe --summary-json /tmp/mac-cleanup-summary.json
```

`--summary-json PATH` exports a versioned, path-free summary for `scan` or a cleanup dry-run. It contains aggregate counts and byte totals only; candidate paths, reasons, IDs, project names, and configuration are omitted. The flag is rejected with `--apply`.

To export the **latest already-saved scan** without scanning, cleaning, or loading policy, use the separate read-only helper:

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/export_summary.py --output /path/to/mac-cleanup-summary.json
```

It reads only the saved state file and projects the exact `mac-dev-cleanup.summary.v1` allowlist: `schema`, `timestamp`, `mode`, `apply`, `candidateCount`, `riskCounts` (`safe`, `aggressive`, `manual`), `safeBytes`, `aggressiveBytes`, `manualBytes`, and `selectedBytes`. It requires `apply: false`, a timezone-aware non-future timestamp, non-negative integer counts/totals, matching candidate/risk counts, and mode-consistent byte totals. The output is atomically written with owner-only permissions. It never emits candidate paths, IDs, reasons, config, or other source fields, and does not transmit the file anywhere.

When explicitly requested, the same saved-state allowlist can be POSTed to a user-specified HTTPS endpoint. The path must be exactly `/v1/mac/summary`; the server certificate and hostname are verified, and the request times out after 15 seconds. Only a dedicated ingest token is accepted, through stdin (first line); never pass it as an argument or print/log it. The upload command never runs a scan or cleanup:

```bash
set -o pipefail
bwvault credential get --alias mac.cleanup.ingest-token --reveal --json \
  | jq -er '.secret | strings | select(length > 0)' \
  | python3 ~/.codex/skills/mac-dev-cleanup/scripts/export_summary.py --upload --endpoint https://collector.example/v1/mac/summary --token-stdin
```

Store the dedicated token under the `mac.cleanup.ingest-token` `bwvault` alias. The pipeline extracts only `.secret` from BWVault JSON and passes it through stdin without displaying it. Stdin is bounded to 8192 token bytes. Success requires a 2xx JSON response with `schema: agent-ops-mac/v1`, `accepted: true`, and `state: stored`; otherwise a generic error is returned without echoing the response body. Plain HTTP, redirects, URL credentials, query strings, fragments, and any other path are rejected.

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

Start the Skill's loopback-only control server (any of the install paths works — they are all symlinks into the one central directory):

```bash
python3 ~/.skillshub/mac-dev-cleanup/scripts/web_server.py
```

Open:

```text
http://127.0.0.1:8766/dashboard.html
```

The port resolves as `--port` → `MDC_PORT` → `config.json: dashboard_port`, defaulting to **8766**. That default deliberately avoids 8765: it is a crowded neighbour on a developer Mac (a Codex auto-resume daemon already listens there on this machine) and a collision makes the server exit the moment it starts, which looks like the command doing nothing.

When served this way, the dashboard can:

- read the latest state and current `config.json`;
- edit thresholds, scan roots, exclusions, protected projects/categories, and retention preference;
- validate and atomically write `config.json`;
- trigger a new read-only scan and refresh the page state;
- view and clear the quarantine area, and inspect / empty the **system Trash** (`POST /api/trash/empty-system`, gated by the literal `confirm: "EMPTY TRASH"` string plus the API token — see P1 expansion above).

Opening `~/.codex/logs/mac-dev-cleanup/dashboard/dashboard.html` directly with `file://` remains supported as a read-only fallback. The HTML and its two sibling data scripts are generated together in that private directory, so the browser can load them by relative path without XHR or CORS. In that mode, config editing generates a CLI command instead of silently pretending the file was saved. The installed Skill directory contains only the template and runtime code.

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

**Mount points are also never walked.** Every traversal goes through `safe_walk()`, which prunes any directory that is an active mount point (detected by string comparison against the `mount` table, so no filesystem I/O is added). This exists because a **stale network mount hangs the entire scan forever**: a dead SMB/NFS share (e.g. `//host/share` on `/tmp/<name>` whose backing service was stopped) blocks indefinitely on the first `stat()` inside it — the process shows 0% CPU with no open directory handles and never finishes. If `scan` appears stuck with no output, run `mount | grep -E "smbfs|nfs"` and check for a dead share under a scan root (`/tmp` is a scan root). If a NAS service needs attention, use Agent Ops to inspect or restore that service; this Skill must not start or otherwise manage its Docker container. A stale local mount may be force-unmounted only as a local filesystem action. Do **not** "fix" this by patching `pruned()` — `pruned()` calls `Path.resolve()`, which stats, and would hang the same way.

The same dead mount defeats *any* recursive walk of `/tmp`, not just this Skill's: a recursive glob (`**/*`), a bare `find /tmp`, or a disk-usage tool hangs identically. Even `diskutil unmount force` can hang, because an orphaned kernel mount has no `mount_smbfs` process left to kill. If the exporting service is on the NAS, route its status and lifecycle through Agent Ops; if the mount itself is stale, use the host's local mount controls. Never probe `/tmp` recursively while a stale share is mounted.

## Dashboard and state

The page is an **app-like console with a sidebar and four hash-routed views** (`#overview` / `#clean` / `#history` / `#settings`); on narrow screens the sidebar becomes a horizontal sticky tab bar. The **overview is an app landing, not a panel stack**: a hero section (disk-usage donut + 可清理空间 headline + scan timestamp + 开始清理/重新扫描) above three tinted risk cards (安全清理 / 深度清理 / 人工确认 — clicking one jumps to the clean view pre-filtered to that risk), then a 深度清理候选 preview (top aggressive candidates by size, checkbox-selectable, sharing the same selection state as the clean view) with its own mini selection bar. Collapsible panels below hold category/disk/tools details.

Panels (the unified collapsible `panel()` shell, drag-reorderable) are grouped per view: overview holds hero + risk cards + preview + category/disk/tools, clean holds the one-click commands + candidate table, history holds the quarantine panel + operations, settings holds the config form.

The clean view's candidate list has **selection checkboxes** (manual-risk rows are disabled — that level is never auto-deleted) and a sticky bottom bar showing "已选 N 项 · X GB"; the 生成清理命令 button copies a precise `clean-safe`/`clean-aggressive` command (aggressive if any selected pick is aggressive) with one `--candidate-id <id>` per pick, so the terminal only deletes exactly what was reviewed. Selection lives in memory and is cleared when a fresh scan replaces candidate ids.

The dashboard has exactly one tracked source — the template. Every scan creates a private `file://` copy and its two machine-specific data scripts outside the SkillDo directory:

```text
~/.skillshub/mac-dev-cleanup/dashboard_template.html   # the only tracked file: design + tokens
~/.codex/logs/mac-dev-cleanup/dashboard/dashboard.html          # generated shell for file://
~/.codex/logs/mac-dev-cleanup/dashboard/dashboard_data.js       # latest scan snapshot
~/.codex/logs/mac-dev-cleanup/dashboard/config_data.js          # current policy snapshot
```

The generated HTML is byte-identical to the template and contains no machine data. Its sibling scripts contain machine-specific scan/config data and are kept in the owner-only runtime directory (0700 directory, 0600 files). The HTTP server always serves the bundle template at the existing `/dashboard.html` route; the page loads state and config through the local API.

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

The dashboard is a **single HTML file with zero third-party runtime dependencies**: no CDN, no `vendor/` libraries, no Alpine/Tailwind. It deliberately loads exactly two sibling scripts — `dashboard_data.js` and `config_data.js`. `scan()` writes all three file-dashboard artifacts under `~/.codex/logs/mac-dev-cleanup/dashboard/`, outside the SkillDo source tree. The sibling scripts carry machine-specific data (absolute paths, disk usage, per-category byte counts), so the directory is owner-only. Opening that generated HTML through `file://` loads the scripts by relative path. The HTTP route serves the data-free template instead and obtains current state/config through the API.

`write_state()` writes `state.json` and atomically replaces the two data scripts and generated HTML in the private dashboard directory. The template is read from the Skill bundle. The runtime directory is created with mode 0700 and each generated file with mode 0600. Keeping the page free of sibling-*framework* loads is still mandatory — inlined Alpine/Tailwind or CDN references are what previously caused the "仪表盘脚本加载失败" error in the WorkBuddy preview webview.

Constraints when editing the dashboard UI:
- Keep it dependency-free vanilla HTML/CSS/JS. Do NOT reintroduce Alpine, Tailwind, CDN links, or external `vendor/` scripts.
- Keep the two fallback tokens `/*__DATA__*/null` and `/*__CONFIG__*/null` in the template. The build no longer substitutes them; `check_dashboard_dom.mjs` injects `state.json` into them in memory so the headless render stays deterministic without async `file://` script loading.
- In offline (`file://`) mode the scan button and settings-save fall back to generating a CLI command / downloading `config.json`; the live POST API only activates when served by `web_server.py`.
- Validate after UI changes with a headless render (jsdom) to confirm zero runtime errors and that all sections render:

  ```bash
  python3 scripts/check_dashboard.py                     # static + syntax gate
  npm test                                               # engine/export tests + Skill routing
  npm i jsdom
  node scripts/check_dashboard_dom.mjs dashboard_template.html    # headless assertions
  # or: MDC_JSDOM=/path/to/jsdom/lib/api.js node scripts/check_dashboard_dom.mjs dashboard_template.html
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
| **Generated artifact tracked beside its source** | a build output byte-identical to its template (e.g. `dashboard.html` vs `dashboard_template.html`; prove with `shasum a b`) | Keep the source, gitignore the output — but only after `grep -rn "<outname>"` shows nothing loads it by path |
| **Unreferenced asset dirs** | `assets/`, `static/`, `media/` with zero hits for `grep -rn "assets/"` across code, docs and configs | Delete the directory; first `shasum` every file to find one whose content is unique, and relocate that one instead of losing it |

### Rules

1. **Git-aware moves**: prefer `git mv` over plain `mv` to preserve history. Fall back to `mv` if the file is untracked.
2. **Git-aware deletes**: use `git rm` for tracked files, plain `rm` for untracked junk.
3. **Never touch**: `.git/`, `.gitignore`, source code, database files (`.db`), lockfiles (`pnpm-lock.yaml`, `package-lock.json`, `Cargo.lock`), `.env.example` files, or anything the user explicitly wants to keep.
4. **Merge before delete**: for redundant docs (e.g. `README_LAN.md`), always merge content into the primary doc first. Never delete without merging.
5. **Idempotent**: re-running on an already-tidy project should be a no-op (no errors, no moves).
6. **Prove "derivative" before deleting the copy**: a file is only a derivative if its bytes are identical to its source (`shasum`) *or* a build step regenerates it — and either way, `grep` must show nobody loads it by path. Deleting a "redundant" file that something opens by name breaks the build silently. When the source/output pair is byte-identical, the output is a pure derivative: gitignore it and delete it from the repository (a plain `rm` leaves it tracked — the removal only lands when the next commit records the deletion, so on a SkillDo-managed repo the file must be absent from the central directory at `skilldo push` time).
7. **Check that the docs still match after collapsing a pair**: structural changes leave prose behind. Grep the repo for the deleted or renamed path, for any claim about how the artifact is produced (e.g. "the build inlines the data"), and for **hard counts** — number of cleanup categories, assertion counts, default port, install paths. A stale sentence *or* a stale number that contradicts the code is worse than no sentence; the number is the more dangerous of the two because it looks authoritative. Measured 2026-09-23: one doc pass left "13 categories", "31 headless assertions" and "port 8765" while the code said 17, 35 and 8766. Re-derive every count from the running code (grep the category labels out of `dashboard_template.html`, run the assertion script) instead of trusting the previous number.

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

## Docker routing

This Mac cleanup Skill does not install, start, inspect, build with, or manage a local Docker engine or OrbStack. Keep local development lightweight. Route NAS Docker status, logs, start, stop, restart, update, and rollback through Agent Ops; do not SSH to the NAS for Docker work or call Docker/fnOS APIs directly.

## User LaunchAgent service CLI

Use the bundled `scripts/local_services_cli.py` when the user asks to inspect or manage an existing macOS user service. Commands return one JSON object on stdout; failures return a JSON error on stderr and a nonzero exit code.

```sh
python3 <skill-dir>/scripts/local_services_cli.py list
python3 <skill-dir>/scripts/local_services_cli.py status com.example.worker
python3 <skill-dir>/scripts/local_services_cli.py register com.example.worker
python3 <skill-dir>/scripts/local_services_cli.py start com.example.worker
python3 <skill-dir>/scripts/local_services_cli.py stop com.example.worker
python3 <skill-dir>/scripts/local_services_cli.py enable-autostart com.example.worker
python3 <skill-dir>/scripts/local_services_cli.py disable-autostart com.example.worker
```

List and status are read-only. Register only the exact Label of an existing `~/Library/LaunchAgents/<Label>.plist`; registration records the verified plist path and does not start it or change its login policy. Start, stop, and autostart changes require the exact service to be registered first. Run lifecycle commands only when the user has asked for that service action. The CLI delegates every operation to `local_services.py`; it does not accept arbitrary plist paths, shell commands, system LaunchAgents/Daemons, or restart. Its JSON does not echo plist argument vectors. Agent Ops remains the owner of NAS container lifecycle and does not control these local Mac services.

## Application Login Items inventory (read-only)

Use the bundled `scripts/local_login_items_cli.py list` to read the current user's traditional “Open at Login” list through the native System Events Apple Events interface. The first call may require macOS Automation permission. The CLI outputs JSON and never changes login state; there are no enable/disable/remove commands. The dashboard performs the same read only after an explicit button click. macOS `SMAppService` controls helpers registered inside the calling app's bundle; it does not provide a public switch for this unrelated dashboard to toggle other apps. Use the exact System Settings > General > Login Items & Extensions pane for changes. App Background Activity and extensions are outside this inventory.

```sh
python3 <skill-dir>/scripts/local_login_items_cli.py list
```

## Agent Ops status handoff

Agent Ops exposes the latest Mac cleanup scan as a read-only aggregate:

```sh
agent-ops status --scope mac --json
```

This reads `~/.codex/logs/mac-dev-cleanup/state.json` only. It does not run a scan or cleanup, and omits candidate paths. The report includes scan time/staleness, risk counts, byte totals, selected bytes, and disk usage. To refresh it, run this Skill's read-only `scan` command first, then query Agent Ops again. Keep cleanup execution in this Skill's explicit `--apply` path; Agent Ops is an inventory and handoff surface, not a file-deletion interface.

## Useful follow-up checks

If the script reports large skipped targets, inspect manually before deleting:

```bash
ncdu ~
ncdu ~/Library/Caches
ncdu ~/Library/Logs
ncdu ~/.cache
```
