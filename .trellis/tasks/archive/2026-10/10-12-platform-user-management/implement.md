# 执行计划

父任务不直接写代码。按顺序启动 4 个子任务，每个子任务各自完成验收、检查和提交，并推送到 `codex/platform-3.7.4`。

## 顺序与依赖

1. `10-12-script-accounts`：脚本统一用户，可独立运行（脚本 3.7.4-preview.3），见 design §2
2. `10-12-script-account-api`：脚本 `--api account_apply`（3.7.4-preview.4），见 design §3，依赖 1
3. `10-12-agent-platform-users`：Agent（0.3.0-preview.11），见 design §4，依赖 2
4. `10-12-panel-platform-users`：面板（0.3.0-preview.11），见 design §5，依赖 3

1 完成后就可以交付「脚本独立使用统一用户」，不必等后面的子任务。

## 通用检查（每个子任务提交前）

```sh
bash -n vless-server.sh
for t in tests/*.sh; do bash "$t" || echo "FAILED $t"; done   # singbox-stats-live.sh 需要真实统计核心，本机跳过并说明
cd platform && .venv/bin/python -m unittest discover -s tests -v
node --check web/app.js && node tests/install-form.cjs && node tests/traffic-display.cjs   # 本机无 Node，以 GitHub Actions 为准
```

本机默认 Bash 3.2，脚本要求 Bash 4.1+：先确认有没有 Homebrew bash；没有就以 GitHub Actions 为准，并如实说明。

## 子任务 1：脚本统一用户
- [ ] 数据层：`db_account_*` 系列函数（创建、读取、更新同步字段并维护 rev/mtime、加/移成员、归入、删除），全部用 `_db_apply` 和 jq 传参
- [ ] 派生：成员的 expire_date、quota=0、enabled、disable_reason 跟随统一用户（一个纯 jq 函数，便于测试）
- [ ] 执行：`_sync_accounts`（用量增量、周期、状态），接在 `--sync-traffic` 之后和 `--check-expire` 中；状态变化时每个核心重建一次
- [ ] 月重置和配额停用跳过成员
- [ ] 菜单：「统一用户」子菜单、归入、批量归并预览、按协议菜单中的成员标注和引导、解除平台关联
- [ ] `tests/accounts.sh`
- [ ] vendor 同步，`docs/script-accounts.md`
- 回滚点：`feat:` 提交（数据层 + 执行）、`feat:` 提交（菜单）、`chore:` 提交（vendor 同步）

## 子任务 2：脚本接口
- [ ] capabilities、inventory（accounts、account_id、config_revision）
- [ ] `account_apply` 事务与 `result`
- [ ] `tests/accounts-api.sh`；vendor 同步；文档补充接口一节
- 回滚点：`feat:` + `chore:`

## 子任务 3：Agent
- [ ] `ScriptAPI.write`/`result`，能力检查接受 stage `account_write`
- [ ] 快照字段与 `sanitize_snapshot`；`validate_platform_task`
- [ ] `.txn.lock`、platform_apply 执行、实例任务拒绝修改成员
- [ ] `tests/test_platform_users_agent.py`
- 回滚点：`feat:`

## 子任务 4：面板
- [ ] Store v2 迁移、备份校验
- [ ] 三方合并、用量累计、平台周期、block、调度入队、任务结果回写
- [ ] REST 接口、监控告警
- [ ] 前端：用户管理、关联与认领、实例弹窗联动、流量页按用户汇总
- [ ] `tests/test_platform_users_panel.py`、`tests/platform-users.cjs`（加入 CI）
- [ ] 本地预览截图；`platform/docs/platform-users.md`；版本 0.3.0-preview.11
- 回滚点：后端 `feat:`、前端 `feat:`

## 父任务收尾
- [ ] 本地端到端联调：面板 + 2 个模拟节点（Agent + 隔离的脚本 cfg 目录），覆盖双向同步和跨节点配额
- [ ] `docs/platform-user-management.md`：版本、改动、隔离测试结果；真实 VPS 验收单独一节，未授权则写「未执行」
- [ ] 更新 CLAUDE.md 的版本行与 `docs/platform-3.7.4-merge.md`
- [ ] 推送后检查 GitHub Actions；不发 Release，不操作「香港维多利亚」等生产节点
