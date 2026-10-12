# 脚本统一用户接口（3.7.4-preview.4）

父任务：`10-12-platform-user-management`。技术设计见父任务 `design.md` §3。依赖子任务 `10-12-script-accounts`（数据结构和执行逻辑），必须在它完成之后开始。

## Requirements
- `capabilities` 用 `accounts_api.version:1` 声明统一用户接口；`stage` 和 `write_actions:[]` 保持不变，以兼容现有 Agent 的接口检查。
- `inventory` 输出 `accounts`（不含凭据）和协议用户的 `account_id`。（实现时决定不提供 config_revision，并发控制用统一用户的 rev。）
- `account_apply` 支持 create/update/link/unlink/block/member_add/member_claim/member_remove/reset_credentials/reset_usage/delete，在一个事务里完成：`.txn.lock`、幂等记录、备份、整体校验、一次写库、每个核心重建一次、服务校验、失败回滚、结果持久化；带 base_rev 的操作在 rev 不一致时返回 `rev_conflict`。
- `result` 按 request_id 返回已存结果，不重放。
- 菜单修改和 API 修改维护同一套 rev 和 mtime。

## Acceptance Criteria
- [x] `tests/accounts-api.sh`：各操作、rev_conflict、幂等重放、指纹冲突、单条校验失败时整体不写入、重建失败回滚、遗留 running 意图返回 unknown、inventory 不含凭据
- [x] 现有 `tests/*.sh` 全部通过；`bash -n` 通过；vendor 同步
- [x] `docs/script-accounts.md` 增加接口一节
