# mac-dev-cleanup

> 一个由 **AI 代理驱动**的 macOS 开发者缓存清理 **Skill**。

在 Codex / Trae / Claude 等 AI 代理里用自然语言说一句「清理我的开发缓存」，代理读取本仓库的 `SKILL.md` 后调用内置 Python 脚本，自动完成扫描、分级与可恢复的清理。

🌐 在线主页：[yancongya.github.io/mac-dev-cleanup](https://yancongya.github.io/mac-dev-cleanup/)

## 这是什么

`mac-dev-cleanup` 是一个 **AI Skill**（不是独立 App）：

- `SKILL.md` —— 给 **AI 代理**读取的技能清单（代理据此知道何时、如何调用本 Skill）；
- `scripts/mac_dev_cleanup.py` —— Skill 真正执行的清理引擎（纯 Python 标准库，零运行时依赖）；
- `scripts/export_summary.py` —— 从最近一次已保存状态导出脱敏摘要，不运行扫描或清理；
- `scripts/web_server.py` + `dashboard_template.html` —— 本地 Web 控制台（读状态、改配置、触发扫描）；
- 本 `README.md` —— 给**人**看的仓库说明。

> **README.md 与 SKILL.md 不冲突**：前者面向人类浏览 GitHub，后者面向 AI 代理运行 Skill，两者职责完全不同、可共存。

> 仓库中的 `dashboard.html` 是**构建产物**（`dashboard_template.html` 的副本），不入库、由本地 `scan` 生成；`.gitignore` 同时排除含本机数据的 `config_data.js` / `dashboard_data.js` / `config.json` / `state.json`。

## 快速开始

**步骤 0（推荐）· SkillDo 统一安装**：本机维护时以本仓库为唯一可编辑源，通过 SkillDo 构建并分发 Skill。把下面这句交给 AI 代理，它会先检查本地仓库与 SkillDo 安装状态，再按仓库里的流程构建、安装并做只读验证：

> 请按 mac-dev-cleanup 仓库的 SkillDo 流程安装或更新它：先检查本地仓库、生成包、SkillDo 中心副本和各 agent 软链的状态；只从仓库源构建并同步，不要创建第二份独立 Skill 副本；完成后运行只读 scan 验证，并报告可清理项和权限问题。

如需手动操作：

1. **维护本机安装**：在此仓库根目录执行 [SkillDo 更新流程](#skilldo-更新流程)。不要把仓库直接克隆到 `~/.codex/skills/`，否则会绕过中心目录并形成重复副本。没有 SkillDo 的外部使用者可按代理自己的安装流程克隆仓库。

2. **调用 Skill**（安装后，在 AI 代理对话里直接说，可整句复制粘贴）：

   > 用 mac-dev-cleanup 这个 skill 帮我扫描并清理开发缓存：先只做只读扫描，再列出可清理项让我确认后再执行。

## 验证

在仓库根目录运行 `npm test`，执行清理引擎、摘要导出与 Skill 路由测试；这些检查不会扫描或清理真实用户数据。Dashboard 集成检查单独运行 `npm run test:dashboard`，需要先有本机已保存的扫描状态和生成的 `dashboard.html`，并依赖已安装的 `jsdom`；它只读取这些既有产物，不会触发新扫描或清理。

如需导出最近一次扫描的汇总而不重新扫描，可指定一个已存在目录中的输出文件：

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/export_summary.py --output /path/to/mac-cleanup-summary.json
```

命令只读取已保存的 `state.json`，校验时间、风险计数和字节总数后写出 `mac-dev-cleanup.summary.v1`；导出仅含汇总字段，不含候选路径、ID、原因或配置。文件以仅当前用户可读写的权限原子写入。该命令只生成文件，不会自动同步到其他设备。

如需**显式上传**最近一次已保存摘要，必须明确提供 HTTPS 地址（路径固定为 `/v1/mac/summary`），并通过标准输入提供专用 `X-Mac-Ingest-Token`。不会触发扫描/清理，也不会把令牌写入文件或日志：

```bash
set -o pipefail
bwvault credential get --alias mac.cleanup.ingest-token --reveal --json \
  | jq -er '.secret | strings | select(length > 0)' \
  | python3 ~/.codex/skills/mac-dev-cleanup/scripts/export_summary.py --upload --endpoint https://collector.example/v1/mac/summary --token-stdin
```

将专用上传令牌保存在 `bwvault` 的 `mac.cleanup.ingest-token` alias 下。上面的流水线从 BWVault JSON 中只提取 `.secret` 并通过管道传递，不把密值显示到终端、写入参数或日志。读取最多 8192 字节。程序会校验服务器证书和主机名，并在 15 秒后超时；拒绝明文 HTTP、重定向、其他路径、URL 用户名/密码、查询参数和片段。只有 2xx 响应同时包含 `schema: agent-ops-mac/v1`、`accepted: true`、`state: stored` 才报告成功；其他响应统一报告未确认，且不显示响应正文。此功能只向用户明确指定的端点发送 allowlist 摘要，不发送候选详情、路径或配置。

## SkillDo 更新流程

本仓库根目录是唯一可编辑源；构建器把 Skill 专用文件投影到受 Git 跟踪的 `skills/mac-dev-cleanup/`。该目录是生成物，不要直接编辑。首次登记并刷新本机中心副本时，在仓库根目录运行：

```bash
python3 scripts/build_skilldo_package.py build
skilldo track-local --skill mac-dev-cleanup --path skills/mac-dev-cleanup --yes
skilldo update --skill mac-dev-cleanup --yes
```

后续修改根目录的 `SKILL.md`、运行脚本或支持文件后，重新构建并更新中心副本：

```bash
python3 scripts/build_skilldo_package.py build
skilldo update --skill mac-dev-cleanup --yes
```

构建器只把 Skill、运行脚本、看板模板和 Agent 元数据放进 `skills/mac-dev-cleanup/`，不包含 Git 元数据、依赖、配置、扫描状态、历史或生成的看板数据。首次更新前应确认本机政策和历史仍位于 `~/.codex/logs/mac-dev-cleanup/`；更新后运行一次 `scan`，重建本机看板文件。

`track-local` 保留仓库远端作为来源线索，但登记状态仍是本机来源。等生成目录提交并出现在 GitHub 后，再运行 `skilldo repair source --skill mac-dev-cleanup --url https://github.com/yancongya/mac-dev-cleanup.git --subpath skills/mac-dev-cleanup --apply`，将 SkillDo 元数据切换为可跨设备更新的 Git 来源。不要在远端路径尚未发布时强制登记 Git 来源。

## 能力

- 识别 **25 类**清理目标：全局/应用缓存与日志、项目生成物、日志与临时文件、测试产物、截图、大目录/大文件、闲置依赖与闲置模型、微信缓存与过期媒体、白名单应用的缓存与用户数据、Xcode 产物（DerivedData/DeviceSupport/Archives/模拟器）、开发缓存（Homebrew/pnpm/go/mise，Gradle 守护进程感知）、AI 工具缓存（含 Claude Code 旧版本，只留最新）、孤儿残留（反向扫描易失性目录 + 双向标识符匹配）、浏览器 profile 缓存（Chromium 系 + Firefox，Service Worker 站点数据永不碰）、安装包（DMG/PKG/ISO/XIP + ZIP 载荷校验）、iOS 设备备份（只读报告）…
- **重复文件查找（`dupes` 子命令）**：大小 → 64KB 头哈希 → 全量 SHA-256 四级渐进；硬链接不算重复；报告性质（选哪份保留是人决策），看板报告面板展示浪费总量
- **三级风险模型**：`safe` / `aggressive` / `manual`（`manual` 永不自动删除，仅报告待确认）
- **配置化应用白名单**：把 `~/Library/Application Support/<App>` 下可安全回收的缓存（如录屏中断残档、Crashpad、日志）纳入扫描，用户数据（如截图历史）只报告不删；应用常驻时自动跳过，退出后重跑即回收
- **Stale 项目识别**：以源码 mtime + 最后 git commit 判定（默认 90 天）
- **可恢复清理**：真实清理「先进废纸篓」，写入操作清单，可一键还原——绝不使用裸 `rm`
- **可恢复清理**：`--apply` 仅把候选项移入可恢复隔离区并写操作清单；不会自动清空废纸篓。清空是独立且不可逆的操作，必须由用户明确提出，并在控制台通过 `EMPTY TRASH` 与 API token 双重确认
- **Docker 边界**：本 Skill 只读查看 Mac OrbStack 容量；NAS Docker 状态、日志和生命周期操作统一经 Agent Ops，本 Skill 不执行 Docker 清理或其他写操作
- **统一 Agent 工作流接入**：扫描与清理仍由本 Skill 的 CLI/看板负责；需要把 Mac 状态汇入 Agent 工作流时，先运行本 Skill 的只读 `scan`，再调用 `agent-ops status --scope mac --json` 获取汇总。Agent Ops 只读取最新状态，不会触发扫描或清理，也不返回候选路径；结果可用于阶段记录，但不能代替 CLI/看板的执行证据。实际清理继续走本 Skill 的显式授权与 `--apply` 流程。
- **项目内结构整理（Project hygiene）**：除磁盘级缓存外，还能整理单个项目——清空格目录、删 AI IDE 残留（`.agents`/`.claude`/`.opencode`/`.superpowers`/`.workflow`/`.DS_Store`/`*.bak`）、把散落的 `migrate_*`/`fix_*`/`test_*`/`init_*` 脚本归位到 `scripts/`/`tests/`、合并冗余文档。全程 Git 感知（`git mv`/`git rm`），不碰源码与数据库
- **本地 Web 控制台**：六视图（概览 = 纯只读仪表盘 / 清理 = 唯一执行域含整模式与按勾选两种范式 + 重复文件 / 系统 = 应用卸载 + 启动项 + TM 快照 / 还原 = 操作与执行统一时间线 + 废纸篓 / 计划任务 / 设置含工具自检）；服务/FDA 权限降级由顶部全局横幅统一提示；端口解析顺序 `--port` → `MDC_PORT` → `config.json: dashboard_port`（默认 8766，避让常被占用的 8765）
- **系统废纸篓管理**：`~/.Trash` 全量清单（隔离区单列、保持可恢复）；清空需逐字确认串 `EMPTY TRASH` + API token 双重门禁，默认保留隔离区
- **TM 本地快照管理**：列表 + 单条删除；`com.apple.os.update-*` 系统更新回滚点代码级拒绝删除，重启装完更新即自动释放
- **启动与服务管理**：LaunchAgents/LaunchDaemons 清单保留系统级只读；用户明确登记的当前用户 LaunchAgent 可在本地看板启动/停止、设置登录自启。服务登记不启动服务也不改自启；停止与关闭自启相互独立。macOS 应用登录项暂未纳入清单，应用卸载仍是独立功能。
- **TCC 优雅降级**：`~/.Trash` 与 `MobileSync` 是 macOS 权限保护目录——无权限时 API 返回 `available: false` / 类别缺席并给出授权指引，绝不中断扫描或报 500
- **零运行时依赖**：纯 Python 标准库

## 命令参考

下文用 `<skill-dir>` 指代安装目录（经典布局为 `~/.codex/skills/mac-dev-cleanup`，SkillDo 布局为 `~/.skillshub/mac-dev-cleanup`）：

```bash
python3 <skill-dir>/scripts/mac_dev_cleanup.py scan               # 只读扫描
python3 <skill-dir>/scripts/mac_dev_cleanup.py clean-safe         # 干跑（只报告）
python3 <skill-dir>/scripts/mac_dev_cleanup.py scan --summary-json /tmp/mac-cleanup-summary.json # 导出无路径汇总
python3 <skill-dir>/scripts/mac_dev_cleanup.py clean-safe --summary-json /tmp/mac-cleanup-summary.json # 干跑汇总
python3 <skill-dir>/scripts/mac_dev_cleanup.py clean-safe --apply # 真清理（进废纸篓）
python3 <skill-dir>/scripts/mac_dev_cleanup.py dupes              # 重复文件报告（只读）
python3 <skill-dir>/scripts/mac_dev_cleanup.py --show-config      # 查看当前配置
python3 <skill-dir>/scripts/web_server.py --port 8766             # 启动本地 Web 控制台
```

完整说明见 [SKILL.md](SKILL.md)、[CHANGELOG.md](CHANGELOG.md) 与[在线文档](https://yancongya.github.io/mac-dev-cleanup/)。

`--summary-json` 仅用于 `scan` 或清理干跑，输出版本化、无候选路径/原因/ID/配置的 JSON 摘要；不能与 `--apply` 同用。

## 安全须知

清理采用「Trash-first」策略：`--apply` 会把文件移入 `~/.Trash/mac-dev-cleanup/<操作ID>/` 并写入操作清单，便于还原；它不会自动清空废纸篓。若用户之后明确要求永久清空，需通过控制台输入 `EMPTY TRASH` 并通过 API token 门禁。只有确认隔离区内容为零后，才可报告空间已经释放。

若 `df` 未及时回血，先用**对照实验**区分「记账失灵」与「清理没生效」：往 `/tmp` 写一个 512M 文件看 `df` 是否变化，再删掉看是否回补——写降删不回补是记账问题（多见于有待装系统更新），写降删也回补则说明腾出的块被其它进程占用，两种都不该重复删。切勿因 `df` 未变就误判清理失败（验证用 `df -h ~`，而非 `df /`）。详见 SKILL.md 的「APFS snapshots」章节。

另注意：`~/.Trash`、`~/Library/Application Support/MobileSync` 与 Safari 缓存受 macOS TCC 保护，crontab 读写也跟随同一权限。若 Web 控制台的「系统废纸篓」显示不可用、或扫描报告里没有 iOS 备份类别，需给服务进程授予「完全磁盘访问权限」，要点如下（2026-09-29 实证）：

1. **授权对象是解释器实体，不是 `/usr/bin/python3`**——那只是个 shim，exec 后进程实体变成 CLT 解释器，TCC 只认后者：
   `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9`
2. **该文件在 FDA 添加对话框里是灰色的**（Launch Services 把版本号 `.9` 误判为扩展名），「前往文件夹」对隐藏路径/软链也不跳转。唯一可靠方法：在 Finder 按 `Cmd+Shift+G` 进入上述目录，把 `python3.9` 文件**直接拖到「完全磁盘访问权限」列表上**，再打开开关。切勿经 Yoink/Dropover 等拖拽暂存工具——会给文件打隔离标记，导致服务进程被 SIGKILL。
3. 授权后 `launchctl kickstart -k gui/$(id -u)/com.yancongya.mac-dev-cleanup` 重启服务生效。
4. **Xcode CLT 升级后授权静默失效**（TCC 按实体路径 + ad-hoc 签名匹配），症状是废纸篓/crontab 又变「未授权」——重复一次拖拽即可。
5. **已授权但控制台仍显示「不可用」？先排查孤儿进程，别急着重新授权**：若 Finder 拖拽授权已完成、`launchctl kickstart -k` 重启后 `/api/trash` 仍 `available:false`，很可能是 **端口 8766 被一个 pre-FDA 的旧进程占着**——该进程在授权前就启动、从未获得 FDA 资格，launchd 按 KeepAlive 反复拉新实例全因 `Address already in use` 崩溃（err.log crash-loop），dashboard 始终连到这个无授权的老进程（2026-09-30 实案：P0 bug 的 `bootout` 曾让进程脱离 launchd 追踪却未死，长期占端口）。诊断：`lsof -nP -iTCP:8766 -sTCP:LISTEN` 看 PID 启动时间；若早于授权时刻就是它。`kill <pid>` 终止后 `launchctl kickstart -k gui/$(id -u)/com.yancongya.mac-dev-cleanup` 让 launchd 干净重建单实例即可，无需重新授权。
6. **不要在受限的 agent / IDE 终端里直接 `stat ~/.Trash` 验证 FDA**：那种环境自身没有 FDA（`ps`/`launchctl list` 都被拒），它的 python 子进程必然 `PermissionError`，会造成「授权失效」的假阴性。正确验证：在已授权的服务上 `launchctl kickstart -k` 之后，用**浏览器或真实 Terminal**（非 agent 子 shell）访问 `GET /api/trash`，看 `system.available` 字段——`true` 即授权生效。
