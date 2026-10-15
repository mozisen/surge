# 设计

## 数据
- `platform_users` 增加 `password_hash TEXT`（NULL 表示未开启登录）。迁移用 `ALTER TABLE ... ADD COLUMN`，放在 `platform_users` 现有的迁移入口里。
- 新表 `user_sessions(token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL, user_id TEXT NOT NULL)`，token 存 sha256。
- 通知设置增加 `bot_username`：启用机器人时保存 getMe 的用户名。旧数据没有该字段，用户页第一次读取时调用一次 getMe 补存，失败只显示「已启用」。

## 登录与鉴权
- `POST /api/login`：先按管理员校验（行为不变）。不匹配时按平台用户名查找已开启登录、未在删除中的用户，校验密码。成功后写 `user_sessions`，响应 `{csrf, version, role: "user"}`；管理员响应增加 `role: "admin"`。失败计数仍写 `attempts`。
- 已停用、到期或超额的用户可以登录，只能查看自己的状态。
- 新装饰器 `portal`：只查 `user_sessions`，校验 CSRF，设置 `g.user`。`admin` 装饰器不变，只认 `sessions` 表，所以用户 cookie 访问管理接口一律 401。
- `POST /api/logout` 去掉 `@admin`：按 cookie 删除两张表里对应的会话。

## 用户接口（全部 `@portal`）
- `GET /api/me`：`{name, state, used, quota, expire_date, reset_day, cycle, csrf, version, links:[{id, node_name, online, cycle_used, members:[{core, protocol, port, enabled}]}], relays:[{id, chain:[服务器名], entry:"host:port", protocol, state, port_only}], telegram:{bot_enabled, bot_username, bound, username, bound_at, code_pending}}`。不含 note、node_id、account_id、landing_host。
- `POST /api/me/share`：`{link_id, core, protocol, port}` 或 `{relay_id}`。校验关联或线路属于本人，成员存在且启用、节点在线、不在维护。用户已有 queued 或 running 的导出时拒绝。任务 `request_key = "user-share:<user_id>:<uuid>"`，审计 `portal.share`。复用 `relays.share` 的线路导出逻辑：参数化 request_key 前缀。
- `GET /api/me/tasks/<id>`：只返回 request_key 以 `user-share:<本人>:` 开头的任务，字段 `{status, message, connection}`，不含 `config_details`，10 分钟过期。`GET /api/me/tasks/<id>/qr` 同样校验。二维码生成抽成共用函数。
- `POST /api/me/tg-code`、`POST /api/me/tg-unbind`：调用 `monitor.new_code`、`monitor.unbind`。机器人未启用时拒绝生成绑定码。
- `POST /api/me/password`：`{current_password, new_password, confirm_password}`，8–128 位；按 `attempts` 键 `user:<id>` 限流。成功后删除该用户全部会话并清除 cookie。

## 管理员接口
- `POST /api/users/<id>/login`：`{password}` 设置或重置密码并开启登录；`{enabled:false}` 关闭登录。两种都删除该用户会话，审计。
- 与管理员同名时拒绝开启登录。`/api/account` 改名时检查是否与已开启登录的用户重名。
- 用户详情与列表返回 `login_enabled`。删除用户时一并删除其会话。

## 前端
- 启动：`/api/session` 返回 401 时再试 `/api/me`，成功进入 `portal()`，否则显示登录页。登录响应按 `role` 分流。
- `portal()`：独立外壳，不含管理导航。顶栏显示品牌、用户名、「修改密码」「退出」，下面依次为账号概览、我的协议、中转线路、Telegram 四块。点「连接信息」后轮询 `/api/me/tasks/<id>`，弹窗显示连接、复制按钮和二维码。每 30 秒刷新一次 `/api/me`。
- 管理员用户详情增加「登录」区：显示是否已开启，提供「设置密码」「关闭登录」。
- 前端代码放在 app.js 新的「用户自助」段（在 用户管理 标记之后，便于 cjs 测试）。

## 兼容与回滚
- 只增加列和表，旧版本会忽略。回滚到 1.2.x 后用户无法登录，管理员不受影响。
- 节点程序不需要改动（导出连接沿用现有 share 任务）。
