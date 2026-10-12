# 面板平台用户管理（0.3.0-preview.11）

父任务：`10-12-platform-user-management`。技术设计见父任务 `design.md` §5、§6。依赖子任务 `10-12-agent-platform-users`。

## Requirements
- SQLite 迁移到 user_version 2：`platform_users`、`platform_links`（平台用户 ↔ 节点统一用户）；备份校验接受 v2，旧的 v1 备份恢复后自动补表。
- 双向同步：基准、节点、面板三方逐字段合并，后改的生效，冲突时提示并写审计。
- poll 时按成员的原始计数累计每个关联的周期用量；按用户的重置日（面板时区）切换周期；派生到期、超额、手动停用状态。
- 跨节点超额时对所有节点下发 block，恢复后解除。
- 调度：按节点合并下发 `platform_apply`，相同差异不重复入队；离线节点显示待同步；unknown 任务阻塞，等人工核对。
- 管理员接口：用户增删改查、关联节点（在节点新建统一用户，或认领已有统一用户）、协议用户归入、解除关联、删除节点统一用户、重置用量、重置凭据（单个或全部）。
- 告警改为按平台用户：80%、超额、3 天内到期、同步失败。
- 界面：「用户管理」列表（含未关联的节点统一用户）和详情、关联弹窗、实例弹窗联动（成员标记、归入）、流量页平台用户汇总。中文文案、黑白简约，遵守组件规范，保持现有元素 id。

## Acceptance Criteria
- [x] `tests/test_platform_users_panel.py`：三方合并（仅节点改、仅面板改、两边都改）、跨节点累计、超额 block 和周期恢复、到期同步、认领保留用量、离线待同步、旧 Agent 拒绝绑定、入队去重、unknown 阻塞、备份 v1/v2 恢复、接口鉴权和 CSRF
- [x] `tests/platform-users.cjs` 加入 CI；现有 cjs 测试不变（本机无 Node，以 Actions 为准）
- [x] 本地预览截图检查列表、详情、关联弹窗
- [x] `platform/docs/platform-users.md`；版本号 0.3.0-preview.11
