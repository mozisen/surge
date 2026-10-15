# 上游来源与固定版本

`vless-server.sh` 是本提交根目录同名脚本的逐字节快照，保留原作者声明：

- 仓库：https://github.com/mozisen/surge
- 分支：`codex/platform-3.7.4`
- 提交：与当前根目录脚本同一 Git 提交；使用下列摘要固定内容。
- 版本：`3.7.4-preview.14`（Snell v5 只取 5.x 版本）
- SHA-256：`397e51e6be49baa287c4488b4a86867e27873625b8081c0032d7b0f44220b09b`

3.7.4-preview.14：Snell v5 的最新版本、版本列表与后台缓存只取发行说明中的 5.x（发行说明同时列出 6.x，此前把 6.0.0 当作 v5 最新版本，显示「可更新」且更新会因版本校验失败）；启动时作废旧脚本写入的非 5.x 缓存。上一固定版本为 3.7.4-preview.13，SHA-256 为 `4e0fa1007a145dea1d3b782dfe8367754e701a3ebf5b8c0eec41770ec07ce9c7`。

3.7.4-preview.13：Sing-box 的全新安装、核心管理更新、指定版本与统计修复都只使用 `mozisen/surge` 分支 `singbox-stats-binaries` 中本机（架构 + libc）已发布的版本，不再安装官方版本；本机架构没有预编译包时才安装官方版本并提示无用户统计。上一固定版本为 3.7.4-preview.12，SHA-256 为 `f3e8466b6cf1bffae24110643f57b4b5cbe9e980660d4a334e59605bfeb1af49`。

原快照未提供许可证，不对该文件另行声明许可证。

最初固定版本为 3.7.3-preview.1，提交 `a0dcff02383fd8cda48d9e54ebe95027367e91cd`，SHA-256 为 `fc38833fc12d9f1bff8adfa4f12ac1f3aca41aee5978059af68fb27222044c32`。本次加入共享渲染器及 CLI 对已接管实例的适配。

Agent 只加载 CLI 分派前的定义，调用白名单内的二进制安装器与 Snell 计数器辅助函数；配置渲染只提取固定的 `_platform_render_inbound` 函数，通过标准输入传递私有数据，不执行菜单。事务仍由按实例定位的 Python Bridge 管理，不动态下载最新脚本。

新增接口检查调用完整 CLI 的 capabilities/inventory，缓存 60 秒，只上报版本、接口状态和数量。不转发原始响应，不使用其包含流量的 revision 派发写任务。新接口的 write_actions 为空；写入能力按 Agent 明确声明的组合开放，继续使用 Python 适配器；其他协议不因此开放。未知能力契约按不可用处理。

2.2 兼容扩展：共享渲染器识别面板独立配额；原脚本月重置跳过面板计费用户，由 Agent 重置且保留手动停用状态；旧用户仍遵循原脚本策略。统计成功后保存分内核/实例采样时间，面板拒绝在统计不可用时新增配额。Agent 不重复读取或清零内核统计。

本轮之前的共享渲染版为 3.7.3-preview.2，SHA-256 为 `4c83a5cda311efd5969906467088b49e0daeea5d97ffd8cc0b57c7369788e1f8`。本轮同时修复 Bash 5 严格错误模式下首次统计增量导致同步提前退出的问题。

本次共享渲染器增加 Sing-box 单用户 SS / SS2022，禁用或到期时替换为随机有效密钥，不覆盖其他入站。

SS 单用户入站采集：按唯一端口和标签读取非清零计数，累计与基线原子写入唯一用户；依赖带 with_v2ray_api 的 Sing-box、grpcurl 与周期 --sync-traffic。必须同步更新节点主脚本，Agent 升级不会覆盖已有主脚本。

合并前的平台接口线固定版本为 3.7.3-preview.5，分支 `codex/ss-traffic`，SHA-256 为 `7b6414342f0f02fef269c366d894327796efc62f0b6eacab67f1adab61cc9117`。本次合并入正式版 3.7.3 的配额执行与修复，以及 3.7.4-preview.1 的 Sing-box 核心更新状态修复。月重置沿用 3.7.3 的逐用户重置（覆盖 Xray、Sing-box 与 Snell，仅恢复因超额停用的用户），并继续跳过面板计费用户。

3.7.4-preview.3 新增节点级统一用户（db.json 顶层 `accounts`，协议用户的 `account_id`）。成员协议用户的到期、配额、启停由脚本派生，共享渲染器与 Agent 无需修改即可正确执行；面板配置版本号忽略统一用户的用量字段。上一固定版本为 3.7.4-preview.2，SHA-256 为 `7ce9467d90298512b62ef4072fa977a98985850074150802981e855511ab7aa6`。

3.7.4-preview.4 新增 `--api account_apply` 与 `result` 查询：一个请求内的统一用户操作作为事务执行（`$CFG/.txn.lock`、幂等记录 `$CFG/api-results`、备份 `$CFG/api-backups`、失败回滚）。`capabilities` 保持 `stage=read_only_foundation` 与 `write_actions=[]`，另以 `accounts_api.version=1` 声明，现有 Agent 的只读接口检查不受影响。inventory 增加 `accounts` 与用户的 `account_id`，仍不含凭据。

3.7.4-preview.5 新增 `meta.user_authority`（script/platform）。平台模式下本机菜单的用户写操作全部禁用；切换到平台时清空受管实例的全部用户与凭据（行级凭据换成随机值）、统一用户、TG 绑定与用户路由，独立协议不受影响。`--api account_apply` 新增单独成请求的 `set_authority`，脚本模式下拒绝其他统一用户写操作；`accounts_api.version` 升为 2，能力声明与 inventory 带 `user_authority`。

3.7.4-preview.6 新增协议用户能力表（multi/single/none 与统计方式，能力声明 `user_modes`、inventory 每实例 `user_mode/user_stats/user_available`，`accounts_api.version=3`）；SS2022 在 Xray、Sing-box 与共享渲染器中支持多用户（实例 password 为服务端密钥，旧的单密码实例保持原格式），共享渲染器的 SS 传统版支持多用户；Snell 新增成员改为分配到空实例；新增只读的 `--api account_share`；以平台为准时安装空实例。

3.7.4-preview.7：SOCKS（每个端口实例一个用户，Xray 入站统计，policy 开启 statsInbound）与 Snell+ShadowTLS、Snell v5+ShadowTLS、SS2022+ShadowTLS（每台节点一份，归一个用户，nft 端口计数）接入用户管理。分配时更换凭据与 ShadowTLS 握手密码；唯一用户停用、到期或超额时 SOCKS 换成随机账号、ShadowTLS 停止前后端服务。没有 users 的旧实例行为不变。

3.7.4-preview.8：以平台为准的节点不再使用本机 TG 通知。切到平台时（以及已是平台模式的节点在流量同步、机器人轮询或打开菜单时）清空 `telegram.json` 为默认值、删除数据库旧的 `.telegram`、移除用户机器人轮询 cron；平台模式下管理员告警、用户提醒、每日报告都不发送，TG 菜单只读。以脚本为准的节点不变。上一固定版本为 3.7.4-preview.7，SHA-256 为 `b472a93ef874b00386e2ad12ec20c22bb82ffc64642a5b244e39473512d3f117`。

3.7.4-preview.9：端口转发统一管理 Realm 与 nftables。Realm 规则补稳定 id；nftables 启用中的规则以 nft.sh 兼容的 `/etc/nftables.d/port-forward.conf` 为准（nft.sh 改动也能同步），备注与停用规则存于 `realm/rules.json`。菜单新增修改、启用/停用；`--api` 新增 `forward_apply`（单操作事务、幂等、按快照拒绝过期修改、失败回滚）与 inventory 的 `forwards`/`forward_status`（状态与流量），能力声明 `forward_api.version=1`。上一固定版本为 3.7.4-preview.8，SHA-256 为 `1e36ec7ef9b031f3b68a15b56a9914932fefcabf66f406ed042a96a63fc0c846`。

3.7.4-preview.10：节点已注册 Vaio 节点程序（存在 `/etc/vaio-agent/config.json`）且为平台模式时，「用户管理方式」菜单不再提供切回「以脚本为准」，提示由面板统一管理；未注册的节点不变。上一固定版本为 3.7.4-preview.9，SHA-256 为 `47c23156bf1b6b13d9cd034cdf3d1a3b75235d373dbf2ac3513eab6db1c684a3`。

3.7.4-preview.11：`account_apply` 在节点还没有 `db.json`（从未安装过协议）时先建立空数据库，平台自动切换用户管理方式不再因「数据库无效」失败。上一固定版本为 3.7.4-preview.10，SHA-256 为 `6dc7d8d60c295dfef529dbe124df966cb7484dbf2af2ad7c7b786d5d98036c5a`。

3.7.4-preview.12：`account_share` 新增可选 `port`（`VAIO_SHARE_PORT`），中转线路导出时地址与端口换成第一层中转入口，凭据仍取落地实例；Snell 导出也遵循平台指定的地址与端口。上一固定版本为 3.7.4-preview.11，SHA-256 为 `c03524907c1a7ea107ab03f2feba39465ee42ffbf813703667a508d8e047dcb5`。
