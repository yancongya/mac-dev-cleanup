# 验收清单（Acceptance Checklist）

> 用途：对「两条线调研（开源仓库源码拆解 + 商用产品功能清单）→ 复刻还原」成果做一次性完整验收。
> 调研基准见 [feature-parity.md](feature-parity.md)。本文档逐项可勾选，全绿即验收通过。
>
> 参考对标口径：**交互顺手度**对齐 Pearcleaner（卸载）/ Mole（CLI 安全工程）/ PureMac（诚实口径）/ AppCleaner（卸载交互）/ CleanMyMac X（全能布局）/ DaisyDisk（可视化）；**只对齐语义与交互，不搬运代码**。
>
> **2026-09-30 信息架构重组**：7 tab → **6 tab**（概览 / 清理 / 系统 / 还原 / 计划任务 / 设置）。
> 原「报告」tab 撤销：启动项 + TM 快照并入「系统」，重复文件迁入「清理」；「还原」= 操作历史 + 看板执行记录统一时间线。概览收敛为纯只读仪表盘（勾选/执行入口全部移除）。本清单已按新结构更新；文末 2026-09-28 验收记录保留为重组前基线存档。

---

## 0. 自动化门禁（每次验收前必跑，3 条命令 + 1 个巡检）

```bash
python3 scripts/test_mac_dev_cleanup.py        # 单测
python3 scripts/check_dashboard.py             # 模板与生成物一致性
node scripts/check_dashboard_dom.mjs dashboard.html   # DOM 结构
```

- [ ] 单测 **89/89** 通过（基线 89，含 cron/prune/trash TCC/service uninstall 归属守卫回归）
- [ ] DOM 检查 **105/105** 通过（基线 105，六视图 + 交互断言）
- [ ] 模板一致性 `[OK]`（生成物与模板逐字节一致）
- [ ] GET 端点巡检全部 200：`health / state / config / apps / trash / launch / snapshots / dupes / schedule / operations / clean/history / app/icon`（icon 用 apps 列表首个应用名验证，PNG 魔数）
- [ ] POST 门禁抽查：`empty-system` 错误 confirm → 400；`snapshot/delete` 传 `com.apple.os.update-*` 名 → 400；`schedule` 传 `clean-aggressive` → 400；`trash/clear` 错误 confirm → 400（CLEAR QUARANTINE 字面量守卫）
- [ ] TCC 降级抽查：无完全磁盘访问的上下文中 `/api/trash` 返回 `system.available:false`（非 500）、`/api/snapshots` 正常、scan 不中断
- [ ] **跑测试套件不卸载生产服务**：套件跑完后 `launchctl print gui/501/com.yancongya.mac-dev-cleanup` 仍有输出（2026-09-30 修复项，有回归测试锁定）

## 1. 概览视图（纯只读仪表盘，对标 CleanMyMac Smart Scan 布局 + DaisyDisk 可视化）

- [ ] 英雄区环形图 + 可清理量大数字，明暗主题均清晰
- [ ] **磁盘树图**（DaisyDisk/Mole analyze 语义）：分类体积 squarified 布局、top 12 + 「其他」、hover 显示完整 title、纯 SVG 零依赖
- [ ] 三张风险卡片（safe/aggressive/manual）数量与实际一致，**只跳转不执行**
- [ ] 深度清理候选预览行为**只读**——无勾选框、无执行/生成命令按钮，点击行跳转清理视图对应筛选
- [ ] **概览不再有任何执行入口**（ov-run-btn/ov-cmd-btn 已移除，DOM 断言锁定）
- [ ] 工具自检已迁至设置视图，概览不再出现

## 2. 清理视图（唯一执行域，对标 Mole clean 分级 + PureMac 永不自动勾选口径）

- [ ] 「整模式清理」面板语义明确：标注**忽略勾选、全量按模式执行**，与下方按勾选精确清理二选一不混淆
- [ ] 候选表：搜索框（焦点保持、实时过滤）、风险筛选 chip、排序表头（箭头切换）
- [ ] 路径可复制标记存在且 title 为完整路径
- [ ] 勾选 → 吸底操作栏计数联动 → 「生成命令」（离线态）与「执行」（在线态）双路径
- [ ] **勾选状态持久化**（localStorage `mdc.selection.v1`）：刷新页面勾选保留；候选清单变化后过期 id 自动丢弃
- [ ] 执行时实时日志滚动展示，结束后操作 ID 可查；执行完成刷新改为**轮询 state.timestamp**（无魔数延时）
- [ ] **manual 类永不自动勾选**：large-files / installer / ios-backup / orphan / ollama 模型 / Xcode Archives 与模拟器 Devices / 截图 / 大文件
- [ ] 25 类 category 与全部 reason 中文标签覆盖（无英文裸串漏翻）
- [ ] 浏览器运行中，其缓存候选整组缺席（Chrome 开着 → 无 Chrome 候选）
- [ ] 执行产物全部进隔离区（Trash-first），`~/.Trash/mac-dev-cleanup/` 出现带 manifest 的操作目录
- [ ] **重复文件面板**（自原报告 tab 迁入）：浪费总量、组列表、building 态轮询、truncated 提示；note 明示「报告只读，处理需人工决策」

## 3. 系统视图（应用卸载 + 启动项 + TM 快照，对标 AppCleaner/Pearcleaner/Mole/PureMac）

### 3a. 应用卸载

- [ ] 列表：图标（PNG 实图）、体积、运行中徽标、搜索、排序
- [ ] 卸载按钮**两段式确认**（第一次变「确认卸载？」，5 秒超时回退）
- [ ] 卸载成功：toast + 列表**即时**移除该应用（不依赖手动重扫）
- [ ] 卸载成功提供「↺ 查看操作历史并还原」直达跳转
- [ ] 图标请求 404 时回退字母头像（不出现破图）
- [ ] 卸载后：bundle + 关联 Library 残留进隔离区，还原视图可一键还原
- [ ] 卸载失败（应用运行中/受保护）有明确错误 toast
- [ ] 通过 Finder 等外部途径删除的应用，重进应用视图后**自动消失**（GET 自愈），图标同步清扫

### 3b. 启动项（只读）

- [ ] scope 分组（用户/本地代理/本地守护中文）、Label/Program/RunAtLoad/KeepAlive 徽标、com.apple.* 已过滤
- [ ] 只读声明（「启用/卸载请在 launchctl 或应用内操作」），面板内无操作按钮

### 3c. TM 快照

- [ ] 可删/受保护双态徽标；`com.apple.os.update-*` 显示「受保护」且**无删除按钮**
- [ ] 可删项删除需强确认弹层（**注明不可恢复** + tmutil 警示）；df 不实时说明

## 4. 还原视图（统一时间线，对标 Pearcleaner 双层 Undo + Mole trash bins）

- [ ] **操作与执行记录统一时间线**：清理（看板/CLI/定时来源标注）与卸载全部按时间交错呈现，一处看全「刚才那次清理怎么样了」
- [ ] 可还原操作带**一键还原**（两段式确认）+ 明细展开 + 还原命令可复制
- [ ] 看板触发的运行带状态徽标（运行中/成功/exit N）+ **日志展开**
- [ ] 独立「执行记录（仅看板触发）」面板已移除（DOM 断言锁定）
- [ ] 隔离区：操作清单（ID/时间/条数/体积）+ 清空按钮
- [ ] **清空隔离区守卫**：走统一确认层（非原生 confirm），正文说明「清空将放弃 N 条操作记录的还原能力」；后端 `CLEAR QUARANTINE` 字面量守卫兜底
- [ ] **系统废纸篓**：总量、条目列表（大小/时间排序）、条目数；与隔离区分块展示，隔离区不计入系统废纸篓体积
- [ ] 清空系统废纸篓**强确认弹层**：第一次点弹确认层 → 层内二次点击才执行；文案注明「默认保留 mac-dev-cleanup 隔离区（可恢复）」+ **不可恢复**标识
- [ ] TCC 无权限时：顶部全局降级横幅出现（唯一授权指引入口），面板内仅留本地禁用短文案（不白屏不报错）

## 5. 计划任务视图（对标 CCleaner 计划清理 + PureMac 计划清理安全口径）

- [ ] 两张卡片：每日安全清理（clean-safe）/ 每周只读扫描（scan），各带启用开关 + 时间（scan 加星期）控件
- [ ] 未配置任务显示默认值（clean-safe 03:30 关 / scan 周日 04:00 关）
- [ ] 安全说明三件套齐全：aggressive 刻意不可调度、只读写 `# mdc-managed:<任务>` 标记行、日志路径
- [ ] 保存成功 toast + 卡片底部展示**实际写入的 crontab 行**（等宽小字）
- [ ] `crontab -l` 对比：仅 `# mdc-managed` 行变化，用户其它定时任务逐字未动
- [ ] 禁用任务 = 行首注释行（时间配置保留）
- [ ] crontab 不可用上下文：控件禁用 + 短提示（完整授权步骤在顶部全局横幅），不发请求
- [ ] 与既有外部定时（如 WorkBuddy 夜间自动化）并存时无重复执行冲突（验收时二选一）

## 6. 设置视图

- [ ] 配置项全部中文标签（≥15 项）、aria 折叠可切换
- [ ] 构建衍生物分组、微信媒体保留月数、白名单应用缓存等高级项在列
- [ ] **工具自检面板**（自概览迁入）：缺失工具一目了然
- [ ] 保存后 `--show-config` 与面板一致
- [ ] 配置校验拒绝非法值（端口越界/路径逃逸/safe-manual 冲突）

## 7. 前端交互通用标准（「顺手度」对标）

- [ ] 明暗主题切换后**全部六视图**可读（重点：treemap 方块、徽标、等宽路径）
- [ ] 所有破坏性操作都有确认层且**按可逆性分级**：可还原操作=两段式按钮；不可逆操作（清空系统废纸篓/删快照/清空隔离区）=modal + 字面量/二次点击 + 「不可恢复」标识；计划任务保存（明确按钮）
- [ ] **服务/FDA 降级收敛为顶部唯一横幅** `#svc-banner`：授权指引全站唯一化，各 tab 不再各说各话
- [ ] 长任务均有 building 态 + 轮询（apps 重建 / dupes 全量哈希），不给死白屏
- [ ] 空态有解释性文案（非「无数据」裸提示）
- [ ] 错误降级不白屏：TCC（~/.Trash、MobileSync）、crontab 不可用、icon 404
- [ ] 零外部依赖（无 CDN/字体/图标库），断网可用
- [ ] 视图间 hash 路由可直达、刷新后保持
- [ ] 移动窄窗口不塌布局（表格可横向滚动）

## 8. 功能复刻对照（调研 → 落地全景）

| # | 功能 | 来源参考 | 状态 |
|---|---|---|---|
| 1 | Xcode 专项清理 | 三家 | ✅ 运行中跳过、Archives manual |
| 2 | Homebrew 缓存 | Pearcleaner/PureMac/Mole | ✅ |
| 3 | 全局开发缓存 27+ 类 | Pearcleaner/Mole | ✅ 进程守护 |
| 4 | 孤立残留扫描 | Pearcleaner+PureMac | ✅ 双向匹配 |
| 5 | AI 工具缓存 | Mole/PureMac | ✅ Claude Code 保最新 |
| 6 | 凭据黑名单 + TOCTOU | PureMac | ✅ 代码级 |
| 7 | 大文件/旧文件 | PureMac 口径 | ✅ 永不自动勾选 |
| 8 | 系统废纸篓管理 | Mole/PureMac | ✅ 双门禁 |
| 9 | 磁盘树图 | DaisyDisk/Mole | ✅ 纯 SVG |
| 10 | 浏览器 profile 缓存 | Mole | ✅ SW 站点数据不碰 |
| 11 | 安装包清扫 | Mole | ✅ Downloads 收窄 |
| 12 | iOS 备份报告 | Mole/CleanMyMac | ✅ TCC 降级 |
| 13 | 重复文件 | Mac Clean/PureMac | ✅ 报告性质（已迁清理视图） |
| 14 | 启动项报告 | Pearcleaner | ✅ 只读（已迁系统视图） |
| 15 | TM 快照管理 | Mole/PureMac | ✅ 回滚点拒删（已迁系统视图） |
| 16 | 计划清理 | CCleaner/PureMac | ✅ cron 托管 |
| 17 | 卸载器 | Pearcleaner/AppCleaner | ✅ 自愈列表+图标 |
| 18 | Trash-first + 还原 | 三家 | ✅（基线能力；2026-09-30 升级统一时间线） |

- [ ] 上表 18 项逐项在 UI 走查一遍（对照本文各节）

## 9. 刻意不做（验收时确认没有越界复刻）

- [ ] 无 App Lipo / 翻译修剪（PureMac 2.9.5 撤回先例）
- [ ] 无常驻废纸篓监控（Sentinel 路线）
- [ ] 无恶意软件/VPN/隐私擦除（MacKeeper 路线）
- [ ] 无「内存释放/提速」宣传口径（PureMac 诚实口径）
- [ ] 无 SmartDelete 常驻拦截（Web 架构不可行）

## 10. 已知差距（验收时明示，不算失败项）

| 差距 | 来源 | 现状与建议 |
|---|---|---|
| Mail 附件缓存 | 调研 #15 | 低优先未排期；Mole/PureMac/CleanMyMac 均有 |
| 维护任务集（DNS/Spotlight 重建等） | 调研 #16 | 超出「清理」定位，暂缓 |
| dupes 只报告、不可勾选清理 | Mac Clean/CleanMyMac 可操作 | 报告性质是刻意决策（面板已迁清理视图并注明）；若需操作化，加「保留一份、其余隔离」 |
| 相似照片查找 | BuhoCleaner/CleanMyMac/PureMac | 未做；PureMac 也只比不删 |
| Safari 专项 profile 缓存 | Mole 浏览器 8 款含 Safari | 当前 browser-cache 覆盖 Chromium 系 + Firefox；Safari 缓存部分由 `~/Library/Caches` 的 app-cache 覆盖，专项拆解未做（FDA 后复验是否仍缺席） |
| 多位置废纸篓（外置盘） | CleanMyMac | 仅 ~/.Trash |
| 真实 free vs purgeable 区分 | DaisyDisk | treemap 基于分类体积，未做 purgeable 语义 |

---

## 验收记录

### 2026-09-30 信息架构重组（本会话执行）

**范围**：六阶段重组（P0 逻辑纠错 / 概览只读化 / 历史域统一时间线 / 导航 7→6 / P2 状态打磨 / 文档同步），门禁全绿发布。

- **门禁**：89/89 单测、105/105 DOM、模板一致 [OK]
- **新增断言锁定**：概览零执行入口、执行记录面板移除、整模式语义标注、trash/clear 守卫、全局降级横幅存在
- **附带修复 P0**：单测 service uninstall 曾无条件 bootout 生产 LaunchAgent（每次跑测试悄悄卸载常驻服务）——改读目标 plist 自身 Label、仅真正加载时才 bootout，+2 回归测试
- **待人工**：launchd 服务重载后真机过一遍六视图（含明暗主题），重点验证统一时间线与全局横幅

### 2026-09-28 自动验收（重组前基线，存档）

**全过项：**

- **§0 门禁**：80/80 单测、95/95 DOM（旧基线）、模板一致 [OK]、12 GET 端点 200、POST 门禁 4/4
- **§2 清理**：manual 永不自动勾选；reason 汉化全覆盖（52 规则零漏翻）；浏览器运行中其候选缺席
- **§3 卸载**：卸载即时移除；外部删除自愈；Trash-first 隔离
- **§4 历史**：EMPTY TRASH 逐字门禁实测 400；TCC 降级实测
- **§5 报告（旧）**：启动项 30 项解析；快照回滚点拒删 400；dupes 真实 25 组/2.1G
- **§6 计划任务**：aggressive 400 拒绝实测；crontab 降级实测；禁用=注释行（单测往返）
- **§9/§10**：18 项复刻对照 + 6 项刻意不做静态审计全过

**验收中发现的新事实（仍有效）：**

- Safari 专项缓存缺席是目录自身 TCC 保护（非过滤器排斥），FDA 后复验；若仍缺席再考虑专项拆解。

| 日期 | 门禁 | 人工走查 | 结论 |
|---|---|---|---|
| 2026-09-28 | 80/80 · 95/95 · [OK] | 待人工 5 项 | 自动验收通过（重组前基线） |
| 2026-09-30 | 89/89 · 105/105 · [OK] | 服务重载后真机六视图走查 | 重组发布完成，待真机验收 |
