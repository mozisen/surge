# 运维与恢复

## 文件位置

| 位置 | 内容 |
|---|---|
| 面板 `/app/data/panel.sqlite` | 管理员哈希、会话、节点、任务、审计 |
| 节点 `/etc/vaio-agent/config.json` | 面板地址和节点身份凭据，0600 |
| 节点 `/opt/vaio-agent` | Agent 程序及固定原脚本快照 |
| 节点 `/var/lib/vaio-agent/journal.json` | 执行记录，用于重启恢复与去重 |
| 节点 `/var/lib/vaio-agent/runtime.log` | 命令原始输出，可能含敏感信息，0600 |
| 节点 `/var/lib/vaio-agent/backups/{任务ID}` | 修改前数据库与配置文件、文件路径清单 |
| 节点 `/etc/vless-reality` | 原脚本数据库和协议配置 |

## 排错

面板：`docker compose logs --tail=100 panel caddy`。

节点 systemd：`systemctl status vaio-agent` 和 `journalctl -u vaio-agent -n 100`。

节点 OpenRC：`rc-service vaio-agent status`，日志在 `/var/lib/vaio-agent/agent.log`。

代理操作失败：在节点检查 `/var/lib/vaio-agent/runtime.log`。不要直接将包含凭据的完整日志公开上传。

Agent 网络失败最多退避至约 60 秒，恢复后自动重连。若注册成功但身份文件未成功保存，重新在面板生成安装脚本；旧注册令牌不会复用。

重新注册会撤销原节点身份、取消待执行任务并清除接管状态。运行中任务不允许重新注册。撤销节点身份无法中止已经在节点执行的任务。

## 恢复原则

自动回滚以恢复配置和服务为目标，不撤销系统包或二进制安装。报告“回滚未完全恢复”时，先停止 Agent，核对备份路径、目标实例以及共享服务，再人工恢复。

不要未经核对直接覆盖整个 `db.json`：备份之后的使用量、其他手动修改可能更晚。`manifest.json` 按顺序记录目标路径，数字文件为对应备份；原本不存在的文件没有备份。

当任务显示“待核对”，先检查节点当前端口/服务和本地 journal。系统不会重复执行有歧义的任务，也不能保证安装中断后无需人工恢复。

## 备份与保留

定期备份面板数据卷与各节点配置、备份目录。面板数据库使用 SQLite，在线备份请使用 SQLite backup API，或停止面板后复制数据库文件。

首版不自动删除操作审计、任务、节点 journal 和配置备份。根据节点规模自行制定保留策略，清理前备份；不要删除执行中任务的记录。runtime.log 达到 5 MiB 会在下次执行前截断。

## 更新与卸载

直接安装版：以 root 运行 `vaio-panel update`，可用 `--ref 提交SHA` 固定版本。升级器先准备独立环境并运行测试，确认没有排队/运行任务后停止面板、备份数据库和配置，再切换程序并检查健康状态。失败自动恢复旧程序；数据库保留最新状态，当前迁移仅增加字段。备份在 `/var/backups/vaio-panel/时间编号`，历史程序在 `/opt/vaio-panel-releases` 或 `/opt/vaio-panel-before-*`。

容器版：备份数据后 `git pull --ff-only`、`docker compose build`、`docker compose up -d`。数据库使用 `PRAGMA user_version` 管理兼容迁移；未来破坏性迁移须遵循对应发行说明。

Agent：以 root 执行 `vaio-agent update`，旧版本从「节点设置」复制升级命令。安装包通过现有 HTTPS 面板下载并校验；升级前开启维护模式，拒绝未完成或未核对任务，保留身份、代理配置与任务记录。新程序上线失败尝试恢复 `/opt/vaio-agent-backup-*` 中的旧程序。维护状态解除失败时，核对服务与任务后执行 `vaio-agent resume`。面板无法访问时不会强行更新。

“待核对”任务需要先检查节点实际结果，再在任务记录填写说明并标记已核对；这只解除任务状态限制，不重试或回放操作。

节点删除进入回收站，同时撤销身份并取消排队任务；运行中、维护中或待核对时禁止删除。删除不卸载服务器上的代理或 Agent。恢复节点保留任务历史，但必须重新注册并确认接管；旧凭据不会恢复有效。

只卸载 Agent 时先撤销节点身份，再停止并禁用 `vaio-agent` 服务，移除对应 unit 与 `/opt/vaio-agent`。保留 `/etc/vless-reality`，现有代理不随 Agent 卸载。确认不再需要恢复记录后再删除 `/etc/vaio-agent` 和 `/var/lib/vaio-agent`。

Agent 停止后，面板用户到期检查不再运行；原脚本的既有定时任务不受此操作影响。

## 快捷安装与账号恢复

直接安装版程序位于 `/opt/vaio-panel`，数据库位于 `/var/lib/vaio-panel/panel.sqlite`，配置位于 `/etc/vaio-panel/panel.env`。用 `vaio-panel status / restart / logs` 管理服务（选择其中一个子命令）。

后台右上角「账号设置」支持改账号、改密码，需验证当前密码。账号 3–32 位字母、数字、点、下划线或短横线，密码 12–128 位。新密码留空则保留原密码，保存后所有登录会话失效。旧数据库自动使用账号 `admin`，不会重置原密码。

忘记密码时，直接安装版以 root 执行 `vaio-panel account`；容器版执行 `docker compose run --rm panel python -m vaio init`。重置会同时更新账号、密码并退出所有会话。已连接的节点不受影响。

节点安装命令中的凭据通过请求头发送，不进入 URL 或常规访问日志；安装脚本下载到私有临时文件，执行后自动删除。命令本身包含一次性凭据，应避免分享，注册后失效。下载失败不会执行残缺脚本。下载不会消耗注册机会，真正注册时原子消耗；重新生成会立即撤销旧命令。
