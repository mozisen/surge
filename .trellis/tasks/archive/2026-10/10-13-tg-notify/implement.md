# 实施计划
1. 脚本：`_tg_platform_cleanup` 与调用点、发送函数和菜单的平台模式守卫；新增 `tests/tg-platform.sh`；版本 3.7.4-preview.8；同步 vendor 副本、UPSTREAM_SHA、vendor README。验证 `bash -n`、脚本测试。
2. 面板后端：monitor.py 设置结构与迁移、队列不留记录、用户提醒、阈值、每日报告、机器人轮询与命令；platform_users 删除级联；server.py 接口；backups 恢复时的 notifications 处理。unittest：新 `tests/test_notify.py`，修改 test_billing_monitor。
3. 前端：导航改名、通知配置页、设置弹窗、绑定码弹窗；cjs 测试。
4. 版本 0.3.0-preview.19；文档 platform/docs/platform-users.md、docs/script-accounts.md。
5. 全部测试、本地预览截图（1280/375）、提交（脚本、面板、文档分开）、推送、CI。
回滚点：每步一个提交。
