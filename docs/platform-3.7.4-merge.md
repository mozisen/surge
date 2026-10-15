# 平台接口线与 3.7.4 预览合并

预览版本：`3.7.4-preview.2`。测试分支：`codex/platform-3.7.4`。仅发布分支，不更新 GitHub Release，不部署服务器。

把两条互不包含的未发布线合到一起：

- `codex/singbox-update-state-fix`（3.7.4-preview.1）：包含正式版 3.7.3 的配额执行、普通 SS 用户与 Telegram cron 修复，以及 Sing-box 核心更新状态修复。
- `codex/ss-traffic`（3.7.3-preview.5）：平台只读接口、共享渲染器、面板独立配额、SS/SS2022 单用户流量采集，以及 `platform/` 下的面板与 Agent（0.3.0-preview.8）。

## 冲突与取舍

只有两个文件出现文本冲突。

- `reset_monthly_user_traffic`：采用 3.7.3 的逐用户重置，覆盖 Xray、Sing-box 与 Snell，只恢复因超额停用的用户，写入成功后才标记当月已重置。保留平台线的约束：带 `panel_quota` 字段的面板计费用户跳过，不清零也不恢复，由 Agent 按面板周期重置。
- `tests/singbox-stats-query.sh`：两侧加载的函数取并集。

平台线原先的月重置只处理 Xray，并把所有非面板用户一律设为启用；合并后手动停用和到期用户不再被月重置恢复，这是 3.7.3 的既有行为。

`tests/platform-billing.sh` 随之改为加载逐用户重置所需函数，并增加 Sing-box 用例：面板计费用户（含配额为 0）不变，手动停用的旧用户清零但保持停用。

`platform/vendor/vless-server.sh` 与根目录脚本逐字节一致，`platform/agent/runtime.py` 的 `UPSTREAM_SHA` 和 `platform/vendor/README.md` 已同步。

## 验证

- Shell 隔离回归：`tests/*.sh` 共 19 个，18 个通过；`singbox-stats-live.sh` 需要真实统计核心，本次未运行。
- 平台：90 项 unittest 中 88 项通过、1 项跳过；`test_qr_auth_expiry_and_result_allowlist` 因本地环境无法安装 `qrcode` 依赖而未能运行，以 GitHub Actions 结果为准。`node --check web/app.js`、`install-form.cjs`、`traffic-display.cjs` 通过。
- `bash -n vless-server.sh` 通过。`git diff --check` 只报告脚本中原有的行尾空格，本次合并未新增。

以上均为隔离或模拟测试，没有在真实 VPS、真实客户端或线上面板上验证。节点升级 Agent 不会覆盖已有主脚本，需单独更新。

## 测试面板部署

2026-10-09 经用户要求，通过 termark 在 vps.town 执行 `vaio-panel update --ref dc1c60b8da117eeb74feb889fe0fbc2d0272b11b`，面板从 `37df3be` 升级到 `dc1c60b`，版本号保持 0.3.0-preview.8。升级器测试 91 项通过、2 项跳过（日志中的“已恢复旧程序”来自临时目录内的回滚自测）；服务运行正常，`/` 返回 200，`web/app.js` 的 SHA-256 与本地一致。备份位于 `/var/backups/vaio-panel/1791530497563494975`，日志位于 `/root/vaio-update-dc1c60b.log`。节点 Agent 与主脚本未更新，月重置逻辑尚未在真实节点验证。

## 面板 0.3.0-preview.9

- 账号设置的密码下限改为 8 位（`9595530`）后，`vaio init` 同步改为 8–128 位，README 同步；新增 init 的 7/8 位边界测试。
- 本地验证：shell 回归 18 项通过（live 用例未运行）；unittest 92 项通过、2 项跳过；`bash -n` 通过，vendor 副本一致。本机无 Node，前端检查以 GitHub Actions 为准（`app.js` 本次未改）。
- 面板与 Agent 版本号升为 `0.3.0-preview.9`，前端资源缓存参数同步更新。脚本版本仍为 3.7.4-preview.2。
- 2026-10-09 通过 termark 将 vps.town 面板升级到 `5d52f3f`（0.3.0-preview.9）：升级器测试 92 项通过、2 项跳过，服务正常，首页资源版本为 preview.9，`index.html` SHA-256 与本地一致。备份 `/var/backups/vaio-panel/1791530821000064419`。节点 Agent 与主脚本仍未更新。
- 节点暂不更新（用户决定）。原测试节点 ovh-vps-1 已在面板中吊销删除；当前唯一在线节点"香港维多利亚"有真实用户流量，未获授权，Agent 仍为 preview.8、脚本仍为 3.7.3-preview.5。合并后的月重置逻辑尚未在真实节点验证。
- 协议安装界面改版：第一步改为协议卡片（内核、传输方式、已安装数量），第二步表单分为基础设置、证书设置和默认折叠的高级设置；「生成」按钮移到输入框右侧，弹窗加宽到 760px，头部和底部固定。提交参数与改版前一致：88 种协议、版本和证书组合逐项比对无差异。`install-form.cjs` 新增卡片选择路径。本地用模拟节点在 1280×860 和 375px 下截图核对；本机无 Node，前端测试用 macOS jsc 加兼容层运行通过，以 GitHub Actions 为准。
- 2026-10-09 通过 termark 将 vps.town 面板升级到 `c39fec1`（安装界面改版，版本号仍为 0.3.0-preview.9）：升级器测试通过，服务正常，`app.js`、`style.css` 的 SHA-256 与本地一致。备份 `/var/backups/vaio-panel/1791559034729366566`。未在真实节点执行安装。

## 面板 0.3.0-preview.10：黑白运维控制台视觉重设计

- 版本号升为 `0.3.0-preview.10`（`3e82efe`），前端资源缓存参数同步。脚本版本仍为 3.7.4-preview.2，Agent 代码未改。
- 只改视觉与布局（Trellis 任务 `panel-ui-redesign`，用户确认 S1–S4、不改文案）：
  - 设计 token 只用灰阶（`#000`…`#fff`），圆角分层 3/6/8/12px，面板去掉阴影；系统字体栈、全局等宽数字，等宽字体只用于端口、命令等机器字符串（`f510186`）。
  - 状态徽章用形状区分：实心点（在线/运行中）、勾（已完成）、空心环（离线/停止）、虚线环（等待）、黑底反白（失败/待核对）。
  - 去掉顶栏，刷新状态、账号设置、退出移到侧栏底部；手机端为吸顶栏加单行横滑导航（`f510186`）。
  - 统计卡合并为读数带，数值与单位分开排；服务器列表改为机架行，内存、磁盘用 10 段刻度条（`a027d0e`）。
  - 节点详情、任务、流量、监控、备份、审计页面统一表格密度，数值列右对齐（`88b7a01`）；全部弹窗统一头部、表单节奏和底栏，安装弹窗只改 CSS（`962bc58`）。
  - 资源历史图表增加参考线、刻度、起止时间和面积填充，断线区间留白，数据计算不变（`e741ecc`）；刻度条无数据时的无障碍语义与触屏 44px 目标修正（`f319d02`）。
- 未改动：后端接口、全部元素 id 与 `data-action`、`submitTask` 参数、`installPortCandidate`…`editUser` 代码段（与改版前逐字节一致）。
- 本地验证（模拟节点，scratchpad 预览面板）：
  - 1280×860 与 375px 截图核对全部 10 个页面和 16 个弹窗，页面无横向溢出、无脚本错误。
  - 弹窗内无溢出，长安装表单的主按钮始终可见。
  - unittest 92 项通过、2 项跳过；`bash -n vless-server.sh` 通过；shell 回归未运行（脚本未改）。
  - 本机无 Node：用 macOS JavaScriptCore 做了 `app.js` 语法检查，并按 `traffic-display.cjs` 的断言运行流量代码段，均通过。`node --check`、`install-form.cjs`、`traffic-display.cjs` 以 GitHub Actions 为准。
- 未在真实节点上操作，节点 Agent 与主脚本仍未更新（用户暂缓）。
- GitHub Actions：`6f7630a` 的 Platform regression 通过（run 38202847858，Python 3.9/3.12 与镜像构建）。其中包括 `node --check web/app.js`、`install-form.cjs`、`traffic-display.cjs`。
- 2026-10-12 通过 termark 在 vps.town 执行 `vaio-panel update --ref 6f7630ada3f9276b40c2bee2eafdb6f136f837e7`，面板从 `c39fec1` 升级到 `6f7630a`（0.3.0-preview.10）。结果如下：
  - 日志 `/root/vaio-update-6f7630a.log` 显示 `EXIT=0`。升级器测试 92 项通过、2 项跳过；日志中的「已恢复旧程序」来自临时目录内的回滚自测。
  - `/opt/vaio-panel/REVISION` 为该提交，服务 active，本地 `127.0.0.1:18080` 与公网首页均返回 200，资源版本为 preview.10。
  - 服务器上 `web/app.js`、`web/style.css` 的 SHA-256 与本地一致。
  - 备份位于 `/var/backups/vaio-panel/1791778417878133763`。
- 未在测试面板上登录做界面验收，也未操作节点。

## 统一用户管理：脚本 3.7.4-preview.3 / preview.4，面板 0.3.0-preview.11

脚本新增可独立运行的节点级统一用户和事务写接口 `--api account_apply`；Agent 上报统一用户并执行 `platform_apply`；面板新增「用户管理」，跨节点合计流量、双向同步。版本、改动和测试结果见 `docs/platform-user-management.md`。2026-10-12 已将测试面板 vps.town 升级到 `6b819ef`（0.3.0-preview.11），并在数据库副本上完成接口验收；节点未操作。

## 脚本 3.7.4-preview.13：Sing-box 只用统计版预编译包（面板 1.4.1）

- 改动：Sing-box 的全新安装、核心管理更新（菜单改为「最新统计版 / 指定统计版版本」）、指定版本、`install_singbox ... true` 与统计修复，都只使用 `mozisen/surge` 分支 `singbox-stats-binaries` 中本机（`linux-架构-libc`）已发布的版本；不再安装或提示官方版本，官方最新版本只在版本信息里作参考。未发布统计包的版本（例如官方 1.14.3）在下载或停服务之前被拒绝。只有本机架构没有预编译包（如 armv7）时才安装官方版本并提示无用户统计。版本缓存与菜单状态使用伪仓库 `mozisen/singbox-stats`。
- 统计修复的版本检查由「必须是官方最新 1.14 稳定版」改为「当前版本必须有已发布的统计包」，否则提示先更新到最新统计版。
- 同步：`platform/vendor/vless-server.sh`、`UPSTREAM_SHA`（`4e0fa100…`）与 `platform/vendor/README.md`；面板与节点程序 1.4.1（一键更新节点程序时推送新脚本）。
- 测试：`bash -n` 通过；shell 回归全部通过（`singbox-stats-live.sh` 需真实统计核心，未运行）；改写 `tests/stats-platform.sh`（按本机平台列出统计版并按数字排序、缓存回退、修复门槛）与 `tests/singbox-stats-update.sh`（所有安装 / 更新入口只用统计版、未发布版本拒绝、无平台包才退回官方）。`_install_singbox_stats_fresh` 直接写 `/usr/local/bin`，未在本机运行。unittest 245 项（跳过 2 项）与三个 cjs 通过。**真实节点验收**：未执行。

## 脚本 3.7.4-preview.14：Snell v5 只取 5.x（面板 1.4.3）

- 改动：`surge-networks/snell` 版本源只代表 Snell v5，最新版本、版本列表与后台缓存只取发行说明中的 5.x（新增 `_get_snell_v5_versions_from_kb`）；`_init_version_cache` 作废旧脚本写入的非 5.x 缓存。此前 v5 显示「稳定版本 v6.0.0 / 可更新」，更新会被 `install_snell_v5` 的 5.x 校验拒绝。
- 面板 1.4.3 同时修复关联用户重复新建（节点程序任务完成后立即刷新状态；面板不对已同步关联重复新建；失败关联确认后自动恢复）。
- 测试：新增 `tests/snell-v5-versions.sh`；shell 回归全部通过（`singbox-stats-live.sh` 未运行）；unittest 与三个 cjs 通过，新增重复新建与失败恢复两项（已确认在旧逻辑下失败）。**真实节点验收**：未执行。

## 脚本 3.7.4-preview.15：多用户 SS / SS2022（面板 1.5.0）

- 脚本：Sing-box 按用户统计加入 SS2022；统计配置检查加入 SS2022；面板安装的 SS2022 在加入第二个用户时把第一个用户的密钥记为服务端密钥（`db_account_member_new`），渲染器 / `_ss2022_is_multi` / `generate_singbox_config` 缺少 `password` 时回退到第一个用户的密钥；新成员密钥长度按方法（修复 chacha20-poly1305 用 16 字节）。
- 节点程序：去掉 SS/SS2022「面板安装 + 单用户」的写入限制（10-05 添加，早于脚本 10-12 的多用户支持）；`ss_user_stats` 与渲染器一致判断按用户或按入站统计；统计状态、多用户 SS2022 导出（服务端密钥:用户密钥）、实例中新增 SS 用户（SS2022 生成正确长度密钥并保留服务端密钥）。
- 测试：新增 `tests/ss2022-multiuser-stats.sh`、`tests/ss2022-multiuser-accounts.sh`；改写 `platform/tests/test_shadowsocks.py`（多用户写入、端口修改、删除回单用户、导出、统计状态）。真实 Sing-box 配置校验（`VAIO_TEST_SINGBOX`）与真实节点验收未执行。
