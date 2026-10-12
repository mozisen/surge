# 技术设计：统一用户管理（脚本独立 + 平台跨节点）

依据 `prd.md` 的决策 D1–D11，以及 `research/current-state.md`。

## 0. 三层用户概念

| 名称 | 所在 | 含义 |
|---|---|---|
| 协议用户 | 脚本 db.json `row.users[]`（现状） | 某个协议实例里的一个账号，有自己的凭据和原始计数 `used` |
| **统一用户** | 脚本 db.json 新增顶层 `accounts`（新增） | 一台节点上的一个人：挂多个协议用户，到期、配额、重置日、启停统一设置，用量合计，**由脚本自己执行**，不依赖平台 |
| **平台用户** | 面板 SQLite（新增） | 跨节点的一个人：在每台节点上关联一个统一用户，跨节点配额由面板执行 |

脚本可以完全独立运行（D10）。没有接入平台时，统一用户的全部功能都由脚本菜单和定时任务完成。接入平台后，面板与节点的统一用户双向同步，后改的生效（D11）。

## 1. 总体数据流

```
脚本（独立）：菜单 / cron 管理统一用户 → 合计成员用量 → 到期、超额、重置 → 启停成员协议用户 → 重建核心
             ↑↓ --api（account_* 操作，乐观并发：base_rev）
Agent：快照上报 accounts（无凭据）；执行 platform_apply → 脚本 --api
             ↑↓ poll / 任务
面板：平台用户 ↔ 每节点一个统一用户；三方合并（基准、节点、面板）；跨节点配额判断 → 下发
```

## 2. 脚本：统一用户（独立运行，子任务 1）

### 2.1 数据结构（db.json，附加字段，旧版脚本会忽略）

```json
"accounts": {
  "<account_id uuid>": {
    "name": "alice",                 // 节点内唯一，[A-Za-z0-9_-]{1,32}
    "note": "",
    "enabled": true,                 // 管理员手动启停
    "expire_date": "2026-12-31",     // 空表示永不过期
    "quota": 107374182400,           // 字节，0 表示不限
    "reset_day": 1,                  // 0 表示不重置；1–28
    "cycle": "2026-10-01",           // 当前周期键，或 total
    "cycle_used": 123,               // 本周期合计（脚本计算）
    "disable_reason": "",            // "" | manual | expired | quota | platform_quota
    "members": [ {"core":"xray","protocol":"vless","port":443,"name":"alice","last_raw":100} ],
    "rev": 7,                        // 每次修改同步字段时 +1
    "mtime": {"enabled":1760000000,"expire_date":...,"quota":...,"reset_day":...,"note":...,"members":...},
    "platform_user_id": null,        // 关联平台用户后才有
    "platform_block": ""             // 面板下发的跨节点停用原因："" | quota
  }
}
```

- 成员协议用户记录增加 `account_id`。成员的 `expire_date` 由脚本始终同步为统一用户的到期日，`quota` 置 0，`enabled` 和 `disable_reason` 由统一用户的状态派生。这样现有的共享渲染器、Agent reconcile、`--check-expire` 不改也能正确生效。
- 统一用户名在节点内唯一。成员协议用户名默认等于统一用户名；同一协议下名字已被占用时，提示输入其他名字。

### 2.2 执行（脚本 cron，`--sync-traffic` 之后）
1. 用量：对每个成员，`delta = used - last_raw`（used ≥ last_raw 时），否则 `delta = used`；`cycle_used += delta`，`last_raw = used`。这与 `agent/billing.py:advance` 的约定相同。
2. 周期：`reset_day>0` 且本地日期跨过重置日时，`cycle_used=0`，并更新 cycle。
3. 状态：有效 = `enabled` 且未到期 且 (`quota==0` 或 `cycle_used<quota`) 且 `platform_block==""`。原因优先级为 manual > expired > quota > platform_quota。
4. 只在派生的成员状态变化时写库和重建（每个核心一次）。月重置或调高配额后自动恢复；手动停用不自动恢复。
5. 成员不参与节点全局的月重置（`reset_monthly_user_traffic` 跳过带 account_id 的用户），也不参与 `_enforce_user_quotas`（因为 quota=0）。
6. 接入平台时，本地依然按自己的 `quota` 判断。节点本地用量 ≤ 跨节点总量，所以本地超额一定意味着总量超额，这是安全的兜底。

### 2.3 菜单（「用户管理」改版，保留原有的按协议入口）
- 新增「统一用户」子菜单：列表（名称、状态及原因、本周期用量/配额、到期、成员数、平台标记）、新建、编辑（到期、配额 GB、重置日、备注）、启用/停用、添加协议（从已安装的多用户协议实例中选择 → 新建成员并生成凭据；Snell 走现有的 `_snell_add_user` 新建实例）、移除协议（删除成员，或保留为普通协议用户）、查看全部分享链接、重置凭据（单个成员或全部）、重置用量、删除（同时删除成员，或保留成员）。
- 「归入统一用户」：把现有协议用户加入新的或已有的统一用户，保留凭据和用量。「按用户名批量归并」：先列出预览，确认后执行，不会自动执行。
- 原有的按协议用户菜单：成员行标注「属于 alice」；修改成员的到期、配额、启停时，提示改为修改统一用户（同一节点内不能出现两套规则）。不锁定平台用户：平台关联只影响同步，不影响本地是否可编辑（D10）。
- 「解除平台关联」：清除 `platform_user_id` 和 `platform_block`，统一用户回到纯本地管理。

### 2.4 迁移
`init_db` 不自动迁移。没有 `accounts` 字段时等同于空表；旧的协议用户保持现状，直到管理员手动归入。

## 3. 脚本 `--api`（子任务 2）

### 3.1 能力与快照（实现于 3.7.4-preview.4）
- `capabilities` 保持 `stage:"read_only_foundation"` 和 `write_actions:[]`，避免现有 Agent 把脚本接口判为不可用；另外用 `accounts_api:{version:1, actions:["account_apply","result"], ops:[...], snell_member_add:false}` 声明。
- `inventory` 增加 `accounts`（除凭据外的全部字段，成员附带当前累计计数 `used`、`enabled` 和 `disable_reason`）以及协议用户的 `account_id`。不另外提供 config_revision：并发控制用统一用户自己的 `rev`。

### 3.2 `account_apply`
详见 `docs/script-accounts.md`「写接口」。要点：每次请求最多 200 项操作，事务（`.txn.lock`、running 意图、备份、预检、延后重建、失败回滚、恢复失败为 unknown）；`update` 带 `base_rev`，不一致时返回 `rev_conflict` 和当前 rev；`create` 由调用方指定 account_id；`block` 和 `link` 不增加 rev。Snell 的 `member_add` 和带 delete 的移除不进事务，返回 `unsupported_snell_operation`；平台先用安装任务建实例，再用 `member_claim` 归入。

## 4. Agent（子任务 3）

- 能力：脚本宣告 `accounts_api_version==1` 且校验和匹配时，快照上报 `accounts_version:1`，并带上 `accounts`（经 `sanitize_snapshot` 严格归一化：uuid、名字、日期、整数范围、最多 1000 个统一用户和 20000 个成员）。
- 新任务 `platform_apply`：`{"action":"platform_apply","params":{"ops":[...]}}`，由 `vaio/common.py:validate_platform_task` 校验，Agent 和面板共用。Agent 沿用任务意图记录（指纹、不重放）和 enforcement-pending 阻塞，调用脚本 `account_apply`（request_id = 任务 ID）；结果不明时先查询 `result`。脚本返回 `rev_conflict` 时，任务记为 failed，并带上冲突信息（已回滚、可以重提）。
- 锁：新增 `$CFG/.txn.lock`。`Bridge.locked()` 和 `reconcile()` 先拿它，再拿 `.db.lock`；调用脚本时不持有任何锁，由脚本自己拿 `.txn.lock`。
- 实例任务碰到统一用户的成员时：`user_update` 的 quota_gb/reset_day/expire_date/enabled 以及 `user_delete` 都拒绝，提示「该用户属于统一用户，请修改统一用户」。share、inspect、reset_credentials 允许。
- `reconcile` 不变（成员的 enabled 和到期已经派生好）。

## 5. 面板（子任务 4）

### 5.1 数据模型（SQLite user_version 1 → 2）
```sql
CREATE TABLE platform_users(
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, note TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1, expire_date TEXT NOT NULL DEFAULT '',
  quota_bytes INTEGER NOT NULL DEFAULT 0, reset_day INTEGER NOT NULL DEFAULT 0,
  cycle TEXT NOT NULL DEFAULT 'total',
  mtime TEXT NOT NULL DEFAULT '{}',          -- 各同步字段在面板上的修改时间
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE platform_links(                 -- 平台用户 ↔ 某节点的统一用户
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES platform_users(id),
  node_id TEXT NOT NULL REFERENCES nodes(id),
  account_id TEXT,                           -- 节点上创建完成之前为空
  base TEXT NOT NULL DEFAULT '{}',           -- 上次同步一致时的字段值（三方合并的基准）
  base_rev INTEGER,                          -- 对应的节点 rev
  cycle_used INTEGER NOT NULL DEFAULT 0,     -- 面板按平台周期计算的本节点用量
  last_raw TEXT NOT NULL DEFAULT '{}',       -- 成员键 → 上次的原始计数
  state TEXT NOT NULL,                       -- pending | synced | conflict | failed | unknown
  last_error TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
  UNIQUE(user_id, node_id), UNIQUE(node_id, account_id));
```
成员不入库，以快照为准。备份校验接受 user_version ≤ 2；恢复 v1 备份后由 Store 迁移补表。

### 5.2 同步字段与三方合并（D11）
同步字段：`name`、`note`、`enabled`、`expire_date`、`quota`、`reset_day`，以及成员集合（节点本地增删协议也要同步回面板，面板端只记录在快照里）。

快照到达时，对每个已关联的节点统一用户：
1. `node_changed = 节点值 ≠ base`，`panel_changed = 平台值 ≠ base`（逐字段比较）。
2. 只有节点改了：写回平台用户（mtime 用节点的 mtime），再下发给其他节点。
3. 只有面板改了：下发 `update`，补丁只包含这些字段，带 `base_rev = 节点当前 rev`。
4. 两边都改了而且值不同：按修改时间，后改的生效（节点 mtime 和面板 mtime 比较）；输的一方被覆盖，界面提示「已按后改的合并」并写审计。时钟偏差会影响判定，文档里说明，面板会显示两边的时间。
5. 下发成功、并在下一次快照中确认值一致后，更新 base 和 base_rev。
6. 节点本地新增或移除了成员：面板只展示，不需要合并，因为成员只属于节点。

### 5.3 跨节点用量与配额
- 每次 poll 时，按成员的原始计数计算增量，累加到该节点 link 的 cycle_used（与 §2.2 的算法相同，但用平台周期）。只累计 `traffic_state==ready` 的实例。
- 平台周期：按面板时区的 reset_day 切换，所有 link 的 cycle_used 清零。
- `Σ cycle_used ≥ quota_bytes` 时，对所有节点下发 `block: quota`；周期切换、调高配额或手动重置后下发 `block: ""`。节点本地也会按自己的 quota 兜底（§2.2.6）。
- 到期：同步字段 expire_date 下发到节点，由节点执行；面板只做展示和告警。

### 5.4 调度
monitor.scan 每 30 秒执行一次，管理员操作后也会立即触发：对每个在线、已接管、非维护、没有 unknown 和 queued/running 任务、并且宣告了 `accounts_version=1` 的节点，把需要下发的操作（创建、更新补丁、block、link）合并成一个 `platform_apply`，request_key 用操作摘要去重。失败的任务已回滚，下一轮在差异仍然存在时重新计算并下发；unknown 阻塞该节点，等人工核对。离线节点的 link 显示「待同步」。

### 5.5 关联与认领
- 新建关联：平台用户 → 选择节点 → 在节点创建统一用户（create，带要新建的协议成员），之后 link。
- 认领：节点上已有的、未关联的统一用户，可以关联到新的或已有的平台用户。关联时比较字段，不一致时让管理员选择以哪边为准，然后作为一次修改下发。认领节点用户时，本周期用量按节点 raw 计入（保留已用流量）。
- 节点上未归入统一用户的协议用户：在面板的实例弹窗里可以「归入统一用户」（member_claim），与脚本菜单的功能等价。
- 解除关联：`unlink`，节点统一用户保留，回到纯本地管理。删除平台用户：先选择全部解除关联，或者同时删除各节点的统一用户（delete，成员一并删除或保留）。

### 5.6 界面（黑白规范）
- 侧栏新增「用户管理」（`#users`）：平台用户列表（状态及原因、本周期用量/配额 meter、到期、节点数、同步状态），以及「节点上未关联的统一用户」区块，可以认领。
- 详情 `#users/<id>`：字段编辑、各节点关联表（节点、节点统一用户、成员协议 · 端口、同步状态、本周期用量、冲突提示）、添加节点、重置用量、重置凭据、解除关联、删除。连接信息复用 `share` 任务，按成员逐个查看。
- `showInstance`：成员行显示「统一用户 alice」，链接到平台用户（已关联时）或节点统一用户；未归入的协议用户可以归入。
- 流量页：新增「按用户」表（平台用户本周期合计及各节点明细）。`trafficPage()` 只用测试上下文提供的函数。
- 监控：已归入统一用户的协议用户不再逐个告警，改为按平台用户告警（80%、超额、3 天内到期、同步冲突或失败）；未关联平台的节点统一用户按节点告警。

## 6. 兼容与回滚
- 旧脚本或旧 Agent：不宣告能力，不能关联，界面提示升级；现有的实例管理不受影响。
- 新脚本独立使用：不安装 Agent 也可以完整使用统一用户。
- 节点脚本回滚到 3.7.4-preview.2：`accounts` 和 `account_id` 会被忽略；成员保留最后派生的 enabled 和到期日，quota=0，因此不会被误停，但统一配额不再生效。文档里说明。
- 面板回滚：数据库 v2 会被旧面板拒绝，需要先恢复 v1 备份。

## 7. 安全
- 凭据只在节点生成和保存；快照、任务结果里不含凭据（share 走现有的清理逻辑）。
- 脚本 API 只接受 JSON，所有值用 jq 传参并按白名单校验；名字、uuid、日期、端口在三层都校验。
- 面板的新接口全部要求管理员会话和 CSRF。
