# 执行计划

父任务不直接写代码，按顺序启动 3 个子任务，每个子任务各自完成 prd 的验收、检查和提交，并推送到 `codex/platform-3.7.4`。

## 顺序

1. `script-user-api`（脚本 3.7.4-preview.3）：design §5
2. `agent-platform-users`（Agent 0.3.0-preview.11）：design §6；依赖 1 的 `--api user_apply` 契约
3. `panel-platform-users`（面板 0.3.0-preview.11）：design §2–4、§7；依赖 2 的快照字段和 `platform_apply`

## 通用检查（每个子任务提交前）

```sh
bash -n vless-server.sh
for t in tests/*.sh; do bash "$t" || echo "FAILED $t"; done   # singbox-stats-live.sh 需要真实统计核心，本机跳过并说明
cd platform && .venv/bin/python -m unittest discover -s tests -v
node --check web/app.js && node tests/install-form.cjs && node tests/traffic-display.cjs   # 本机无 Node，以 GitHub Actions 为准
```

本机默认 Bash 3.2，脚本测试需要 Bash 4.1+：用 Homebrew bash 运行，或者以 GitHub Actions 为准，并如实说明。

## 子任务 1：脚本
- [ ] `capabilities`：users_api_version、write_actions、stage
- [ ] `inventory`：platform_user_id、disable_reason、raw_used、config_revision
- [ ] `user_apply`：校验 → .txn.lock → 幂等记录 → 备份 → 内存变更 → `_db_apply` → 重建 → 校验 → 结果；失败时回滚
- [ ] `result`：按 request_id 返回已存结果
- [ ] 菜单保护、月重置跳过、卸载时的提示
- [ ] 新测试 `tests/platform-users-api.sh`：create/claim/update/release/delete、幂等重放、指纹冲突、校验失败不写入、重建失败回滚、running 意图返回 unknown、菜单拒绝修改平台用户、月重置跳过
- [ ] 同步 `platform/vendor/vless-server.sh`、`UPSTREAM_SHA`、`platform/vendor/README.md`；`docs/platform-users-script.md`
- 回滚点：一个 `feat:` 提交加一个 `chore:` 同步提交

## 子任务 2：Agent
- [ ] `ScriptAPI.write` 和 `result`；能力检查改为接受 stage `user_write`
- [ ] 快照字段与 `sanitize_snapshot`
- [ ] `vaio/common.py`：`platform_apply` 校验（Agent 和面板共用）
- [ ] `Bridge`：`.txn.lock`、platform_apply 执行、实例任务拒绝修改平台用户
- [ ] 测试：`tests/test_platform_users_agent.py`（模拟脚本 API：成功、失败、unknown 后查询、超时、指纹冲突、锁顺序）
- 回滚点：一个 `feat:` 提交

## 子任务 3：面板
- [ ] Store 迁移 v2，备份校验接受 v2
- [ ] 用量累计（poll 事务内）、周期切换、期望状态计算、调度入队、任务结果回写绑定
- [ ] REST：`/api/users`、`/api/users/<id>`、`/api/users/<id>/bindings`、认领、解除、删除、重置用量、重置凭据
- [ ] 监控告警改为按平台用户
- [ ] 前端：用户管理列表与详情、添加绑定、实例弹窗联动、流量页平台用户表
- [ ] 测试：`tests/test_platform_users_panel.py`（跨节点累计、超额全停与周期恢复、到期与延长、认领保留用量、离线待同步、旧 Agent 拒绝、去重入队、unknown 阻塞、备份恢复 v1/v2）；`tests/platform-users.cjs`（界面渲染和元素 id）
- [ ] 本地预览：模拟节点 preview.py 截图检查（参考 scratchpad 方法）
- [ ] `platform/docs/platform-users.md`，版本号 0.3.0-preview.11
- 回滚点：后端和前端各一个 `feat:` 提交

## 父任务收尾
- [ ] 本地端到端联调：面板 + 2 个模拟节点（Agent + 隔离的脚本 cfg 目录）
- [ ] `docs/platform-user-management.md`：版本、改动、隔离测试结果；真实 VPS 验收单独一节，未授权则写「未执行」
- [ ] 更新 CLAUDE.md 的版本行与 `docs/platform-3.7.4-merge.md`
- [ ] 推送后检查 GitHub Actions；不发 Release，不操作「香港维多利亚」等生产节点
