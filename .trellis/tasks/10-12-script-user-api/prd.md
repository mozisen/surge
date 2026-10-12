# 脚本平台用户写接口（3.7.4-preview.3）

父任务：`10-12-platform-user-management`。技术设计见父任务 `design.md` §5，执行清单见父任务 `implement.md`「子任务 1」。

## Requirements
- `--api capabilities` 宣告 `users_api_version:1`、`write_actions:["user_apply"]`；协议级的 `write_supported` 保持 false。
- `--api inventory` 给用户输出 `platform_user_id`、`disable_reason`、`raw_used`，给实例输出 `config_revision`；不输出凭据。
- `--api user_apply` 支持 create/claim/update/release/delete，全部在一个事务里完成：互斥锁、幂等记录、备份、整体校验、一次写库、每个核心重建一次、服务校验、失败回滚、结果持久化。
- `--api result` 按 request_id 返回已存结果，不重放。
- 交互菜单不能修改平台用户（配额、到期、启停、删除、重置流量、TG 绑定），给出中文提示；月度重置跳过平台用户；到期检查仍然停用到期的平台用户。
- 同步 vendor 副本、`UPSTREAM_SHA`、vendor README。

## Acceptance Criteria
- [ ] `tests/platform-users-api.sh` 覆盖：五种操作、幂等重放、指纹冲突、单条校验失败时整体不写入、重建失败回滚、遗留 running 意图返回 unknown、菜单拒绝、月重置跳过
- [ ] 现有 `tests/*.sh` 全部通过（singbox-stats-live.sh 除外，需要说明）
- [ ] `bash -n` 通过；vendor 副本逐字节一致，SHA 正确
- [ ] `docs/platform-users-script.md` 记录版本、接口、测试结果，隔离测试和真实验收分开写
