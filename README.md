# mac-dev-cleanup

> 一个由 **AI 代理驱动**的 macOS 开发者缓存清理 **Skill**。

在 Codex / Trae 等 AI 代理里用自然语言说一句「清理我的开发缓存」，代理读取本仓库的 `SKILL.md` 后调用内置 Python 脚本，自动完成扫描、分级与可恢复的清理。

🌐 在线主页：[yancongya.github.io/mac-dev-cleanup](https://yancongya.github.io/mac-dev-cleanup/)

## 这是什么

`mac-dev-cleanup` 是一个 **AI Skill**（不是独立 App）：

- `SKILL.md` —— 给 **AI 代理**读取的技能清单（Codex / Trae 等规范要求的入口，代理据此知道何时、如何调用本 Skill）；
- `scripts/mac_dev_cleanup.py` —— Skill 真正执行的清理引擎（纯 Python 标准库，零运行时依赖）；
- 本 `README.md` —— 给**人**看的仓库说明。

> **README.md 与 SKILL.md 不冲突**：前者面向人类浏览 GitHub，后者面向 AI 代理运行 Skill，两者职责完全不同、可共存。

## 快速开始

**步骤 0（推荐）· 一键下载并使用**：把下面这句直接复制给 AI 代理，它会自动完成「克隆仓库 → 安装到 skills 目录 → 跑只读扫描做安装验证」的完整链路：

> 请帮我把这个 skill 快速下载并安装使用：把仓库 https://github.com/yancongya/mac-dev-cleanup.git 克隆到 ~/.codex/skills/mac-dev-cleanup，然后运行 scan 做一次只读扫描作为安装验证，告诉我能清理多少空间、有哪些需要我确认的项目。如果缺少 Python 或权限不足，也请说明。

如需手动操作：

1. **手动安装 Skill**（终端执行，把仓库放到代理的 skills 目录）：

   ```bash
   git clone https://github.com/yancongya/mac-dev-cleanup.git ~/.codex/skills/mac-dev-cleanup
   ```

2. **调用 Skill**（安装后，在 AI 代理对话里直接说，可整句复制粘贴）：

   > 用 mac-dev-cleanup 这个 skill 帮我扫描并清理开发缓存：先只做只读扫描，再列出可清理项让我确认后再执行。

## 能力

- 识别 **13 类**目标：全局/应用缓存与日志、项目生成物、测试产物、截图、大目录/大文件、stale 依赖与模型…
- **三级风险模型**：`safe` / `aggressive` / `manual`（`manual` 永不自动删除，仅报告待确认）
- **Stale 项目识别**：以源码 mtime + 最后 git commit 判定（默认 90 天）
- **可恢复清理**：真实清理「先进废纸篓」，写入操作清单，可一键还原——绝不使用裸 `rm`
- **清理后自动释放空间**：`--apply` 完成后自动清空废纸篓（后台 osascript + 10 分钟轮询），并用 `df -h ~` 验证回收；无需手动重启
- **项目内结构整理（Project hygiene）**：除磁盘级缓存外，还能整理单个项目——清空格目录、删 AI IDE 残留（`.agents`/`.claude`/`.opencode`/`.superpowers`/`.workflow`/` .DS_Store`/`*.bak`）、把散落的 `migrate_*`/`fix_*`/`test_*`/`init_*` 脚本归位到 `scripts/`/`tests/`、合并冗余文档。全程 Git 感知（`git mv`/`git rm`），不碰源码与数据库
- **配置化**：单一 `config.json` 管理阈值/扫描根/排除项；附带本地 Web 控制台
- **零运行时依赖**：纯 Python 标准库

## 命令参考

```bash
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py scan               # 只读扫描
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-safe         # 干跑（只报告）
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py clean-safe --apply # 真清理（进废纸篓）
python3 ~/.codex/skills/mac-dev-cleanup/scripts/mac_dev_cleanup.py --show-config      # 查看当前配置
python3 ~/.codex/skills/mac-dev-cleanup/scripts/web_server.py                         # 启动本地 Web 控制台
```

完整说明见 [SKILL.md](SKILL.md) 与[在线文档](https://yancongya.github.io/mac-dev-cleanup/)。

## 安全须知

清理采用「Trash-first」策略：真实删除会先把文件移入 `~/.Trash/mac-dev-cleanup/<操作ID>/` 并写入操作清单，便于一键还原。完成后 Skill 会自动清空废纸篓释放空间（后台 osascript + 10 分钟轮询），并用 `df -h ~` 验证回收。

若仍因 **APFS 快照占位**未及时回血（多见于系统级大目录），**重启是最可靠的兜底释放方式**。切勿因 `df` 未变就误判清理失败（验证用 `df -h ~`，而非 `df /`）。详见 SKILL.md 的「APFS snapshots」章节。
