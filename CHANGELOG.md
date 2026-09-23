# 变更历史 / Commit History（重构）

## Unreleased

### Changed
- **看板端口改为可配置，默认 8766**：`web_server.py` 原先硬编码 `--port` 默认 8765，而该端口在本机被保持运行的 CodexAutoResume 守护进程占用 —— 端口冲突时服务会立刻退出，看起来就像命令什么都没做。现解析顺序为 `--port` → `MDC_PORT` 环境变量 → `config.json: dashboard_port`，默认值 8766；`validate_config` 拒绝 1024–65535 之外的取值（含字符串与浮点），新增 `DashboardPortTests` 三例（单测 34 → 37）。SKILL.md 同步说明冲突原因与三种改法。

### Added
- **应用白名单缓存识别（`config.json: app_support_whitelist`）**：`~/Library/Application Support` 一直是整体 prune 的，于是把多 GB 缓存放在那里的应用对扫描**完全不可见**。新增 config 驱动的形状白名单（对齐微信白名单的做法，但条目来自 `config.json`，新增应用只是改配置而非改代码）：仅**逐字列出**的相对路径被豁免，应用自身的数据库/配置/授权一律不匹配。`safe` 条目归入新分类 `app-support-cache`（temp、录屏恢复、崩溃转储、运行日志，`clean-safe` 可清）；`manual` 条目归入 `app-support-manual`（截图历史等用户数据，只上报、永不自动删）。条目可选 `require_quit`：该进程在跑时 `--apply` 跳过其 `safe` 路径并打印 `skipped: <name> is running`，避免移动正在录制的文件。首条内置规则为 PixPin —— 其 `Temp/RecordingRecovery` 单文件曾达 **2.2G** 且完全扫描不到（2026-09-23）；同目录 43 个 `.his` 截图历史归为 `manual`。校验拒绝：root 不在任何 `PRUNE_PATHS` 之下、绝对路径 / `~` 前缀 / 含 `..` 的逃逸路径、同一路径同时列为 safe 与 manual、空条目与未知键。
- **Docker / OrbStack 章节**（SKILL.md）：明确「绝不盲扫」禁区——`docker container prune` 会删掉只是当前未运行的服务容器（如 n8n，应 `docker start` 而非 prune）、`docker volume prune` 会删掉无运行容器认领的业务数据卷（如 `bwvault-data`）、`docker system prune -a` 两者兼有；给出安全序列（`docker system df` → `image prune` → `builder prune`）。并区分字节位置：本机 OrbStack 由宿主驱动，NAS（tyconfn）的 Docker root 在 `/vol1`（≈900G）而非 ≈20G 系统盘。
- **`df` 记账失灵对照实验**（SKILL.md）：新增「是没删掉还是没记账」的判定法——`dd` 写入 512MB，看 `df -k` 是否上涨、删除后是否回落；「写入涨、删除不降」= 系统记账卡住（待装更新/重启占位），不是清理失败，别重复删。同时补正：查快照必须用 `tmutil listlocalsnapshots /System/Volumes/Data`，`diskutil apfs listSnapshots` 返回 `No snapshots` 是误导。
- **Project hygiene 章节**（SKILL.md）：新增项目内结构整理工作流，覆盖空目录清理、AI IDE 残留删除、散落脚本归类、冗余文档合并、Git 感知移动/删除、标准目录约定。源自 pilinote 项目实际整理经验（2026-09-01）。
- **看板亮/暗主题手动切换**：顶栏新增主题按钮，可在亮色/暗色间切换并持久化到 `localStorage`（`mdc.theme`）；未手动选择时仍跟随系统 `prefers-color-scheme`。默认主题采用 logo 的粉色系（`#f95c93` 品牌粉 + `#650340` 深酒红），链接/焦点环/主按钮/拖拽高亮均改为粉色，暗色背景改为酒红微染（`#150a11`）。新增防闪烁初始化脚本（2026-09-01）。

- **Install layout 章节（SKILL.md，SkillDo 管理）**：新增「单一物理副本 + 5 个软链」的安装布局说明——`~/.skillshub/mac-dev-cleanup` 是唯一实目录，codex / claude_code / mimocode / workbuddy / OH-WorkSpace 全部软链到它。写明三条铁律：只在中心目录改、发布走 `skilldo push` 拉取走 `skilldo update`、**`skilldo update` 会按仓库整体重建中心目录（删掉所有未被 git 跟踪的文件）**，因此必须跨 update 存活的东西一律放在技能目录之外。背景：本机曾出现**三份副本**（codex 实目录 + 中心镜像 + workbuddy 实目录），4 个工具读到的是一个月前的镜像，只有 codex 读得到新代码。
- **Core rules 补两条现场规则（SKILL.md）**：① 判定废纸篓已清空要看 `du -sk ~/.Trash/mac-dev-cleanup` 是否为 0，**不能等隔离目录消失**——清空后空的 `mac-dev-cleanup/` 外壳仍在，等它消失必然跑满超时并误报失败（实测白等 600 s）。② 目标被运行中进程占用时必须**中止该条目**（不是打印提示后继续）：2026-09-09 曾在 HanaAgent 子进程运行时移动 `.hanako` 应用数据目录，打断运行中的服务并需人工恢复；应用运行数据目录（`~/.hanako`、`~/.workbuddy`、`~/.codex`、`~/.claude`、容器存储）默认不动，内置形态是微信硬跳过、config 形态是 `require_quit`。
- **aggressive 收益提醒（SKILL.md Risk levels）**：updater / runtime 类缓存**当天就会重新下载**，清它只赔带宽。实测 2026-09-22：aggressive 清掉 `~/.cache/codex-runtimes` 1.6G、`hanako-updater` 437M、`com.google.antigravity` 352M，数小时内全部回归。aggressive 的力气应花在构建产物（`target`/`build`/`dist`/`.venv`/`node_modules`）上。

### Fixed
- **清空废纸篓的降级路径**（SKILL.md Core rules）：原文只写 `osascript`，但实测在 TCC 下被拒（`-10004`，退出码 1，**非超时**）。现补判别法（用只读 AppleScript 探测，同样失败 ⇒ 宿主进程缺 Finder 自动化授权）与已验证的降级方案 `rm -rf ~/.Trash/mac-dev-cleanup/<op-id>`（只动本工具隔离内容，不波及老板废纸篓里的其它内容），并注明代价是 `--restore` 失效；补充 `ls ~/.Trash/` 会被 TCC 拒绝、改用 `du -sh` 校验结果。
- **看板动态 action 翻译**：`zh()` 支持 `skipped: <应用名> is running` 形状的动态翻译（原静态表只能匹配写死的「微信运行中」）；新增 `app-support-cache` / `app-support-manual` 中文标签与两条 reason 翻译规则。
- **看板主题按钮可见性**：将顶栏主题切换按钮从 32×32 纯图标改为带文字标签的按钮（暗色/亮色），并添加品牌粉色边框，避免被误认为普通状态图标。
- **docs 落地页新增亮/暗手动切换**：`docs/index.html` 原本只跟随系统暗色，现加入与看板一致的顶栏主题按钮（`data-theme` + `localStorage` 持久化），默认仍跟随系统；按钮采用 logo 粉色边框。
- **docs 落地页亮色主题改为 logo 粉色系**：修复亮色下强调色仍固定为绿色的问题。默认亮色与 `data-theme="light"` 下 `--accent` 改为 `#c2185b`（深粉红）并配合 `--accent-soft:rgba(249,92,147,.12)`；暗色下 `--accent` 改为 `#f95c93`（品牌粉）并配合深酒红 `--accent-ink:#3a0a1f`；`--green` 语义变量也同步映射为粉色，`.tag-safe`、`.tl.ok`、`.copy.done` 等均不再显示绿色。
- **dashboard.html 去数据化、可安全入库**：此前生成的 `dashboard.html` 会把真实扫描数据（机器绝对路径、磁盘用量、各类缓存字节数）内联进页面，无法公开上传。`_render_dashboard_html` 不再内联 state/config，改为由 `dashboard.html` 通过 `<script src="dashboard_data.js">` / `<script src="config_data.js">` 引用（两者仍 gitignore，含机器数据）。本地 file:// 打开时同目录脚本加载真实数据正常显示；上传到 GitHub 后纯壳无泄露，前端回退到内置「数据缺失」提示。`.gitignore` 相应移除 `dashboard.html` 排除项；`check_dashboard.py` 放宽原「禁止外部 script」断言为仅允许这两个数据文件，`check_dashboard_dom.mjs` 改为在内存注入 `state.json` 验证渲染（不再依赖异步 file:// 加载）。

### Changed
- **`config.json` 迁出技能目录**：策略文件从 `<skill>/config.json` 移到 `~/.codex/logs/mac-dev-cleanup/config.json`。原因是 `skilldo update` 会按仓库整体重建技能目录，留在其中的策略文件会被删除、本机设置被静默重置。新增 `adopt_legacy_config()`（把旧位置的文件**移动**过来：不覆盖已存在策略、`MDC_CONFIG` 生效时不执行），模块加载时自动做一次性迁移；`LOG_DIR` 尚未创建时 `save_config()` 会先建父目录。`web_server.py` 不再自己拼 `ROOT / "config.json"`，改为复用 `cleanup.CONFIG_PATH`，避免看板与 CLI 读写两份配置。新增 `ConfigLocationTests`（5 例）锁死「配置必须位于技能目录之外」这条规则。
- **技能内 `.workbuddy/` 记忆迁出并软链回来**：该目录（WorkBuddy 会话记忆 + 每日清理自动化的运行记录）同样会被 `skilldo update` 抹掉，现实体存放于 `~/.codex/logs/mac-dev-cleanup/.workbuddy/`，技能目录内只留软链。顺带清理 1 个 0 字节空日志。

> 本文件基于会话迭代记录与各文件的磁盘时间戳（mtime）重建。
> 真实的 git 仓库于 **2026-08-03** 才初始化，此前在多个 IDE（Codex / Trae / WorkBuddy）中的迭代未留下独立文件副本，
> 仅存两份可用物证：
> - `scripts/mac_dev_cleanup.py.bak.20260731`（2026-07-31 19:11 的脚本快照）
> - 当前各文件（最新版）
>
> 因此下列"提交"为**语义化重建**，用于记录演化脉络；颗粒度以物证可支撑者为界。

---

## 1. 2026-07-11 · chore: 技能初始骨架（来自市场/模板）

- `agents/openai.yaml`：定义技能元信息（display_name、short_description、default_prompt、allow_implicit_invocation）。
- 此时仅有占位脚本与说明，无实际扫描/清理逻辑。

## 2. 2026-07-31 · feat: 基础扫描与清理能力

- 新增 `scripts/mac_dev_cleanup.py` 初版：
  - `discover_global()` / `scan_projects()` / `scan_temp()` 识别全局缓存（npm/uv/pip/playwright/codex 等）、项目内 `node_modules`/`.venv`/`build`、临时目录。
  - 风险分级：`safe` / `aggressive` / `manual`；模式 `scan` / `clean-safe` / `clean-aggressive`。
  - `Candidate` 数据类、`write_state()` 输出 `state.json` + 外部数据文件。
- 首轮实测：激进全清 ~9.8G。
- 物证：该版即为 `mac_dev_cleanup.py.bak.20260731`。

## 3. 2026-07-31 · feat: 扩展识别范围（大文件/日志/缓存/截图）

- 升级脚本识别：大文件目录、测试产物、应用日志、各类缓存、截图等。
- 先清理一轮：应用缓存/日志 ~4.8G。

## 4. 2026-07-31 · fix: 删除后磁盘空间不释放（APFS 快照）

- 现象：删了大文件但 `df` 不变。
- 根因：APFS 系统更新快照 `com.apple.os.update-*` 占位，需重启才释放。
- 在 `SKILL.md` 补 APFS 快照注意事项与验证命令（`df -h ~`）。

## 5. 2026-07-31 · feat: stale 项目识别（很久没开发的项目）

- 判定方式：源码文件 mtime + 最后 git commit 时间（排除 `.DS_Store`/lockfile/`.workbuddy` 等元数据假活跃）。
- 识别 stale 项目的依赖与模型（`.pth`/`.safetensors`/`.onnx` 等），清理模型 ~8.87G。
- 新增 `--stale-days`（默认 90）。

## 6. 2026-07-31 · feat: Web 仪表盘首版（多轮 redesign）

- 初版依赖 Tailwind + Alpine，从 `vendor/` 本地加载；输出 `dashboard_data.js` / `config_data.js` 供页面读取。
- 经历多轮改版：去"AI 味"、更专业、响应式（手机/平板/桌面三断点）。

## 7. 2026-08-01 · feat: 控制服务器（实时扫描/保存）

- 新增 `scripts/web_server.py`：本地 HTTP 服务，支撑仪表盘"重新扫描 / 保存配置"按钮联网生效。
- 离线（`file://`）模式下降级为"生成 CLI 命令 + 下载 config.json"。

## 8. 2026-08-03 · refactor: 零依赖自包含仪表盘

- 根因：预览 webview 对 `body` 末尾 `defer` 外部脚本 + 兄弟 `<script src>` 数据文件初始化失败，触发"脚本加载失败"兜底。
- 重写为纯 vanilla 单文件：`dashboard_template.html`（`/*__DATA__*/` / `/*__CONFIG__*/` 令牌），`write_state()` 注入数据后输出自包含 `dashboard.html`。
- 移除 Alpine / Tailwind / `vendor/` / CDN / 外部数据文件；体积 488KB → 63KB。
- jsdom 无头渲染验证：零运行时错误，77 行候选全渲染。

## 9. 2026-08-03 · feat: config.json 配置化

- 新增 `config.json`：可配置 `stale_days`、各类阈值（app_cache_min_mb / app_log_min_mb / large_dir_mb / large_file_mb）、扫描根目录等。
- Web 设置面板可改配置 → 生成 `set-config` 命令 / 下载 config.json；脚本 `load_config()` / `validate_config()` / `save_config()` 读取校验。
- **安全边界**（PROJECT_ROOTS、PERSONAL_ROOTS、MODEL_SUFFIXES 等）保持硬编码，不进 config。

## 10. 2026-08-03 · fix: 顶栏置顶 + 主题化滚动条

- 移除 56px `top-spacer`（原先为避免被预览工具栏遮挡而留白，导致顶栏悬空），顶栏改 `sticky; top:0`。
- 新增 `::-webkit-scrollbar`（圆角细条）+ `scrollbar-width:thin`，颜色跟随浅/深色变量。

## 11. 2026-08-03 · feat: 候选项面板小屏卡片化

- 小屏（<640px）隐藏表格，改用卡片流（每条候选纵向展示 大小/风险/动作/类别/路径/原因），去除横向滚动。
- 大屏（≥640px）保留原表格；搜索/筛选在两种视图同步更新。

## 12. 2026-08-23 · feat: 微信缓存与过期聊天媒体清理（白名单制）

- 新增 `wechat-cache`（radium 小程序运行时 / app_data 日志 / crashinfo / 容器 Caches）与 `wechat-media`（`msg/{attach,video,file}` 及账号 `cache` 下严格 `YYYY-MM` 月份目录）两个 aggressive 类别。
- `wechat_media_keep_months` 配置项（默认 1 = 仅保留当月）；消息数据库（db_storage）、config、favorite、Backup、all_users 因形状校验结构性不可命中。
- `pruned()` 中枢白名单豁免：仅放行上述精确形状，容器其余部分照旧 pruned。
- 运行中守卫：`--apply` 时检测到微信进程则跳过全部微信候选并警告，杜绝 live 容器内移动文件导致数据库损坏。
- dashboard 模板 `zh()` 增加微信类别与跳过状态中文标签；单元测试覆盖月份解析、cutoff、豁免形状与配置校验。

## 13. 2026-08-31 · feat: Tauri / Vite 构建衍生物识别

- 起因：Tauri 应用（skills-hub / skilldo）反复构建会留下 GB 级产物，此前只能人工清理。
- 规则以 `src-tauri` 父目录为锚点做形状匹配，避免泛名 `gen` 误伤无关目录：
  - `src-tauri/gen/`（tauri-build 生成的 capability schemas）→ `safe`，cargo build 秒级重建。
  - `src-tauri/target/` → `aggressive`，reason 标注 `Tauri/Rust build directory`。
  - `dist-ssr/` 加入 `AGGRESSIVE_DIR_NAMES`；`.vite-temp/` 加入 `SAFE_DIR_NAMES`。
  - `vite.config.ts.timestamp-*.mjs` 等 Vite 临时配置副本 → `safe`。
- 交付物保护：`target/release/bundle/**` 出现 `.dmg/.app/.msi/.exe/.deb/.rpm/.AppImage` 时，整个 target 降级为 `manual`，aggressive 不可清；浅层扫描（限深 4 层）避免遍历多 GB 的 target。
- stale 流程同步该判断，闲置项目的已打包 target 不会被 `stale-deps` 重新提升为 aggressive。
- 单元测试新增 `TauriBuildTests`（7 例，共 16 例全绿）；SKILL.md 新增「Tauri / Vite build by-products」章节。

## 14. 2026-08-31 · refactor: 构建衍生物规则改为 config 驱动 + 控制台汉化升级

**规则配置化（回应"为什么硬编码在脚本里"）**
- `config.json` 新增 `build_artifacts` 策略块（safe_dirs / aggressive_dirs / safe_file_globs / tauri_parents / tauri_gen_dirs / tauri_build_dirs / bundle_markers），脚本不再硬编码这些名字。
- 内置 `SAFE_DIR_NAMES` / `AGGRESSIVE_DIR_NAMES` 保持为不可缩减的安全边界，自定义项以并集方式追加；新增 `EFFECTIVE_SAFE_DIRS` / `EFFECTIVE_AGGRESSIVE_DIRS` 供 walker 使用。
- `_validate_build_artifacts()` 拒绝未知键与非字符串；嵌套对象按键合并（部分覆盖不丢兄弟默认值）；`bundle_markers` 清空时回退内置列表（交付物保护不可绕过）。
- `is_vite_timestamp_file()` → `is_build_artifact_file()`，改由 `safe_file_globs` fnmatch 驱动。
- 新增 `MDC_CONFIG` 环境变量指向备用策略文件（供测试切换配置）；`BuildArtifactConfigTests` 5 例，共 **21 例全绿**。

**控制台（dashboard_template.html）**
- 汉化：标题/品牌、"API online"→"接口已连接"、工具自检 ok/miss→"已安装"/"缺失"、运行模式 scan/clean-safe/clean-aggressive→中文、设置项标签全部中文化（原为英文键名）。
- 新增 `REASON_RULES`：31 条 reason 模板正则汉化（$1/$2 参数回填），未命中回退原文；原因列由此前的全英文变为中文。
- 交互修复：搜索/筛选不再重建整个卡片，只替换 `#listview`，修复了每敲一个字符就丢焦点、中文输入法组合被打断的问题。
- 新增：toast 轻提示（扫描/保存/复制结果不再藏进折叠的设置面板）、路径点击复制、筛选 chip 显示数量、草稿提示与"放弃草稿"、保存后原地更新配置、数字输入下限校正。
- 无障碍：设置折叠 `aria-expanded`/键盘可操作、chip `aria-pressed`、输入框 `aria-label`；`fetch` 缺失时静默降级（原先抛未捕获 ReferenceError）。
- 设置面板改为 `SETTINGS_SCHEMA` 驱动，新增「构建衍生物规则」分组与微信媒体保留月数字段；`readForm` 输出含 `build_artifacts`，与 `--set-config` / `api/config` 闭环。
- 新增 `scripts/check_dashboard_dom.mjs`（jsdom 无头渲染，31 条断言全通过，零运行时错误）。

---

## 物证对照

| 文件 | mtime | 对应阶段 |
|------|-------|----------|
| `agents/openai.yaml` | 2026-07-11 08:01 | #1 骨架 |
| `scripts/mac_dev_cleanup.py.bak.20260731` | 2026-07-31 19:11 | #2 基础版快照 |
| `scripts/web_server.py` | 2026-08-01 02:28 | #7 控制服务器 |
| `scripts/mac_dev_cleanup.py` | 2026-08-03 12:44 | #5/#8/#9 大改写 |
| `SKILL.md` | 2026-08-03 12:46 | 文档同步 |
| `dashboard_template.html` / `dashboard.html` | 2026-08-03 14:15 | #10/#11 |

> 注：#3/#4/#6 等中间改版发生在 7/31–8/1，未留下独立文件快照，仅能从会话记录还原其语义。
