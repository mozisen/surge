# 现状调研：用户、时限、流量（2026-10-12，HEAD 9a7ed2d）

脚本 3.7.4-preview.2，面板与 Agent 0.3.0-preview.10。只读调研，未改代码。

## 1. 节点脚本 `vless-server.sh`

### 用户存储
- 数据库 `/etc/vless-reality/db.json`，结构为 `{xray:{<proto>: row|[row...]}, singbox:{...}, meta:{...}}`。每个 row 是一个端口实例，`row.users[]` 是该实例的用户。
- 用户字段：`name`、`uuid`（各协议的凭据都放这个字段，包括密码和 PSK）、`quota`（字节）、`used`（字节）、`enabled`、`created`、`expire_date`（YYYY-MM-DD）、`disable_reason`（manual/quota/expired）、`resume_after_quota_reset`、`quota_enforced`、告警状态、TG 绑定、`routing`。
- **用户名在同一 (core, proto) 内唯一，跨端口共享**：`db_add_user` 在多端口时只加到第一个实例；`db_del_user`、`db_get_user` 会在全部端口里查找。原因是统计身份按协议计，Xray 用 `name@proto`，Sing-box 用 `proto-name`，与端口无关（vless-server.sh:617-792、2909）。
- 没有 users 数组的旧实例按 `default` 用户处理（凭据取 row 的 uuid/password/psk）。
- Snell 和 SS 是一个用户一个端口：Snell 每个实例有独立的 `snell_id`、服务和 nft 计数器；SS 单用户入站按入站计数归属唯一用户。

### 到期、配额、月重置、统计
- 到期：`--check-expire`（cron）调用 `check_and_disable_expired_users`，以 `disable_reason=expired` 停用。
- 配额：`_sync_all_user_traffic_unlocked`（cron，带 `-reset` 读取核心计数）把增量累加到 `used`；`_enforce_user_quotas` 对 `used>=quota` 的用户以 `disable_reason=quota` 停用。
- 月重置：节点全局一个重置日（文件 `TRAFFIC_MONTHLY_RESET_DAY_FILE`，默认 1 日，可关闭）。`reset_monthly_user_traffic` 清零 `used`，并恢复因配额停用的用户。**带 `panel_quota` 的用户会被跳过**，由面板计费自行处理。
- 统计状态写在 `meta.last_traffic_sync_status`、`meta.traffic_observed_xray|singbox`、Snell/SS 用户的 `traffic_observed_at`。

### `--api`（版本化接口）
- 只读基础层 `stage=read_only_foundation`：`capabilities`、`inventory`（脱敏，users 只输出 name/enabled/quota/used/expire_date）、`plan`（只做定位和版本检查，永远返回 unsupported_operation）、`result`（永远是 unknown）。
- `write_actions=[]`，**没有任何用户写操作**。Agent 的 `script_api.py` 只调用 capabilities/inventory，并且要求 `write_actions==[]`。
- revision 是整库的 SHA-256，包含流量，不能用作配置版本。

### 共享渲染器
- `_platform_render_inbound`（Agent 通过脚本副本调用）只渲染「有效用户」：enabled、未到期、未超 `quota`、未超 `panel_quota`（按 panel_used 加上未采样的增量计算）。全部无效时写入占位用户 `vaio-disabled`，入站不会被删除。

## 2. 节点程序 `platform/agent/`

- 直接读写脚本数据库（`bridge.py`，加 `.db.lock` 锁），**不经过 `--api` 写入**。
- 快照（`inventory.py:inventory`）每 10 秒随 poll 上报：每个实例的 core/protocol/port/service/status/managed/sni/traffic_state，以及 users 列表 `{name, enabled, expire_date, used, quota, reset_day}`。其中 used/quota 取 `effective_usage`（有 panel_quota 时用面板周期值）。快照不含凭据和用户的稳定 ID。
- 能力字段：`task_api_version=2`（支持 reset_credentials）、`billing_version=1`（支持 quota_gb/reset_day）、`config_details_version=2`、`install_options_version=2`、`write_capabilities`。面板在 `sanitize_snapshot` 里把这些字段归一化。
- 任务：一次只针对一个实例 `{action, protocol, core, port, params, revision}`。
  - `user_add`：名字在同一 (core, proto) 内唯一，凭据随机生成（不能指定）；Snell/SS 拒绝。
  - `user_update`：quota_gb、reset_day、expire_date、enabled、reset_credentials。
  - `user_delete`：`default` 不能删；Snell/SS 拒绝。
  - `install` 可以带 `name` 和 `credential`（指定凭据），Snell/SS 安装就等于给一个用户开一个端口。
- 计费（`billing.py`）：设置配额或重置日后用户获得 `panel_quota/panel_used/panel_last_used/panel_reset_day/panel_cycle`，并把脚本的 `quota` 置 0（脚本不再按配额停用）。`advance` 把脚本累计的 `used` 的增量计入面板周期，跨过重置日时 panel_used 清零。设置非零配额前要求 15 分钟内有有效采样。
- 本地执行（`Bridge.reconcile`，每 60 秒）：面板离线时也会对 `panel_managed` 实例执行到期和配额。允许用户列表变化后重新渲染并重启服务，失败会回滚；结果未知时写 `enforcement-pending.json` 并阻塞后续写任务。
- 事务：每个任务按 task id 记录意图，结果未知时不重放；写前在节点本地备份；revision 不一致就拒绝。

## 3. 面板 `platform/vaio/` 与 `platform/web/app.js`

- 存储 SQLite：nodes（snapshot JSON 原样保存）、tasks、audit、samples、incidents、notifications、settings。**没有用户表**，用户只存在于各节点的快照里。
- 任务队列：每个节点同时只能有一个 queued/running 任务（server.py:573）；写任务要求 revision 等于最新快照；节点有 unknown 任务时拒绝新的写任务。
- 前端：节点详情 → 协议实例 → `showInstance` 弹窗列出实例用户 → `editUser` 表单（用户名、到期、启用、配额 GiB、每月重置日、重置凭据）→ `submitTask` 下发单实例任务。新增用户只对多用户协议开放。
- 流量页 `trafficPage()`：按节点 → 实例 → 用户的快照展示，汇总是各用户当前周期之和，没有跨节点的用户视角。
- 监控 `monitor.scan`：按「节点:core:proto:port:用户名」逐个告警 80%、超额、3 天内到期。

## 4. 对「平台统一用户」的约束

1. 节点上的身份是 (core, proto, name)，没有跨协议的用户 ID。平台用户要映射到每个实例里的一个用户名，并且同一节点同一 (core, proto) 下名字不能重复。
2. Snell/SS 一个用户一个端口：平台用户绑定这些协议时，等于在节点上为他安装一个独立实例。
3. 现有计费按实例里的单个用户计，周期由用户自己的 reset_day 决定。跨节点累计需要面板汇总后再决定停用。
4. 面板每节点串行一个任务，并且有 revision 检查：一个用户绑定 N 个实例时，逐个下发会很慢，而且容易互相让 revision 过期。需要节点批量动作或面板编排。
5. 停用的机制已经存在（enabled=false，或用 panel_quota 把渲染结果置空）。离线节点由 Agent 本地 reconcile 按本地数据继续执行。
6. 快照没有用户凭据，也没有稳定的用户 ID。认领现有用户只能按「节点 + 实例 + 用户名」匹配。
7. `--api` 没有写能力。要让脚本「同步更新」，要么扩展 `--api` 的用户写操作，要么在数据库里增加脚本能识别的字段（比如 `platform_user_id`、面板锁定标记），让脚本菜单避免和面板冲突。
