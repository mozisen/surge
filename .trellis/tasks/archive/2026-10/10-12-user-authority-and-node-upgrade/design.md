# 技术设计

版本：脚本 3.7.4-preview.5，面板与 Agent 0.3.0-preview.12。

## 1. 用户管理方式（authority）

保存在节点 `db.json` 的 `meta.user_authority`：`"script"`（缺省）或 `"platform"`，切换时间记在 `meta.user_authority_at`。节点是唯一依据，面板只读取快照里的值。

| | 脚本模式 | 平台模式 |
|---|---|---|
| 脚本菜单用户操作 | 全部可用（现状） | 只能查看、看分享链接、看流量、切回脚本 |
| 面板「用户管理」 | 不能关联此节点 | 唯一写入入口 |
| 面板实例弹窗的用户 | 只读 | 只读（链接到用户管理） |
| Agent 用户写任务（user_add/update/delete） | 面板不发送（面板拦截） | Agent 拒绝（走 platform_apply） |
| `account_apply` | 只接受 `set_authority` | 全部操作 |

旧版节点程序不上报 `authority_version`，面板对它保持现在的行为（实例弹窗可编辑用户，不能关联平台用户）。

## 2. 脚本（子任务 1）

### 2.1 数据函数
- `db_authority_get`：输出 `script`/`platform`。
- `_authority_clear_users`（纯 jq，便于测试）：对 `xray`、`singbox` 下每个实例设 `users=[]`（明确为空数组，避免旧的单用户实例回退成 row 级 default 凭据）；row 级的 `uuid`/`password`/`psk` 不删除（生成器和分享逻辑依赖这些字段），而是**换成新的随机值**，保证旧凭据全部失效；删除 `accounts`、`meta.accounts_reload_pending`、TG 绑定相关的 meta；SS/Snell 实例同样 `users=[]`，渲染器和 `_snell_prepare_user` 会把它们停用或换成随机密码。
- `db_authority_set <mode>`：
  - → platform：事务（复用 `--api` 的备份/回滚机制，菜单路径也走同一个函数）：清空用户 → 写 `meta.user_authority=platform` → 重建全部核心和 Snell 实例 → 失败恢复备份。
  - → script：删除所有统一用户的 `platform_user_id`、`platform_block`，写 `meta.user_authority=script`。用户和凭据保留。
- 守卫 `_authority_guard`：平台模式下返回 1 并提示「用户由 Vaio 平台管理」。加在 `_add_user`、`_delete_user`、`_set_user_quota`、`_reset_user_traffic`、`_toggle_user`、`_set_user_expire_date`、`_set_user_routing`、`_snell_add_user`、`_snell_edit_user`、TG 绑定、`manage_accounts` 的写操作，以及 `db_account_*` 的菜单入口（API 路径不受限）。

### 2.2 菜单
- 用户管理页顶部显示「当前由 脚本 / Vaio 平台 管理」。
- 新增 `m` 切换用户管理方式：
  - 切到平台：列出将删除的用户数（按协议），提示所有客户端失效，要求输入 `CLEAR` 确认。
  - 切回脚本：提示平台将停止管理，用户保留，`y` 确认。
- 平台模式下菜单只保留：查看用户列表、分享链接、实时流量、同步流量、切换方式。

### 2.3 `--api`
- `account_apply` 新增操作 `{"op":"set_authority","mode":"platform"|"script"}`（不带 account_id，只能单独成请求）。
- 脚本模式下，除 `set_authority` 外的操作返回 `authority_script`，不写入。
- `capabilities.accounts_api.version` 升到 2（ops 包含 `set_authority`），新增 `user_authority`；`inventory` 增加 `user_authority`。
- 统一用户结算 `accounts_apply` 两种模式下都运行。

## 3. Agent（子任务 2）

### 3.1 模式
- 快照新增 `user_authority`（来自 db meta）和 `authority_version: 1`；`sanitize_snapshot` 归一化。
- `Bridge._execute`：平台模式下拒绝 `user_add/user_update/user_delete`（提示去用户管理页修改）；脚本模式下的「面板只读」由面板拦截（面板是这些任务的唯一来源，旧测试覆盖的按实例写路径保留给旧面板）。`share`、`inspect` 和实例操作不变。
- `platform_apply`：校验允许 `set_authority`；Agent 不额外判断模式，由脚本拒绝。

### 3.2 一键升级
- 新任务 `agent_upgrade`，参数 `{}`（总是同时升级主脚本）。由 `validate_task` 的独立分支校验，不需要 core/protocol/port。
- Agent 执行：检查 `systemd-run`（systemd）或 OpenRC；在独立单元中启动升级器：
  - systemd：`systemd-run --unit vaio-agent-upgrade-<短 ID> --collect --quiet /usr/bin/python3 /opt/vaio-agent/scripts/update-agent.py --task <ID>`
  - OpenRC：`setsid`（`start_new_session=True`）启动同一命令，输出写 `/var/lib/vaio-agent/upgrade.log`。
  - 启动成功即返回任务成功（消息「已启动升级」）；升级本身的结果另行上报。
- `update-agent.py --task <ID>`：
  1. 等待本机任务日志里该任务已上报（最长 120 秒），然后沿用现有流程（下载、校验、暂存自检、维护模式、停止、替换 `/opt/vaio-agent`）。
  2. 同时替换主脚本：用新安装包里的 `vendor/vless-server.sh`，校验其 SHA-256 等于新包 `agent/runtime.py` 里的 `UPSTREAM_SHA`；旧脚本备份为 `/usr/local/bin/vless-server.sh.vaio-backup-<时间>`；原子替换。节点没有主脚本时安装。
  3. 启动新版并等待上线（90 秒）；失败时同时恢复旧程序目录和旧主脚本。
  4. 把结果写入 `/var/lib/vaio-agent/last-upgrade.json`：`{at, task, from, to, script_from, script_to, status: succeeded|rolled_back|failed, message}`。
- 快照新增 `upgrade_version: 1` 和 `last_upgrade`（来自上面的文件，最多 300 字消息）。
- 现有 SSH 方式（`vaio-agent update`）保留不变。

## 4. 面板（子任务 3）

### 4.1 模式与切换
- 节点详情显示「用户管理：脚本 / 平台」，按钮「切换为平台管理」或「切回脚本管理」（仅 `authority_version=1` 的在线节点）。
- 切到平台：弹窗显示该节点现有的用户数（按实例），说明会删除全部用户和凭据、客户端失效，要求输入节点名确认；下发 `platform_apply {ops:[{op:"set_authority",mode:"platform"}]}`。
- 切回脚本：二次确认；下发 `set_authority script`；任务成功后删除该节点的全部关联（平台用户本身保留）。
- 新接口 `POST /api/nodes/<id>/authority {mode, confirm}`，校验 confirm 等于节点名（切到平台时）。

### 4.2 平台模式同步简化
- 删除三方合并：`ingest` 只累计用量；`plan` 直接比较面板字段和节点值，不同就下发 `update`（带节点当前 rev）。
- 删除认领节点统一用户（`account_id` 参数、`prefer`、「未关联的统一用户」区块）。`platform_links.base`、`platform_users.mtime` 不再使用（列保留，避免迁移）。
- `add_link` 要求节点为平台模式。
- 协议用户的「归入」保留，用于把面板安装的 SS/Snell 实例（安装时用户名填平台用户名）归入平台用户。

### 4.3 只读与旧节点
- `authority_version=1` 的节点：实例弹窗不显示编辑、新增、删除用户按钮；脚本模式显示「用户由节点脚本管理」，平台模式显示「在用户管理中修改」。`create_task` 拒绝这些节点的 `user_*` 任务。
- 旧节点：保持现状。

### 4.4 一键升级
- 节点详情的升级提示：节点上报 `upgrade_version=1` 时显示「一键升级」按钮（需要在线、未维护、无未完成任务），否则保留现在的 SSH 命令。
- `POST /api/nodes/<id>/upgrade` 创建 `agent_upgrade` 任务。升级中节点会进入维护模式（现有逻辑），界面显示「升级中」；完成后显示 `last_upgrade` 的结果和时间。

## 5. 兼容与回滚
- 面板 0.3.0-preview.12 + 旧 Agent：行为与现在相同。
- 节点升级后默认脚本模式：「香港维多利亚」升级节点程序后，面板对它的用户变成只读，直到管理员切换为平台模式（切换会清空现有用户，需要谨慎）。文档里写清楚。
- 脚本回滚到 preview.4：`meta.user_authority` 会被忽略，菜单不再锁定。
- 已部署的 preview.11 测试面板没有平台用户数据，删除三方合并不需要数据迁移。
