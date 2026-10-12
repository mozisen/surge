# 执行计划

按顺序实现 3 个子任务，每个子任务单独提交、通过检查后推送 `codex/platform-3.7.4`。

## 子任务 1：脚本（3.7.4-preview.5）
- [ ] `db_authority_get`、`_authority_clear_users`（jq）、`db_authority_set`（平台：备份 → 清空 → 重建 → 失败恢复；脚本：解除平台字段）
- [ ] `_authority_guard` 加到全部用户写入口；用户管理页显示模式，平台模式菜单收缩；切换菜单（CLEAR 确认）
- [ ] `--api`：`set_authority`、脚本模式拒绝其他操作、`accounts_api.version=2`、`user_authority` 字段
- [ ] 测试：`tests/user-authority.sh`（清空覆盖多用户/SS/Snell/旧单用户实例/TG/统一用户，旧凭据不残留；失败回滚；切回保留；守卫；菜单冒烟）；`tests/accounts-api.sh`、`tests/accounts-cli.sh` 补充 set_authority
- [ ] vendor 同步，`docs/script-accounts.md` 更新

## 子任务 2：Agent（0.3.0-preview.12）
- [ ] 快照 `user_authority`、`authority_version`、`upgrade_version`、`last_upgrade`；sanitize
- [ ] 拒绝 `user_*` 任务；`validate_platform_task` 支持 `set_authority`
- [ ] `agent_upgrade` 任务：独立单元启动升级器；`update-agent.py --task`（等待上报、主脚本替换与回滚、结果文件）
- [ ] 测试：`tests/test_agent_upgrade.py`（命令构造：systemd/OpenRC；等待上报；成功、新版未上线回滚、校验失败、主脚本 SHA 不符；结果文件；快照字段）

## 子任务 3：面板（0.3.0-preview.12）
- [ ] 删除三方合并与认领；`add_link` 要求平台模式；切回脚本删除关联
- [ ] `POST /api/nodes/<id>/authority`、`POST /api/nodes/<id>/upgrade`；`create_task` 对新节点拒绝 `user_*`
- [ ] 界面：节点详情模式与切换（输入节点名确认）、实例弹窗只读、用户管理页移除认领区块、一键升级按钮与结果
- [ ] 测试：更新 `test_platform_users_panel.py`、`platform-users.cjs`；新增模式切换、只读、升级任务测试
- [ ] 本地预览截图；`platform/docs/platform-users.md`、`docs/platform-user-management.md` 更新

## 检查
```sh
bash -n vless-server.sh
for t in tests/*.sh; do bash "$t" </dev/null || echo "FAILED $t"; done
cd platform && <venv>/bin/python -m unittest discover -s tests
node --check web/app.js && node tests/install-form.cjs && node tests/traffic-display.cjs && node tests/platform-users.cjs
```
推送后以 GitHub Actions 为准。不部署、不操作节点；测试面板部署需要另行指示。
