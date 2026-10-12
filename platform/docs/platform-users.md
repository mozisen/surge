# 平台统一用户

本文档跟踪平台统一用户在 Agent 和面板中的实现。节点脚本部分见 `docs/script-accounts.md`，跨层设计见 `.trellis/tasks/10-12-platform-user-management/design.md`。分支 `codex/platform-3.7.4`，只推送预览分支，不创建 GitHub Release。

## Agent（子任务 3）

Agent 和面板共用版本号，这一步不单独升版本；面板子任务完成时一起升到 `0.3.0-preview.11`。

### 快照
- 新增 `accounts`：节点统一用户的全部字段（名称、备注、启停、到期、配额、重置日、周期、本周期用量、`rev`、各字段 `mtime`、平台关联与停用标记）、按脚本规则计算的状态 `state`（manual > expired > quota > platform_quota），以及每个成员的协议、端口、用户名、当前累计计数、启停和停用原因。不含任何凭据。
- 实例用户新增 `account_id`。
- 新增 `accounts_version`：只有当脚本接口的能力声明里有 `accounts_api.version == 1` 并且包含 `account_apply` 时才为 1。面板只对值为 1 的节点开放关联和同步。
- 面板的 `sanitize_snapshot` 会严格归一化这些字段：最多 1000 个统一用户，每个最多 50 个成员，合计最多 20000 个；id 必须是 uuid；名称、日期、整数、枚举格式不对的一律清空或置 0；结构错误时拒绝整个快照。

### 任务 `platform_apply`
```json
{"id":"<任务ID>","action":"platform_apply","params":{"ops":[ ... ]}}
```
- 操作格式与脚本的 `account_apply` 相同，由 `vaio/common.py:validate_platform_task` 校验，面板和 Agent 共用这一份校验。
- Agent 沿用现有的任务意图记录（指纹、结果不明时不重放）和 enforcement-pending 阻塞，用任务 ID 作为脚本的 `request_id` 调用 `account_apply`。
- 进程超时或返回 unknown 时，先调用 `result` 查询；仍然不确定就记为 unknown，等人工核对。
- 节点拒绝的情况（`rev_conflict` 会带上节点当前的版本号、账户不存在、Snell 限制等）记为 failed，这时节点上没有任何写入；`apply_failed` 表示节点已回滚。成功时只返回各统一用户的 `rev` 和是否存在。
- 脚本接口不可用（例如 Agent 使用了非默认的配置目录）时直接失败，不写入。

### 锁与结算
- 新增 `$CFG/.txn.lock`：Agent 的实例事务和 reconcile 都先拿这把锁，再拿 `.db.lock`。调用脚本 `account_apply` 时 Agent 不持有任何锁，由脚本自己拿 `.txn.lock`，避免死锁。
- reconcile（每 60 秒）会通过随 Agent 分发的脚本副本运行一次统一用户结算 `accounts_apply`（已加入 Agent 的脚本函数白名单），这样即使节点上安装的主脚本较旧，到期和合计配额也照样生效。结算失败只记日志，不影响后面的到期检查。

### 实例任务的限制
统一用户的成员协议用户：实例任务里修改配额、重置日、到期、启停，以及删除这个用户，都会被拒绝，提示去修改统一用户。重置凭据、查看连接信息、检查仍然可以单独操作。

### 测试
**隔离测试：** 新增 `tests/test_platform_users_agent.py`，共 15 项：任务校验（全部操作合法；空列表、超过 200 项、多余字段、非 uuid、未知字段、换行备注、越界重置日、布尔版本号、未知停用原因、越界端口、缺少名称、错误动作都被拒绝）；脚本接口能力解析，不认识的声明按不可用处理；写入和查询请求的结构，查询不复用任务 ID，请求 ID 必须是 uuid；响应的请求 ID 和状态都会校验；成功结果会记录，再次执行不会重放；版本冲突和已回滚的失败；超时后用查询确认结果，unknown 不重放；脚本接口不可用、待核对的自动策略会阻塞执行；实例事务持有共享锁，而 platform_apply 执行期间不持锁；实例任务拒绝修改成员的策略字段，但允许重置凭据；结算会经过脚本执行，失败不阻塞；快照里不含凭据，并带上状态、成员和 `account_id`；不可信数据会被清洗或拒绝；Agent 按脚本接口能力上报 `accounts_version`。全部 unittest 108 项通过（跳过 2 项），脚本测试全部通过。

**真实验收：** 未执行。没有在 VPS 上运行 Agent 和脚本写接口的端到端流程，也没有操作生产节点。
