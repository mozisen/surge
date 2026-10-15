# 实施步骤

1. 后端数据：`platform_users.password_hash` 迁移、`user_sessions` 表，通知设置保存 `bot_username`。
2. 鉴权：拆分 login（管理员 → 用户）；`portal` 装饰器；logout 同时处理两种会话；管理员同名检查；删除用户时清会话。
3. 用户接口：`/api/me`、share（关联与线路，单任务限制）、tasks 与 qr（共用二维码函数）、TG 绑定码与解绑、改密码。
4. 管理员接口 `/api/users/<id>/login`，并在 describe 中返回 `login_enabled`。
5. 前端：启动与登录分流、`portal()` 页面与样式、连接弹窗、TG 卡片、改密码；管理员用户详情的登录区。
6. 测试：新增 `tests/test_user_portal.py`（含遍历全部 `/api/` 管理路由确认用户会话 401）；`platform-users.cjs` 增加用户页与管理员登录区。
7. 本地预览截图 1280 / 375；版本 1.3.0、CHANGELOG、README；全部测试、提交、推送、CI。

验证命令：`python -m unittest discover -s tests`、三个 cjs 测试、`node --check web/app.js`。
回滚点：每步一个提交，可单独回退。
