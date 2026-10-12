# 技术设计：平台统一用户管理

依据 `prd.md` 的决策 D1–D9，以及 `research/current-state.md`。

## 1. 总体数据流

```
面板（权威：平台用户、配额、周期、到期、绑定）
  │  poll 快照 ← 每个绑定的原始累计用量 + 平台字段
  │  计算期望状态（启用/停用 + 原因），按节点合并成一个 platform_apply 任务
  ▼
Agent（platform_users_version=1）
  │  任务 → ScriptAPI.write("user_apply")，request_id = 任务 ID
  ▼
脚本 `--api user_apply`（事务：锁 → 意图 → 备份 → 改库 → 重建 → 校验 → 结果）
  │  数据库用户记录带 platform_user_id，菜单里不能修改
  ▼
核心配置（共享渲染器只渲染有效用户）
```

节点兜底：到期日随绑定下发到节点。面板离线时，脚本的 `--check-expire` 和 Agent 的 `reconcile` 仍会按本地日期停用到期用户。跨节点配额只由面板判断（D2）。

## 2. 面板数据模型（SQLite user_version 1 → 2）

```sql
CREATE TABLE platform_users(
  id TEXT PRIMARY KEY,                 -- uuid4
  name TEXT NOT NULL UNIQUE,           -- [A-Za-z0-9_-]{1,32}，也是默认的节点用户名
  note TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,  -- 管理员手动启停
  expire_date TEXT NOT NULL DEFAULT '',-- YYYY-MM-DD，空表示永不过期
  quota_bytes INTEGER NOT NULL DEFAULT 0, -- 0 表示不限
  reset_day INTEGER NOT NULL DEFAULT 0,   -- 0 表示不重置；1–28
  cycle TEXT NOT NULL DEFAULT 'total',    -- 当前周期键（起始日期或 total）
  created REAL NOT NULL, updated REAL NOT NULL);

CREATE TABLE platform_bindings(
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES platform_users(id),
  node_id TEXT NOT NULL REFERENCES nodes(id),
  core TEXT NOT NULL, protocol TEXT NOT NULL, port INTEGER NOT NULL,
  node_user TEXT NOT NULL,             -- 节点上的用户名
  origin TEXT NOT NULL,                -- created | claimed | dedicated（为 Snell/SS 安装的独立实例）
  state TEXT NOT NULL,                 -- pending | synced | failed | unknown | releasing
  cycle_used INTEGER NOT NULL DEFAULT 0, -- 本周期累计（面板计算）
  last_raw INTEGER,                    -- 上次看到的节点原始累计 used
  last_error TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL,
  UNIQUE(node_id, core, protocol, node_user));
```

- 派生状态不入库，每次计算：`expired = expire_date < 今天`；`overquota = quota_bytes > 0 且 Σcycle_used ≥ quota_bytes`；期望启用 = `enabled 且未到期且未超额`；停用原因按 manual > expired > quota 的优先级取。
- 端口变化：绑定以 (node, core, protocol, node_user) 唯一；面板改实例端口成功后同步更新绑定的 port。快照里有带同一 platform_user_id 的用户时，以快照为准自动修正 port。
- 删除节点（进回收站）：绑定保留，状态显示「节点已删除」，用量不再增长。
- 备份 `backups.verify` 接受 user_version ≤ 2；恢复后，旧备份（v1）由 Store 迁移补表。

## 3. 用量累计与周期

- 快照里平台用户的 `used` 是脚本的原始累计计数，脚本对平台用户不做月重置（§5.4）。
- 每次 poll，在同一个数据库事务里对每个绑定计算：`delta = raw - last_raw`（raw ≥ last_raw 时），否则 `delta = raw`（计数被清零或用户重建）。然后 `cycle_used += delta`，`last_raw = raw`。首次看到（last_raw 为空）时：认领的绑定把 raw 计入本周期，保留已用流量（D4）；新建的绑定 raw 应为 0。
- 只累计 `traffic_state == ready` 的实例；不 ready 时保留 last_raw，待恢复后一次性补齐增量。
- 周期切换（monitor.scan，按面板时区的日期）：`reset_day>0` 且新周期键大于 `cycle` 时，所有绑定的 cycle_used 清零，cycle 更新。之后期望状态里 quota 原因消失，自动恢复（D3）。
- 管理员「重置用量」：清零 cycle_used，并写审计日志。
- 跨周期的未采样增量计入新周期，与 `agent/billing.py:advance` 的约定一致。

## 4. 期望状态下发（面板 → 节点）

- 新任务动作 `platform_apply`：按节点下发，不针对单个实例。请求格式：
  ```json
  {"action":"platform_apply","params":{"changes":[
    {"op":"create|claim|update|release|delete",
     "target":{"core":"xray","protocol":"vless","port":443},
     "name":"alice","platform_user_id":"<uuid>",
     "enabled":true,"disable_reason":"","expire_date":"2026-12-31",
     "reset_credentials":false}]}}
  ```
  `validate_platform_task` 单独校验，最多 200 条变更；不复用实例任务的 revision 检查。理由：这是声明式、幂等的变更，脚本会按 platform_user_id 逐条核对目标。
- 调度（monitor.scan，每 30 秒，以及管理员操作后立即触发）：对每个在线、已接管、非维护、无 unknown 任务、无 queued/running 任务、并且宣告了 `platform_users_version=1` 的节点，比较期望状态和快照中的实际状态（enabled、disable_reason、expire_date、是否存在、platform_user_id）。有差异时合并成一个 `platform_apply` 任务入队，任务 request_key 用差异内容的摘要，相同差异不会重复入队。
- 结果：成功时绑定标记 synced（以下一次快照为准最终确认）；失败标记 failed 并记录消息，下次调度在差异仍然存在时重试（失败的任务已回滚，可以重新提交）；unknown 时标记 unknown，节点阻塞，等人工核对（D6）。
- 离线节点：不入队，绑定显示「待同步」；上线后下一次调度自动收敛。
- 系统发起的任务在审计里记为 `system`，任务记录页显示「平台用户同步」。

### 绑定与认领流程

- 多用户协议（vless、trojan、hy2、anytls）：添加绑定时，面板写一条 pending 绑定，并下发 `op=create`；脚本生成凭据，在该实例下新增用户，并写入 platform_user_id。
- Snell / SS（一个用户一个端口）：添加绑定时选择「为该用户新建实例」，面板先下发现有的 `install` 任务（name=平台用户名），成功后再下发 `op=claim`，origin 记为 dedicated。
- 认领：选择节点实例里的一个现有用户，下发 `op=claim`。脚本只写入 platform_user_id 和平台字段，不改凭据和 used（D4）。认领前，如果平台用户已设置配额，面板会提示「认领后本周期用量会立刻计入」。
- 解除绑定：`op=release`，节点删掉平台字段，用户回到按实例管理，保留当前的启停状态。删除节点用户：`op=delete`。dedicated 实例的卸载走现有的 `delete` 任务，界面上二次确认。
- 删除平台用户：要求先处理全部绑定，可以选择「全部解除」或「全部删除节点用户」，面板依次下发；全部完成后才删除用户记录。
- 重置凭据（D5）：`op=update, reset_credentials=true`，可针对单个绑定，也可以批量。查看连接信息复用现有的 `share` 任务。

## 5. 脚本 `--api` 用户写接口（3.7.4-preview.3）

### 5.1 能力
`capabilities` 保持 `api_version:1`，新增 `users_api_version:1`、`write_actions:["user_apply"]`、`stage:"user_write"`，`actions` 增加 `user_apply`。协议级的 `write_supported` 仍为 false：实例安装、修改、卸载的写入继续走 Agent 已验收的适配器。

### 5.2 inventory 增量
每个用户增加：`platform_user_id`（uuid 或 null）、`disable_reason`、`raw_used`（原始 used）。仍然不输出凭据。新增 `config_revision`：先剔除易变字段（与 `vaio/common.py:config_revision` 的列表一致）再计算 SHA-256，供 `plan` 检查和诊断使用。

### 5.3 `user_apply` 事务
1. 校验请求：顶层字段同上，`params.changes` 是 1–200 条，每条的字段白名单与面板一致；名字、uuid、日期、协议、端口都严格校验，绝不把内容拼进 shell。
2. 获取 `$CFG/.txn.lock`（flock，Agent 自己的事务也先拿这把锁，见 §6.3），全程持有。
3. 幂等：`$CFG/api-results/<request_id>.json` 已存在时，指纹（请求的 SHA-256）相同就返回已存结果，不同就拒绝；状态是 running 时返回 unknown，并且不重放。
4. 写入意图（running），备份 db.json 和受影响的核心配置、Snell 配置到 `$CFG/api-backups/<request_id>/`（0700）。
5. 在内存中逐条计算新数据库：
   - create：目标实例存在、协议支持多用户、同 (core,proto) 下没有同名用户，生成凭据（规则与 Agent 现有的一致），写入 `platform_user_id`、`platform_managed:true`、quota=0、used=0。
   - claim：目标用户存在且没有 platform_user_id，或者已经是同一个 id（幂等）；只加平台字段。
   - update：目标用户的 platform_user_id 必须匹配；设置 enabled、disable_reason、expire_date；按需重置凭据（同步 row 级的 uuid/password/psk，与 Agent 现有逻辑一致）。
   - release：去掉平台字段。delete：删除用户（default 用户和 Snell/SS 唯一用户拒绝，引导去卸载实例）。
   - 任一条校验失败则整体拒绝，不做任何写入（failed，ValueError 类）。
6. 用一次 `_db_apply` 写入，然后对受影响的核心各重建一次（`rebuild_and_reload_xray` / `_regenerate_config` / `_snell_apply_users`）。等待 1 秒，检查服务仍在运行（被停用的 Snell 实例应当是停止状态）。
7. 失败时恢复备份并重建，结果记为 failed（已回滚）；恢复也失败则记为 unknown。
8. 写入最终结果，`result` 动作按 request_id 返回已存结果，只读不重放。结果文件保留 30 天。

### 5.4 菜单与定时任务
- 用户列表在带 platform_user_id 的用户后面标注「平台」；修改配额、到期、启停、删除、重置流量、TG 绑定之前都要检查，平台用户提示「由 Vaio 平台管理，请在面板操作」并拒绝修改。分享链接和查看仍然可用。
- `reset_monthly_user_traffic` 跳过平台用户；`_enforce_user_quotas` 本来就因为 quota=0 而跳过。
- `--check-expire` 继续对平台用户按到期日停用，作为节点兜底，原因记为 expired。面板延长到期日后，通过 update 恢复。
- 交互菜单直接卸载协议时，如果实例里有平台用户，二次确认并提示面板上的绑定会失效。

## 6. Agent（0.3.0-preview.11）

### 6.1 能力协商
`inventory()` 在 ScriptAPI 读到 `users_api_version==1`、脚本校验和匹配、Agent 支持时，上报 `platform_users_version:1`。`sanitize_snapshot` 归一化这个字段，并给 users 保留 `platform_user_id`（uuid 校验）、`disable_reason`（枚举）、`raw_used`。

### 6.2 执行 platform_apply
- `ScriptAPI.write(action, params, request_id)`：只允许 `user_apply`；校验和不匹配就拒绝；超时 300 秒；stdout 限制 1 MiB；响应必须是同一个 request_id。
- `Bridge.execute` 识别 `platform_apply`，沿用现有的任务意图记录（指纹、不重放）和 enforcement-pending 检查。脚本返回 unknown 或进程超时时，先用 `result` 动作查询；仍然 unknown 就记为 TransactionUnknown。
- 实例任务碰到平台用户时：`user_update` 的 quota_gb/reset_day 和 `user_delete` 都拒绝，提示「平台用户请在用户管理中修改」。share、inspect 仍然允许。

### 6.3 锁
- 新增 `$CFG/.txn.lock`：`Bridge.locked()` 和 `reconcile()` 先拿 `.txn.lock`，再拿 `.db.lock`；调用脚本 `user_apply` 时 Agent **不持有**任何锁，由脚本自己拿 `.txn.lock`。这样避免死锁，也保证 Agent 事务和脚本事务互斥。
- 脚本菜单的单次写入仍然只拿 `.db.lock`（保持现状）。

### 6.4 reconcile
不变。active_users 已经按 enabled、到期、quota/panel_quota 过滤；平台用户的 quota 为 0，只受 enabled 和到期影响。

## 7. 面板界面（遵守黑白组件规范）

- 侧栏新增「用户管理」（`#users`），放在「服务器节点」之后。
- 列表：用户名、状态（启用/停用 + 原因：手动、到期、超额）、本周期用量/配额（10 段 meter）、到期日、绑定数、同步状态（全部同步 / n 个待同步 / 失败）。支持搜索和「新建用户」。
- 详情 `#users/<id>`：基本信息与编辑（到期、配额 GiB、重置日、备注、启停）、操作（重置用量、重置全部凭据、删除）、绑定表（节点、协议 · 端口、节点状态、同步状态、本周期用量、操作：连接信息、重置凭据、解除、删除节点用户）。「添加绑定」弹窗：选节点（只列出能力达标的节点，其余的显示「需要升级节点程序」）→ 选实例 → 新建用户或认领现有用户；Snell/SS 显示「为该用户新建实例」。
- `showInstance`：平台用户行显示「平台 · 用户名」链接，编辑和删除按钮改为「在用户管理中修改」；未认领的用户增加「认领」按钮。
- 流量页增加「用户流量（平台）」表：按平台用户汇总本周期用量和各绑定明细。实例级的表格保持不变。`trafficPage()` 只用测试上下文提供的函数（规范约束）。
- 监控：已绑定的节点用户不再按实例告警，改为按平台用户告警：80%、超额、3 天内到期、绑定同步失败。

## 8. 兼容与回滚

- 旧 Agent（无 `platform_users_version`）：不能绑定或认领，界面提示升级；现有的实例管理不受影响。
- 新 Agent 配旧脚本：理论上不会出现，因为副本一起打包，校验和固定。脚本 API 不可用时不宣告能力。
- 面板回滚到 0.3.0-preview.10：数据库 user_version=2 会被旧面板拒绝（现有保护）。回滚要先恢复 v1 备份，文档里说明。
- 节点回滚：平台字段是附加字段，旧脚本和旧 Agent 会忽略它们。平台用户的 quota=0，只按 enabled 和到期生效，行为可预期。

## 9. 安全

- 凭据只在节点生成和保存，快照和任务结果里不含凭据（share 走现有的 10 分钟清理逻辑）。
- 脚本 API 的请求是 JSON，所有值用 jq `--arg`/`--argjson` 传入，并按白名单校验。
- 平台用户名、uuid 在面板、Agent、脚本三层都做格式校验。
- 面板的新接口全部要求管理员会话和 CSRF；系统任务不暴露给外部接口。
