# Agent 平台用户同步（0.3.0-preview.11）

父任务：`10-12-platform-user-management`。技术设计见父任务 `design.md` §4、§6。依赖子任务 `10-12-script-user-api` 的 `user_apply` 契约，必须在它完成之后开始。

## Requirements
- 脚本 API 宣告用户写能力并且校验和匹配时，快照上报 `platform_users_version:1`；users 带 `platform_user_id`、`disable_reason`、`raw_used`；`sanitize_snapshot` 严格归一化这些字段。
- `vaio/common.py` 新增 `platform_apply` 任务校验（面板和 Agent 共用），最多 200 条变更，字段白名单。
- Agent 执行 `platform_apply`：沿用任务意图记录（不重放）和 enforcement-pending 阻塞；调用脚本 `user_apply`（request_id = 任务 ID），结果不明时先用 `result` 查询。
- 新增 `.txn.lock`，Agent 事务和 reconcile 先拿它；调用脚本时不持有任何锁。
- 实例任务拒绝修改平台用户的配额、重置日，也拒绝删除平台用户。

## Acceptance Criteria
- [ ] `tests/test_platform_users_agent.py`：能力协商（旧脚本、校验和不符时不宣告）、成功、失败、unknown 后查询、超时、指纹冲突、锁顺序、实例任务拒绝
- [ ] 现有 unittest 全部通过
