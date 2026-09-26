# 功能对照清单（Feature Parity）

> 调研基准：2026-09-26。来源三部分：
> 1. 开源仓库源码拆解（Pearcleaner 5.4.3 / Mole 1.56.0 / PureMac 2.9.x，浅克隆于 /tmp/mdc-research/，重启即失）
> 2. 商用产品公开功能（CleanMyMac X / BuhoCleaner / DaisyDisk / AppCleaner / MacKeeper / MacCleaner Pro / AppZapper / CCleaner）
> 3. 本 skill 当前实现（scripts/mac_dev_cleanup.py + web_server.py + dashboard_template.html）
>
> 许可合规：只参考功能语义与实现思路，**不搬运代码**。Pearcleaner 为 Apache-2.0 + Commons Clause（禁止商用分发）；Mole、PureMac 参考自由度更高。PureMac 已在 2.9.5 **撤回** lipo 瘦身与翻译修剪（破坏代码签名致应用无法启动），验证了这两项"不做"的判断。

## 一、商用产品功能点清单（Checklist）

### CleanMyMac X（$39.95/年，全能标杆）
- [ ] Smart Scan 一键扫描（清理+保护+性能合一）
- [ ] 系统垃圾 16 类（用户/系统缓存、日志、语言文件、损坏偏好、损坏登录项、文档版本、iOS 备份、Xcode 垃圾、通用二进制、已删用户等）
- [ ] 邮件附件缓存（Mail/Outlook/Spark）
- [ ] 多位置废纸篓清空（含外置盘）
- [ ] 恶意软件扫描（签名级 3 深度）
- [ ] 浏览器隐私清理（历史/Cookie/缓存，带时间过滤）
- [ ] 卸载器：10 级匹配引擎、17+ Library 子目录、App Reset、久未使用应用检测
- [ ] 应用更新器（Sparkle feed）
- [ ] Space Lens 矩形树图钻取
- [ ] 大文件 & 旧文件（>50MB，按大小+最后访问时间）
- [ ] 重复文件（体积分组→部分哈希→全量哈希→inode 校验四级渐进）
- [ ] 文件粉碎器
- [ ] 菜单栏系统监控（CPU/内存/磁盘/电池/网络）
- [ ] 维护任务 10 项（释放内存、维护脚本、修复权限、重建 Launch Services、重建 Spotlight、清 DNS、瘦 TM 快照）
- [ ] 登录项/启动项管理（开关式）

### BuhoCleaner（$19.99 买断，性价比标杆）
- [ ] 一键闪清
- [ ] 大文件快速定位
- [ ] 重复文件 + 相似照片
- [ ] 启动项管理
- [ ] 实时状态监控 + 一键释放内存

### DaisyDisk（$9.99 买断）
- [ ] 磁盘可视化地图（扇形/树图），按颜色分类钻取
- [ ] 真实 free vs purgeable 区分展示
- [ ] 多盘/快照/云盘扫描

### AppCleaner（免费，卸载交互标杆）
- [ ] 拖放卸载
- [ ] 关联文件清单（勾选保留）
- [ ] SmartDelete：拦截手动丢废纸篓的应用，提示完整卸载
- [ ] 受保护应用警告

### 其余（定位不符，仅记录）
- MacKeeper：杀毒/VPN/身份监控套件；MacCleaner Pro：清理套装；AppZapper：撤销+Zap；CCleaner for Mac：计划清理+按应用排除

## 二、开源仓库功能点清单（源码拆解精炼版）

### Pearcleaner（卸载器深度标杆，核心文件 Logic/Locations.swift、AppPathsFetch.swift、ReversePathsFetch.swift）
- 卸载关联搜索 ~60 个路径常量：全套 ~/Library 子目录 + /Library + /usr/local/* + /private/var/db/receipts + DARWIN_USER_CACHE/TEMP_DIR + 动态枚举 App Support 子目录
- 匹配标识符 10 种：bundle ID、末两段、应用名变体、.app 文件名、entitlements、公司段、Team ID、去 helper/daemon 等 12 后缀的基础 bundle ID、去版本号名
- 搜索深度分级：普通 depth=1，~/Library 与 /Library 根 depth=2（命中非标准父目录时收编）
- ~20 条 per-app 条件规则（Xcode/VSCode/Chrome/JetBrains 的 include/exclude/force 表）
- Spotlight 补搜（NSMetadataQuery，strict/enhanced/deep 三档，5s 超时 500 条上限）
- **孤儿文件搜索**：22 个 Library 路径第一层 → 与全部已装应用标识符反向比对；排除 ~150 个系统词、UUID 文件名、用户黑名单；支持"关联到应用"手动归属
- **Sentinel**：独立 launch agent（FSEvents 监听 ~/.Trash，~2MB 内存），检测到 .app 入废纸篓即深链唤起卸载界面
- **开发环境清理 27 类**：Xcode 全套（DerivedData/Archives/DeviceSupport/模拟器/文档缓存）、Android Studio、JS 生态（npm/pnpm/bun/yarn/deno/go）、Python（pip/conda/pyenv/poetry/uv）、编辑器（VSCode/Cursor/Zed/JetBrains）、Cargo/Carthage/CocoaPods/Composer/Gradle/Maven/Nix/RubyGems/SwiftPM
- Workspace Storage 孤儿清理（VSCode/Cursor workspaceStorage 解析 workspace.json）
- App Lipo（手工解析 Mach-O fat header，dry-run 预估）、翻译修剪（.lproj，保 Base.lproj）
- PKG 管理（私有 PackageKit 枚举收据，app 存活时拒绝卸载）、插件管理（19 类插件路径）、Launch 服务只读查看器
- Homebrew 全家桶：包浏览/装卸/升级/pin、tap 管理、`brew cleanup`（dry-run 统计）、`brew doctor`、cask 收养（adopt）、自动更新调度
- 安全：Trash-first（时间戳 bundle 分组）、双层 Undo（内存+持久化历史页）、危险路径黑名单（/、/System、/usr、$HOME 等绝对拒绝）、uchg 锁定位处理、三级排除列表、特权 Helper 签名校验
- CLI（pear list/list-orphaned/uninstall/uninstall-all/remove-orphaned/helper）+ pear:// 深链 12 个 action

### Mole（CLI 安全工程标杆，核心 lib/clean/dev.sh 5356 行、lib/core/app_protection.sh）
- 子命令：clean（15 个 section）/ uninstall / optimize（20 项维护）/ analyze（Go TUI 树图）/ status（健康评分仪表盘）/ purge（项目工件）/ installer（.dmg/.pkg/.iso 安装包清扫）/ history / touchid / completion / update / remove
- 清理覆盖：系统级（/Library/Caches、崩溃报告、/var/log、14 天以上旧 macOS 安装器、GPU 缓存、TM 失败备份、APFS 本地快照 thinning）、用户级（~/Library/Caches 整扫、Logs、废纸篓、最近项目列表、Mail 附件、.crdownload 不完整下载、Handoff 剪贴板）、**浏览器 8 款**（Safari/Chrome/Chromium/Edge/Brave/Arc/Vivaldi/Firefox 全 profile 缓存 + SW CacheStorage，Chrome SW ScriptCache 明确保留护 MV3 扩展 + 浏览器旧版本目录）、云盘缓存（Dropbox/GDrive/OneDrive，运行中跳过）
- **开发缓存 29 步**：npm/pnpm(store)/uv/pip/pyinstaller/conda、Go GOMODCACHE/GOCACHE、Cargo、mise、Gradle（daemon 运行时跳过）、JetBrains Toolbox 旧版本、Xcode 全家桶（含 booted 模拟器探测与 simctl 孤儿 runtime）、Android NDK 旧版、Docker/OrbStack（运行镜像受保护）、Nix/Lima/Tart/UTM、**AI 工具**（Claude Desktop/Code 旧版本、Codex 缓存与 runtimes、Copilot CLI、Gemini、cursor-agent）
- GUI 应用缓存 20+ 分类：编辑器扩展、飞书/Lark SW、Notion Partitions、微信/企微容器（运行守护）、钉钉、Final Cut 生成缓存、剪映、Spotify、QQ 音乐、Setapp 等
- 卸载：bundle_id 反 DNS 校验防穿越、~30 类路径 + /Library 系统侧 16 类 + pkg 收据、执行链（bootout 登录项 → 停应用 → 删文件 → lsregister -u 注销）、同 bundle 多安装位兄弟存活保护
- **安全五层**：保护清单 ~250 行 case（EDR/端点安全/Keychains/iCloud/音频插件等）+ 默认白名单 + 强制安全白名单 + dry-run（NUL 分隔 ledger、防 symlink 提权的 staging 发布）+ 进程守护删除回调（删除前一刻复查目标进程）+ 每步超时预算 + 语义化退出码（124 超时/75 守护中止）
- analyze：并发扫描（dir/du 双信号量）、mdfind 快速大文件通道、top-N 堆、目录缓存、TM 快照检测、--json
- status：CPU/GPU/内存压力/SMART/网络 sparkline/电池健康/僵尸进程，健康评分 100 分制权重扣减
- Touch ID for sudo（/etc/pam.d/sudo_local，合盖自动跳过）、白名单交互管理、安装包清扫（zip 用 zipinfo 验载荷）

### PureMac（诚实口径 + 安全边界标杆，核心 Services/ScanEngine.swift、cli/Core/Safety.swift）
- 模块：卸载器、孤儿查找、Space Explorer、精确重复（SHA-256，硬链接不算重复）、相似照片（感知哈希，只比不删）、保护审计（Gatekeeper/FileVault/SIP/XProtect 只读）、性能检查（快照列表+删除）、cask 更新、Smart Scan 仪表盘
- 清理类别：System Junk（/Library 与 /var 深度 3）、用户缓存动态枚举（无硬编码应用表）+ **沙盒容器缓存**（Containers/*/Data/Library/Caches ≥1MB）+ HTTPStorages（默认不勾，活跃登录态）、AI 应用（Ollama/LM Studio，历史类默认不勾）、Mail 附件、废纸篓、大/旧文件（>100MB 或 >12 月且 >10MB，永不自动勾选）、Xcode 全家桶（simctl runtime delete 走官方 API，永不自动勾选）、Brew Cache（brew --cache 探测须落在白名单根内，剥离 HOMEBREW_* 环境变量防注入）、Node 缓存（CLI 探测命令输出必须符号链接解析后落在白名单根）、Docker 缓存（刻意不碰 VM 盘与配置根 + docker system prune 虚拟条目）
- **撤回功能先例**：lipo 与翻译修剪 2.9.5 整体下架（破坏签名），代码保留兜底拒绝
- CLI：clean dev/junk/ai/trash（--dry-run/--json/--force，dry-run 恒为 reportOnly）、purge 项目工件（--older-than 阈值，扫描根必须过白名单）、optimize 只读（明示"没有清理任何东西"）、ignore 保护路径文件、config
- 删除管线：删除前重跑 symlink 检查 + (device, inode) 身份比对（防 TOCTOU，"changed since scan" 跳过）、删除后重查身份报 failed、失败非零退出
- 孤儿安全策略：仅 8 个易失性根允许（Caches/Logs/SavedState/HTTPStorages/WebKit/CrashReporter），blockedFragments 拒 Preferences/Containers/LaunchAgents/Keychains 等 16 类，拒 com.apple.*，~35 个家目录点路径（.ssh/.aws/.gnupg/.kube）双重拦截
- 管理员授权：仅 EACCES/EPERM root 项触发，整批一次弹窗，NUL 分隔 + xargs -0 免引号陷阱，授权前逐条重校验，languageFiles 永不升级
- 计划清理：60s Timer + nextRunDate 过期拒绝（防同 UID 攻击者改 plist 立即触发）、onboarding 完成才启动、autoClean 需 ≥100MB 门槛
- 诚实口径：purgeable 只展示不清理、不吹 boost RAM/speed up、失败与 partial/不可达单独计数、相似照片因是估计值所以不删

## 三、对照矩阵与建议（本 skill）

现状基线：隔离+还原（Trash-first ✅）、卸载关联文件（8 类 Library 子目录）、运行中拒绝、路径穿越结构性拒绝、dry-run 默认、执行日志/历史、夜间自动化、白名单/排除/受保护路径、dashboard 五视图+图标。

### P0（2026-09-27 已落地 ✅：价值高、风险低、复用现有扫描+隔离机制）
| # | 功能 | 来源参考 | 现状 | 动作 |
|---|---|---|---|---|
| 1 | Xcode 专项清理 ✅ | 三家都有（Mole dev.sh 最全） | 已接入：DerivedData/DeviceSupport×4/XCTestDevices=aggressive，dt.Xcode 缓存/CoreSimulator Caches/swiftpm/Previews=safe，**Archives/模拟器 Devices=manual**；Xcode 运行中整类跳过；simctl runtime 删除留 P1 | 完成 |
| 2 | Homebrew 缓存清理 ✅ | Pearcleaner + PureMac + Mole | downloads/build logs=safe 已接入（`brew cleanup` 调用按需手动跑，scan 不启子进程保速度） | 完成 |
| 3 | 全局开发缓存 ✅ | Pearcleaner 27 类 + Mole 29 步 | pnpm store/go mod/conda/mise 接入；Gradle/go 有进程守护；既有 npm/uv/cargo/pip 不变 | 完成 |
| 4 | 孤立残留扫描 ✅ | Pearcleaner ReversePaths + PureMac 孤儿策略 | 已接入：仅易失性根、双向标识符匹配、跳过 com.apple.*/系统服务/开发工具/UUID/<1MB；manual 风险；标识符优先读 apps.json | 完成 |
| 5 | AI 工具缓存 ✅ | Mole AI 专项 + PureMac AI Apps | ollama/lmstudio 接入，模型 manual，Claude Code 旧版本（保最新）aggressive；本机无这些目录时类别自动缺席 | 完成 |
| 6 | 安全补强 ✅ | PureMac deniedUserRoots + inode 双查 | IMMUNE_PATHS 凭据黑名单（代码级）+ 隔离前 TOCTOU device/inode 双查（两条隔离路径） | 完成 |

### P1（第二批）
| # | 功能 | 来源 | 现状 | 动作 |
|---|---|---|---|---|
| 6 | 大文件/旧文件视图 ✅ | OmniDiskSweeper + BuhoCleaner + PureMac | `large-files` 类别已接入：扫 scan_roots，>100MB（`large-file`）或 >12月&>10MB（`old-large-file`），全部 manual 永不自动勾选；跳过已被前序 pass 覆盖的路径与符号链接，上限 200 条按大小排序 | 完成 |
| 7 | 整个废纸篓管理 ✅ | Mole/PureMac Trash Bins | `GET /api/trash` 返回 quarantine + system 两块（旧字段保留）；system 列 ~/.Trash 顶层项（大小/mtime，top 100）且默认**保留隔离区**；`POST /api/trash/empty-system` 需逐字 `confirm:"EMPTY TRASH"` + token；TCC 无权限时降级 available:false | 完成 |
| 8 | 磁盘树图 ✅ | DaisyDisk + Mole analyze + Mac Clean Space Lens | overview 加 squarified treemap（纯 SVG，top 12 + 其他），明暗主题适配，无新依赖 | 完成 |
| 9 | 浏览器缓存补全 | Mole 浏览器 8 款 | 仅部分（Edge 已验证可用） | 对照 Mole 路径清单补 Chrome/Arc/Brave/Vivaldi/Firefox profile 缓存；SW ScriptCache 保留 |
| 10 | 安装包清扫 | Mole installer | 无 | Downloads 扫 .dmg/.pkg/.iso/.xip + zip 载荷校验 |
| 11 | iOS 设备备份报告 | Mole/CleanMyMac MobileSync | 无 | ~/Library/Application Support/MobileSync/Backup 只读报告（删除须强确认） |

### P2（按需排期）
| # | 功能 | 来源 | 说明 |
|---|---|---|---|
| 12 | 重复文件查找 | Mac Clean 四级渐进哈希 + PureMac SHA-256 | 工程量最大；硬链接不算重复 |
| 13 | 启动项/登录项管理 | Pearcleaner 只读查看器 | 先只读清单（LaunchAgents/LaunchDaemons 过滤 com.apple.*），删除另议 |
| 14 | TM 本地快照 thinning | Mole tmutil thinlocalsnapshots | 高风险，须排除 com.apple.os.update-* 回滚点 |
| 15 | Mail 附件缓存 | Mole/PureMac/CleanMyMac | 小众，低优先 |
| 16 | 维护任务集 | Mole optimize 20 项 / OnyX | DNS/Spotlight 重建等，超出"清理"定位，暂缓 |

### 不做（有明确依据）
| 功能 | 依据 |
|---|---|
| App Lipo / 翻译修剪 | PureMac 2.9.5 因破坏代码签名整体撤回（"Users lost 21 bundles in a single run"）；与 Trash-first 原则冲突 |
| Sentinel 常驻废纸篓监控 | 用已有夜间孤儿扫描自动化替代，零常驻成本 |
| 恶意软件/VPN/隐私擦除 | 超出清理定位，属安全套件范畴（MacKeeper 路线） |
| 内存释放/boost | PureMac 口径：macOS 自管内存，此类宣传不可靠 |
| SmartDelete 拦截 | 需常驻进程+Finder 扩展，Web 架构做不了 |

## 四、安全机制对照（对齐项，随 P0 顺带补强）

| 机制 | Pearcleaner | Mole | PureMac | 本 skill | 建议 |
|---|---|---|---|---|---|
| Trash-first + 还原 | ✅ 双层 Undo | ✅ 默认 trash | ✅ 卸载/孤儿走 Trash | ✅ 隔离+manifest 还原 | 已达标 |
| dry-run | CLI 部分 | ✅ NUL ledger | ✅ reportOnly 恒不删 | ✅ 默认 dry-run | 已达标 |
| 路径黑名单 | ✅ 绝对拒绝 | ✅ ~250 行保护清单 | ✅ criticalRoots/deniedTrees/凭据根 | ✅ 受保护路径+穿越拒绝 | 补：凭据点路径黑名单（.ssh/.aws/.gnupg/.kube） |
| TOCTOU 防护 | 锁定位处理 | 进程守护回调 | ✅ (device,inode) 前后双查 | 无 | P0 顺带补 inode 身份校验 |
| 进程守护 | 杀运行中 app | ✅ 删除前一刻复查 | 运行中跳过 | 仅 WeChat/require_quit | 扩展到浏览器/Docker/Gradle daemon |
| 白名单强制合并 | 三级排除 | ✅ SAFETY_WHITELIST 恒合并 | ✅ ignore 保护后代 | 排除列表 | 补：强制安全白名单层 |
