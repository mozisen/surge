# Telegram 用户机器人启用修复

截图表明 cron 规则已写入但守护进程未运行，不能仅据此判定具体服务器是缺包、服务被屏蔽还是启动错误。

本次修复检查完整 cron 依赖，主动启用时补装缺失组件；支持 systemd、OpenRC 及无 init 环境的 cron/crond。服务 enable 与 start 分离，不主动解除 masked 状态、不绕过失效的受管服务。后台自动修复不安装软件。

先确认 cron 可运行再写规则，先确认本地轮询再切换 webhook；检查 Telegram 成功响应，失败时保持机器人未启用。TG 两处菜单仅显示 Token 已配置状态，不再泄露原文。

如仍失败，请提供 `/etc/vless-reality/cron-service.log` 中的错误。该文件权限为 600，包含服务和包管理器诊断，不写入 Token。

发布版本：`3.7.3-preview.quota.5`，GitHub 测试分支 `codex/ss-user-fix`，不创建 Release、不部署服务器。

验证：`tests/tg-bot-cron.sh` 隔离模拟、现有 Shell 回归及语法检查。没有真实 VPS/Telegram 测试；需要真实统计核心的 `singbox-stats-live.sh` 未运行。
