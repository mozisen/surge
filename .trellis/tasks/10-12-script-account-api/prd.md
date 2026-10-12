# 脚本统一用户接口（3.7.4-preview.4）

父任务：`10-12-platform-user-management`。技术设计见父任务 `design.md` §3。依赖子任务 `10-12-script-accounts`（数据结构和执行逻辑），必须在它完成之后开始。

## Requirements
- `capabilities` 宣告 `accounts_api_version:1`、`write_actions:["account_apply"]`；协议级的 `write_supported` 保持 false。
- `inventory` 输出 `accounts`（不含凭据）、协议用户的 `account_id`，以及 `config_revision`。
- `account_apply` 支持 create/update/link/unlink/block/member_add/member_claim/member_remove/reset_credentials/reset_usage/delete，在一个事务里完成：`.txn.lock`、幂等记录、备份、整体校验、一次写库、每个核心重建一次、服务校验、失败回滚、结果持久化；带 base_rev 的操作在 rev 不一致时返回 `rev_conflict`。
- `result` 按 request_id 返回已存结果，不重放。
- 菜单修改和 API 修改维护同一套 rev 和 mtime。

## Acceptance Criteria
- [ ] `tests/accounts-api.sh`：各操作、rev_conflict、幂等重放、指纹冲突、单条校验失败时整体不写入、重建失败回滚、遗留 running 意图返回 unknown、inventory 不含凭据
- [ ] 现有 `tests/*.sh` 全部通过；`bash -n` 通过；vendor 同步
- [ ] `docs/script-accounts.md` 增加接口一节
