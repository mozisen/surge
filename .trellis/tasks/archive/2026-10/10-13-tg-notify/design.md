# 设计

## 面板数据
- `settings['notifications']` JSON 改为：`enabled, bot_token, chat_id, quota_percent(80), daily_enabled(false), daily_time("09:00"), bot_enabled(false), bot_offset(0)`。读取时兼容旧键（`telegram_token`→`bot_token`，`telegram_chat`→`chat_id`），丢弃 `webhook`。旧配置只有 Webhook 时视为未配置并关闭通知。
- 新表 `platform_tg(user_id PK → platform_users ON DELETE CASCADE, chat_id, username, bound_at, code_hash, code_expires)`，用 `CREATE TABLE IF NOT EXISTS`，不改 user_version（与 platform_* 表一致；表不存在即无绑定）。chat_id 唯一索引保证一个 Telegram 只绑定一个用户。
- `notifications` 表加列 `chat_id TEXT`（空 = 管理员）；`store` 启动时按 `PRAGMA table_info` 补列。
- 设置键 `notify_test_at`、`daily_report_day` 用于测试限流和每日报告去重。

## 发送
- `transition()` 仍记录 incident 状态变化，入队 `(at,title,status,chat_id)`。`send_pending()`：领取 pending → sending，发送后直接 DELETE；启动时把遗留 sending 行删除（不重发，可能已送达）；关闭通知时 pending 行直接删除。不再按 30 天保留。
- Telegram 发送统一 `tg_call(token, method, params)`：POST JSON，拒绝重定向，超时 10s，异常不记录文本（URL 含 Token）。
- 用户提醒：扫描平台用户时，对已绑定且机器人启用的用户额外入队一条给其 chat_id 的消息（同一 transition 触发，激活时发送；恢复不发给用户）。

## 机器人
- 监控 worker 已经是 flock 选举的单实例。循环改为每 10 秒：机器人轮询（`getUpdates` offset，timeout 0，limit 100），每 30 秒一次 scan/send/备份，每日报告在到点且当天未发时入队。
- 处理更新：仅 `message.chat.type == private`；命令解析同脚本。绑定：码规范化为大写 12 位十六进制，sha256 摘要匹配未过期 code_hash；该 chat 已绑定则提示先解绑；成功后清除 code。
- `/traffic` `/status` 使用 `platform_users.usage()` 与 links 汇总。
- 启用接口：`getMe` 校验 → `deleteWebhook` → `setMyCommands` → 保存 `bot_enabled=true`。

## 接口
- `GET /api/monitor` → `{config(无 token, token_configured), heartbeat, users:[{id,name,bound,username,bound_at,code_pending}]}`；不再返回 events。
- `POST /api/monitor` 保存设置（字段白名单与校验：Token 格式、Chat ID 格式、阈值 50–99 整数、时间 HH:MM）。
- `POST /api/monitor/test`（1 分钟限流）、`POST /api/monitor/bot`（{enabled}）、`POST /api/users/<id>/tg-code` → `{code, expires}`、`DELETE /api/users/<id>/tg`。均审计，审计不含 Token 与绑定码。

## 前端
- 导航名改「通知配置」。页面：状态面板（TG 通知、Bot Token、Chat ID、告警阈值、每日报告、用户机器人、已绑定数），按钮「通知设置」「测试发送」「启用/禁用用户机器人」；下方「用户绑定」表：用户、绑定状态、操作（生成绑定码 / 解除绑定）；生成后弹窗显示 `/bind CODE` 与有效期，提示只显示一次。机器人命令说明放页面说明文字。

## 脚本
- 新函数 `_tg_platform_cleanup`：authority=platform 时，若 TG 配置非默认则写回默认值（保留文件、600 权限），移除 tg-user-bot cron；幂等。
- 调用点：`_authority_apply platform` 末尾、`--tg-bot-poll`、`sync_all_user_traffic` 入口（平台模式）、`_configure_tg_notify` 入口。
- `tg_send_message`、`tg_send_bound_user_message`、`check_daily_report` 在平台模式直接返回。菜单在平台模式显示说明后返回。

## 兼容与回滚
- 旧面板数据库：新表/列自动创建；旧设置键自动迁移。回滚旧面板：旧面板只认 telegram_token/telegram_chat，迁移时同时保留这两个旧键的值，回滚后管理员通知仍可用（用户绑定在旧版不可用）。
- 节点无需升级节点程序即可使用平台通知；脚本清理需随一键升级下发新脚本。
