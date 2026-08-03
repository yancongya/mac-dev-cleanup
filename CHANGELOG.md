# 变更历史 / Commit History（重构）

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
