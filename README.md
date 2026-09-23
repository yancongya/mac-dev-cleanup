# mac-dev-cleanup

> 一个由 **AI 代理驱动**的 macOS 开发者缓存清理 **Skill**。

在 Codex / Trae / Claude 等 AI 代理里用自然语言说一句「清理我的开发缓存」，代理读取本仓库的 `SKILL.md` 后调用内置 Python 脚本，自动完成扫描、分级与可恢复的清理。

🌐 在线主页：[yancongya.github.io/mac-dev-cleanup](https://yancongya.github.io/mac-dev-cleanup/)

## 这是什么

`mac-dev-cleanup` 是一个 **AI Skill**（不是独立 App）：

- `SKILL.md` —— 给 **AI 代理**读取的技能清单（代理据此知道何时、如何调用本 Skill）；
- `scripts/mac_dev_cleanup.py` —— Skill 真正执行的清理引擎（纯 Python 标准库，零运行时依赖）；
- `scripts/web_server.py` + `dashboard_template.html` —— 本地 Web 控制台（读状态、改配置、触发扫描）；
- 本 `README.md` —— 给**人**看的仓库说明。

> **README.md 与 SKILL.md 不冲突**：前者面向人类浏览 GitHub，后者面向 AI 代理运行 Skill，两者职责完全不同、可共存。

> 仓库中的 `dashboard.html` 是**构建产物**（`dashboard_template.html` 的副本），不入库、由本地 `scan` 生成；`.gitignore` 同时排除含本机数据的 `config_data.js` / `dashboard_data.js` / `config.json` / `state.json`。

## 快速开始

**步骤 0（推荐）· 一键下载并使用**：把下面这句直接复制给 AI 代理，它会自动完成「克隆仓库 → 安装到 skills 目录 → 跑只读扫描做安装验证」的完整链路：

> 请帮我把这个 skill 快速下载并安装使用：把仓库 https://github.com/yancongya/mac-dev-cleanup.git 克隆到 ~/.codex/skills/mac-dev-cleanup，然后运行 scan 做一次只读扫描作为安装验证，告诉我能清理多少空间、有哪些需要我确认的项目。如果缺少 Python 或权限不足，也请说明。

如需手动操作：

1. **手动安装 Skill**（终端执行，把仓库放到代理的 skills 目录，下例以 Codex 为例）：

   ```bash
   git clone https://github.com/yancongya/mac-dev-cleanup.git ~/.codex/skills/mac-dev-cleanup
   ```

   若用 **SkillDo** 统一管理多个 Skill，推荐只保留一份物理目录 `~/.skillshub/mac-dev-cleanup`，其余工具的 skills 目录一律用软链指过去——多份真副本会各自漂移，导致不同代理读到不同版本的代码。

2. **调用 Skill**（安装后，在 AI 代理对话里直接说，可整句复制粘贴）：

   > 用 mac-dev-cleanup 这个 skill 帮我扫描并清理开发缓存：先只做只读扫描，再列出可清理项让我确认后再执行。

## 能力

- 识别 **17 类**清理目标：全局/应用缓存与日志、项目生成物、日志与临时文件、测试产物、截图、大目录/大文件、闲置依赖与闲置模型、微信缓存与过期媒体、白名单应用的缓存与用户数据…
- **三级风险模型**：`safe` / `aggressive` / `manual`（`manual` 永不自动删除，仅报告待确认）
- **配置化应用白名单**：把 `~/Library/Application Support/<App>` 下可安全回收的缓存（如录屏中断残档、Crashpad、日志）纳入扫描，用户数据（如截图历史）只报告不删；应用常驻时自动跳过，退出后重跑即回收
- **Stale 项目识别**：以源码 mtime + 最后 git commit 判定（默认 90 天）
- **可恢复清理**：真实清理「先进废纸篓」，写入操作清单，可一键还原——绝不使用裸 `rm`
- **清理后自动回收**：`--apply` 完成后自动清空废纸篓（后台 osascript + 10 分钟轮询）并核验回收；`df` 未回补时按 SKILL.md 的对照实验判断，而不是重复删除
- **容器只报告、不盲删**：Docker / OrbStack 的镜像与卷只做列表与人工确认（`docker container prune` 会连服务容器一起删）
- **项目内结构整理（Project hygiene）**：除磁盘级缓存外，还能整理单个项目——清空格目录、删 AI IDE 残留（`.agents`/`.claude`/`.opencode`/`.superpowers`/`.workflow`/`.DS_Store`/`*.bak`）、把散落的 `migrate_*`/`fix_*`/`test_*`/`init_*` 脚本归位到 `scripts/`/`tests/`、合并冗余文档。全程 Git 感知（`git mv`/`git rm`），不碰源码与数据库
- **本地 Web 控制台**：只读状态查看 + 配置编辑 + 触发扫描；端口解析顺序 `--port` → `MDC_PORT` → `config.json: dashboard_port`（默认 8766，避让常被占用的 8765）
- **零运行时依赖**：纯 Python 标准库

## 命令参考

下文用 `<skill-dir>` 指代安装目录（经典布局为 `~/.codex/skills/mac-dev-cleanup`，SkillDo 布局为 `~/.skillshub/mac-dev-cleanup`）：

```bash
python3 <skill-dir>/scripts/mac_dev_cleanup.py scan               # 只读扫描
python3 <skill-dir>/scripts/mac_dev_cleanup.py clean-safe         # 干跑（只报告）
python3 <skill-dir>/scripts/mac_dev_cleanup.py clean-safe --apply # 真清理（进废纸篓）
python3 <skill-dir>/scripts/mac_dev_cleanup.py --show-config      # 查看当前配置
python3 <skill-dir>/scripts/web_server.py --port 8766             # 启动本地 Web 控制台
```

完整说明见 [SKILL.md](SKILL.md)、[CHANGELOG.md](CHANGELOG.md) 与[在线文档](https://yancongya.github.io/mac-dev-cleanup/)。

## 安全须知

清理采用「Trash-first」策略：真实删除会先把文件移入 `~/.Trash/mac-dev-cleanup/<操作ID>/` 并写入操作清单，便于一键还原。完成后 Skill 会自动清空废纸篓释放空间（后台 osascript + 10 分钟轮询），并核验回收。

若 `df` 未及时回血，先用**对照实验**区分「记账失灵」与「清理没生效」：往 `/tmp` 写一个 512M 文件看 `df` 是否变化，再删掉看是否回补——写降删不回补是记账问题（多见于有待装系统更新），写降删也回补则说明腾出的块被其它进程占用，两种都不该重复删。切勿因 `df` 未变就误判清理失败（验证用 `df -h ~`，而非 `df /`）。详见 SKILL.md 的「APFS snapshots」章节。
