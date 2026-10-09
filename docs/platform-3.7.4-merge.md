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
