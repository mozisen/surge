# 现状调研（2026-10-12，HEAD 5cdefbd：脚本 3.7.4-preview.4，面板/Agent 0.3.0-preview.11）

## 用户管理现在有三套入口
1. 脚本菜单：协议用户（按协议）和统一用户（`accounts`），由脚本 cron 执行到期和配额。
2. 面板实例弹窗：直接改协议用户（`user_add/user_update/user_delete`，单实例任务，配额走 Agent 的 `panel_quota` 计费）。「香港维多利亚」目前就是用这种方式由面板管理用户的。
3. 面板「用户管理」：平台用户 ↔ 节点统一用户，三方合并（base/节点/面板，按 mtime 后改的为准）、跨节点 block、认领、成员操作。

复杂度主要来自：两边都能写同一个用户，因此需要 rev/mtime、三方合并、冲突提示、版本冲突重试；实例弹窗和用户管理页又是两条写路径。

## 可直接复用的部分
- 脚本 `accounts_apply`：结算、派生成员字段、只重建状态有变化的协议、重建失败重试。
- 脚本 `--api account_apply`：事务、幂等、回滚、结果查询。
- Agent `platform_apply`：任务意图记录、不重放、`.txn.lock`。
- 面板：平台用户、关联、跨节点用量累计与 block、调度、任务结果回写、界面。

如果改成「每台节点二选一」，在平台模式下面板就是唯一写入方，三方合并可以整体删除，改成「面板期望状态 → 覆盖节点」；脚本模式下面板对用户只读。

## 节点升级现状
- 面板「升级节点」只给出一条命令，需要在节点上以 root 执行 `update-agent.py`。
- `update-agent.py`：下载 `/downloads/agent.tar.gz`，校验 sha256，解包到暂存目录并自检，进入维护模式（要求面板上该节点没有 queued/running/unknown 任务），检查本机任务日志，停止服务，替换 `/opt/vaio-agent`，启动服务，等待新版本上线（90 秒），失败则恢复旧目录，最后解除维护。
- Agent 的 `ensure_main_script` 只在节点没有主脚本时安装，从不覆盖已有的 `/usr/local/bin/vless-server.sh`；节点主脚本的版本因此可能落后于 Agent 自带的副本（节点 cron 用的是主脚本）。

## 一键升级的技术约束
- 升级器会停止 vaio-agent 服务；如果作为 Agent 的子进程运行，systemd 停止服务时会连同它一起杀掉。必须放到独立的单元或会话中运行（systemd：`systemd-run --unit vaio-agent-upgrade --collect`；OpenRC：`setsid`，脱离 supervise-daemon 的进程）。
- 维护模式要求节点没有执行中的任务，而触发升级的任务本身就是一个任务：需要先上报该任务结果，再由独立进程进入维护和升级。
- 升级结果需要回到面板：新版 Agent 在快照里上报上一次升级的结果（版本、成功/失败/已回滚、时间）。
- 主脚本升级：用 Agent 自带并经过 SHA 校验的副本替换 `/usr/local/bin/vless-server.sh`，先备份，原子替换；cron 不需要改。

## 生产约束
- 「香港维多利亚」：唯一在线节点，有真实用户流量，Agent 0.3.0-preview.8，节点脚本未升级。没有授权不能操作。
- 旧版 Agent 不认识新的升级任务：第一次仍需按现有方式升级（SSH 执行命令），之后才能在面板上一键升级。
