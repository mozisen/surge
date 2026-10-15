# Vaio Panel 正式版发布流程

面板在本仓库 `platform/` 开发，正式版同步发布到 [mozisen/vaio-panel](https://github.com/mozisen/vaio-panel)（仓库根即 `platform/` 的内容）。

## 1.0.0（2026-10-14）

- 来源：surge `codex/platform-3.7.4`，面板与节点程序 1.0.0，内置节点脚本 3.7.4-preview.12。
- 经用户确认：vaio-panel 原有内容（0.2.x 面板及 6 个 `codex/*` 分支）清空，`main` 强制替换为单个 1.0.0 提交，打标签 `v1.0.0`。
- 安装与升级默认来源改为 `mozisen/vaio-panel`（`install-panel.sh` 的 `VAIO_SOURCE_REPO`/`VAIO_SOURCE_REF`，`vaio-panel update --repo/--ref`，默认 `main`）；仍可用 `mozisen/surge` 安装或升级预览版，两种源码包布局都能解包。
- 发布结果：vaio-panel `main` 为单个提交 `264cba0`（「Vaio Panel 1.0.0」，作者沿用本仓库提交身份），标签 `v1.0.0`；6 个 `codex/*` 旧分支已删除，远端只剩 `main` 与 `v1.0.0`。导出目录在本地独立通过 unittest 183 项（跳过 3 项，含仅在单仓库时运行的脚本副本比对）与三个 cjs 测试；vaio-panel 的 GitHub Actions（推送 main 与标签各一次）regression 3.9/3.12 与镜像构建全部通过。
- GitHub Release：本机没有可用于创建 Release 的 GitHub CLI 凭据，需在网页由标签 `v1.0.0` 创建（标题「Vaio Panel 1.0.0」，说明取 CHANGELOG 1.0.0 一节，勾选设为最新版本）。
- 已部署的 0.3.x 预览版面板：旧更新器只认 surge，先 `vaio-panel update --ref codex/platform-3.7.4` 升到 1.0.0，之后默认从 vaio-panel 升级。

## 发布步骤

1. 在 surge 完成改动、测试与 CI，版本号写入 `platform/vaio/__init__.py`、`platform/web/index.html`、`platform/CHANGELOG.md`。
2. 导出：`git archive <提交>:platform` 解包到空目录，确认 `python -m unittest discover -s tests` 与三个 cjs 测试在导出目录独立通过。
3. 在导出目录提交（作者与提交者均为 `mozi <49814846+mozisen@users.noreply.github.com>`，关联 GitHub 账号 mozisen，不使用本机姓名），推送到 vaio-panel `main`，打标签 `v<版本>` 并推送；在 GitHub 由标签创建 Release，标为最新正式版。
4. 在本文件记录版本、来源提交与验证结果。预览版不发布到 vaio-panel。

## 1.1.0（2026-10-14 发布到 vaio-panel）

- 发布结果：在 vaio-panel `main` 上追加提交 `bf8cdd2`「Vaio Panel 1.1.0」（来源 surge `484d66e`，不改写历史），标签 `v1.1.0`。发布目录本地独立通过 unittest 194 项（跳过 3 项）与三个 cjs 测试；vaio-panel 的 Actions（main 与标签各一次）全部通过。
- 远端另有标签 `v1.0.0：`（末尾为中文冒号），是网页创建 1.0.0 Release 时产生的，Release「Vaio Panel 1.0.0」挂在该标签上；`v1.0.0` 标签本身也存在。未改动，待用户决定是否整理。
- 1.1.0 的 GitHub Release 需在网页由标签 `v1.1.0` 创建。

- 安装：域名留空使用本机公网 IP（HTTP，`VAIO_ALLOW_HTTP=1`），自定义面板端口（域名默认 443、IP 默认 8080）；Nginx、证书与 `VAIO_PUBLIC_URL` 统一由 `scripts/panel-address.py`（root）生成，失败恢复原文件。
- 面板地址：面板写 `/var/lib/vaio-panel/address-request.json`，`vaio-panel-address.path` 触发 root 辅助程序绑定或更换域名、关闭旧地址；面板以新地址启动时为已接管节点排队 `agent_set_url`（节点验证新地址 HTTPS 后改写配置）；旧 IP 或旧域名保留到「关闭旧地址」。1.0.0 升级时由 `update-panel.py` 补装辅助服务。
- 卸载：`vaio-panel uninstall [--yes] [--backup 文件]`、`vaio-agent uninstall [--yes]`。
- 测试：新增 `tests/test_panel_address.py`、`tests/test_uninstall.py`、`tests/platform-users.cjs` 面板地址一组；unittest 与 cjs 全部通过。**真实验收**：未执行（尚未在 VPS 上实际安装 IP 模式、绑定域名或卸载）。

## 提交身份更正（2026-10-14）

- 经用户确认，vaio-panel 的两个提交与标签改写为作者 `mozi`（GitHub noreply 邮箱，关联 mozisen），文件内容（tree）不变，日期与说明不变，强制推送 `main` 与 `v1.0.0`、`v1.0.0：`、`v1.1.0` 三个标签。
- 新哈希：1.0.0 `264cba0` → `08537b7`，1.1.0 `bf8cdd2` → `359e780`。上文记录的旧哈希已不在远端。surge 仓库的提交按项目规则不改写。

## 1.2.0（2026-10-14 发布到 vaio-panel）

- 发布结果：在 vaio-panel `main` 上追加提交 `8979537`「Vaio Panel 1.2.0」（来源 surge `365822e`，作者 mozi），标签 `v1.2.0`。发布目录本地独立通过 unittest 205 项（跳过 3 项）与三个 cjs 测试；vaio-panel 的 Actions（main 与标签各一次）全部通过。
- 1.2.0 的 GitHub Release 需在网页由标签 `v1.2.0` 创建。面板内的「面板更新」只读取版本标签，不依赖 Release。


- 服务器列表显示节点程序当前 / 最新版本，「一键更新节点程序」（`POST /api/nodes/upgrade-all`，返回已排队与跳过原因）。
- 面板更新：`vaio/updates.py` 读取 vaio-panel 的 `vX.Y.Z` 标签（缓存 6 小时，失败 30 分钟后重试）；`GET/POST /api/panel-update`，面板写 `/var/lib/vaio-panel/panel-update-request.json`，`vaio-panel-update.path` 触发 root 运行 `update-panel.py --from-request`（与命令更新相同的备份、测试、健康检查与恢复），状态写 `panel-update-status.json`。新装由 `install-panel.sh` 安装辅助服务，升级由 `update-panel.py` 补装；1.1.0 的更新器不认识该服务，因此 1.2.0 面板在打开「面板更新」时通过已有的地址辅助程序（`install_update_helper`）补装。
- 系统设置：账号与面板地址合并为一个对话框的两个标签。
- 测试：新增 `tests/test_panel_update.py`，`tests/platform-users.cjs` 增加版本列、一键更新、面板更新与系统设置；卸载测试覆盖新单元。**真实验收**：未执行（未在 VPS 上实际从面板更新或批量升级节点）。

## 1.2.1（2026-10-14 发布到 vaio-panel）

- 修复平台用户流量一直为 0：节点程序每分钟运行内置脚本 `--sync-traffic`（脚本的同步 cron 只随其 TG 功能安装，平台接管后从未同步）。节点需一键更新到 1.2.1 后生效。
- 发布结果：vaio-panel `main` 追加提交 `f43a1c4`「Vaio Panel 1.2.1」（来源 surge `e0d6523`，作者 mozi），标签 `v1.2.1`。发布目录本地独立通过 unittest 211 项（跳过 3 项）与三个 cjs 测试；vaio-panel 的 Actions（main 与标签）全部通过。
- 诊断依据（经用户授权只读检查 vps.town）：victoria 无 sync-traffic cron、无同步日志；面板中 vps 与 victoria 的 traffic_status 均为 unavailable，用户 used 均为 0。**真实验收**：未执行（节点尚未更新到 1.2.1）。

## 1.2.2（2026-10-14 发布到 vaio-panel）

- 1.2.1 无法从 1.2.0 升级：vps.town 面板内更新两次均在「运行测试」一步失败并保留 1.2.0，原因是 `test_missing_update_helper_is_installed_through_address_helper` 依赖真实的 `/etc/systemd/system/vaio-panel-update.path` 不存在。1.2.2 改为 `SYSTEMD_DIR` 配置（测试用临时目录），并在导出目录模拟已安装辅助服务的环境复跑全部测试通过。v1.2.1 标签保留，不改写历史。
- 同时包含：打开「面板更新」立即重新检查（每分钟最多一次），后台缓存 1 小时；更新中左下角显示「更新中」。
- 发布结果：vaio-panel `main` 追加提交 `bbcb878`「Vaio Panel 1.2.2」（来源 surge `316cc59`，作者 mozi），标签 `v1.2.2`。发布目录本地 unittest 212 项（跳过 3 项）与三个 cjs 测试通过；vaio-panel Actions（main 与标签）通过。
- 经用户授权，已清除 vps.town 面板的 `update_check` 缓存（使其显示 v1.2.1）。**真实验收**：未完成（待在 vps.town 面板内更新到 1.2.2，并一键更新节点程序验证用户流量）。

## 1.3.0（2026-10-15 发布到 vaio-panel）

- 平台用户登录与「我的账号」页面（只看自己的用量、协议与中转线路连接、Telegram 自助绑定码），用户会话独立存储，所有管理接口拒绝用户会话；服务器状态圆点彩色（在线绿、待连接橙、离线红）。
- 发布结果：vaio-panel `main` 追加提交 `dadc764`「Vaio Panel 1.3.0」（来源 surge `12608c0`，作者 mozi），标签 `v1.3.0`。发布目录本地 unittest 221 项（跳过 3 项）在普通环境与模拟已安装面板辅助服务的环境下均通过，三个 cjs 测试通过；vaio-panel Actions（main 与标签）通过。
- **真实验收**：未执行（vps.town 面板尚未更新到 1.3.0，也未用真实用户登录测试）。

## 1.3.1（2026-10-15 发布到 vaio-panel）

- 新建用户即设置登录密码（编辑中重置），1.3.0 无密码用户升级时获得随机密码；备份恢复移入系统设置；界面精简（VAIO、「服务器」、删除页面描述与「更新于」、一键更新节点程序移到添加服务器左边、总览显示中转线路）；用户名不能与管理员相同。
- 发布结果：vaio-panel `main` 追加提交 `3b9abaa`「Vaio Panel 1.3.1」（来源 surge `f3420e9`，作者 mozi），标签 `v1.3.1`。发布目录 unittest 222 项（跳过 3 项）在普通与模拟已安装辅助服务环境下均通过，三个 cjs 测试通过；vaio-panel Actions（main 与标签）通过。
- **真实验收**：未执行。

## GitHub Release（2026-10-15）

- 经用户确认，通过用户已登录的 Chrome 在 vaio-panel 网页创建 6 个 Release：v1.1.0、v1.2.0、v1.2.1、v1.2.2、v1.3.0、v1.3.1（标题「Vaio Panel x.y.z」，说明取 CHANGELOG 对应一节；v1.2.1 说明开头注明无法从 1.2.0 升级、请用 1.2.2）。按版本顺序创建，最新版本为 v1.3.1。
- 1.0.0 的 Release 仍挂在 `v1.0.0：` 标签上，按用户选择未改动。

## 1.3.2（2026-10-15 发布到 vaio-panel）

- 面板按自己的时间判定到期后向所有节点下发停用（victoria 只读检查发现：节点按本地日期判断到期且多用户 SS 端口只每日检查，到期用户 TEST 仍可用 SS 26830）；中转线路显示用户到期等原因并隐藏连接导出；已到期、流量已用尽为红色。
- 发布结果：vaio-panel `main` 追加提交 `80c8836`「Vaio Panel 1.3.2」（来源 surge `5e96d28`，作者 mozi），标签 `v1.3.2`。发布目录 unittest 225 项（跳过 3 项）在普通与模拟已安装辅助服务环境下均通过，三个 cjs 测试通过；vaio-panel Actions（main 与标签）通过。已在网页创建 Release「Vaio Panel 1.3.2」，为最新版本。
- **真实验收**：未执行。

## 1.3.3（2026-10-15 发布到 vaio-panel）

- 代码审计修复（surge `be88535`…`8ef922a`）：登录限流按反向代理后的真实地址、root 辅助程序写状态文件不跟随符号链接、中转导出使用落地账号成员名、到期日只接受 YYYY-MM-DD、检查更新不占数据库写锁。
- 发布结果：vaio-panel `main` 追加提交 `2eb22d2`「Vaio Panel 1.3.3」（来源 surge `f4249f2`，作者 mozi），标签 `v1.3.3`。发布目录 unittest 233 项（跳过 3 项）在普通与模拟已安装辅助服务环境下均通过，三个 cjs 测试通过；vaio-panel Actions（main 与标签）通过。已在网页创建 Release「Vaio Panel 1.3.3」，为最新版本。
- **真实验收**：未执行。

## 1.4.0（2026-10-15 发布到 vaio-panel）

- 在面板更新内核（Xray、Sing-box 统计版、Snell v5/v6）：服务器详情单台更新、服务器页一键批量更新；节点程序先同步流量、备份、停启服务、失败恢复。节点需更新到 1.4.0，节点脚本未改动。
- 发布结果：vaio-panel `main` 追加提交 `df30d80`「Vaio Panel 1.4.0」（来源 surge `6aa0fa9`，作者 mozi），标签 `v1.4.0`。发布目录 unittest 245 项（跳过 3 项）在普通与模拟已安装辅助服务环境下均通过，三个 cjs 测试通过；vaio-panel Actions（main 与标签）通过。已在网页创建 Release「Vaio Panel 1.4.0」，为最新版本。
- **真实验收**：未执行（尚未在真实节点上通过面板更新内核）。
