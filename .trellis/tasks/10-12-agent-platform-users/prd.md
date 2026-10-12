# Agent 统一用户同步（0.3.0-preview.11）

父任务：`10-12-platform-user-management`。技术设计见父任务 `design.md` §4。依赖子任务 `10-12-script-account-api`，必须在它完成之后开始。

## Requirements
- 脚本宣告 `accounts_api_version:1` 且校验和匹配时，快照上报 `accounts_version:1` 和 `accounts`；`sanitize_snapshot` 严格归一化（格式和数量上限）。
- `vaio/common.py` 新增 `platform_apply` 校验（面板和 Agent 共用）。
- Agent 执行 `platform_apply`：沿用任务意图记录（不重放）和 enforcement-pending 阻塞，调用脚本 `account_apply`（request_id = 任务 ID），结果不明时先查询 `result`；`rev_conflict` 记为 failed 并带上冲突信息。
- 新增 `.txn.lock`，Agent 事务和 reconcile 先拿它；调用脚本时不持有任何锁。
- 实例任务拒绝修改统一用户成员的到期、配额、重置日、启停，也拒绝删除成员；share、inspect、reset_credentials 允许。

## Acceptance Criteria
- [ ] `tests/test_platform_users_agent.py`：能力协商（旧脚本、校验和不符时不宣告）、成功、失败、rev_conflict、unknown 后查询、超时、指纹冲突、锁顺序、实例任务拒绝、快照归一化
- [ ] 现有 unittest 全部通过
