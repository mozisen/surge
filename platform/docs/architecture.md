# v0.1.0 架构与接口

## 组件

面板：Flask + Gunicorn + SQLite；前端为原生 HTML/CSS/JavaScript，没有运行时 CDN。Agent 仅依赖 Python 标准库，Linux 上用 flock 协调数据库访问。

```
浏览器 → HTTPS / Caddy → 面板 → SQLite
                           ↑
                  Agent 每 10 秒主动轮询
                           ↓
              本地任务记录 → Bridge → Runtime
                           ↓
         原脚本 db.json / 实例配置 / systemd 或 OpenRC
```

Agent 与面板分离；代理数据不经过主面板。主面板停机不会停止已有代理服务。

## 身份与数据

- 注册凭据随机生成，30 分钟过期；数据库只保存哈希，并在事务内一次性消费。
- 每个节点获得独立随机身份凭据。面板存哈希，节点保存在 0600 的配置文件中。
- 管理员会话随机生成、服务端保存，12 小时有效；HttpOnly/SameSite=Strict，HTTPS 下启用 Secure。
- 所有浏览器写入校验 CSRF。任务严格校验 action/core/protocol/port/params；没有远程 Shell 接口。
- 节点快照仅包含白名单字段。连接导出是显式任务，包含敏感信息的结果 10 分钟后清除；SQLite 和备份必须视为敏感数据。

## 状态与并发

节点状态：待连接、在线（45 秒内心跳）、离线、已撤销。离线页面展示最后快照。

任务状态：queued → running → succeeded / failed / unknown。仅 queued 可取消。35 分钟未回报的 running 标记 unknown，不自动重试。

同一节点最多一个排队/执行任务。SQLite 的 `BEGIN IMMEDIATE` 保证一次领取；Agent 在执行前落盘 journal。Agent 重启后将尚在 running 的任务标为 unknown。结果回传失败会重试提交结果，不重做业务动作。

每个写入任务携带配置 revision。节点执行时重新计算并比较，过期任务拒绝。revision 排除使用量等动态统计字段。数据库写入兼容原脚本的 `.db.lock` flock，安装器确保存在 util-linux/flock。

## 配置策略

节点是实际状态的来源；面板发送明确动作，不定时覆盖整份配置。原脚本 binary installer 被固定版本调用；不操作交互式菜单、不拉取 main 上的最新脚本。

Bridge 用 core + protocol + port 唯一定位数据库实例。Runtime 按相同监听端口定位现有 inbound，保留该 inbound 的其他设置和整个核心的其他 inbound/outbound/routing。VLESS 写入要求 Xray Reality；Hysteria2 写入要求无端口跳跃。

修改前本地备份数据库、目标配置与 unit；写入后对 Xray/Sing-box 执行核心校验，再重启并验证状态。失败恢复原数据库和配置，恢复失败会明确返回需人工处理。Snell 无同等统一配置校验入口，以服务启动和存活检查验证。

Snell 用户对应独立端口；旧版无 ID 的多端口记录拒绝写入。默认用户记录保留以兼容原脚本；可以禁用，不能直接删除。

用户流量读取已有同步结果。首版不改造原脚本统计任务，也不统一网卡字节与用户流量口径。

Hysteria2 配置字段参考 [Sing-box 官方文档](https://sing-box.sagernet.org/configuration/inbound/hysteria2/)。当没有有效用户时，适配层使用一个新生成且不向用户导出的随机凭据，以兼容要求非空认证列表的核心版本，绝不恢复已禁用的默认用户。

## HTTP 路由

| 路由 | 用途 |
|---|---|
| POST /api/login；GET /api/session；POST /api/logout | 管理员会话 |
| GET/POST /api/nodes | 列出/新增节点 |
| GET /api/nodes/{id} | 节点快照 |
| POST /api/nodes/{id}/enrollment | 重置身份并生成安装脚本 |
| POST /api/nodes/{id}/adopt | 对已识别配置确认接管 |
| POST /api/nodes/{id}/revoke | 撤销节点身份 |
| POST /api/nodes/{id}/tasks | 下发任务；要求 Idempotency-Key |
| GET /api/tasks；POST /api/tasks/{id}/cancel | 任务列表/取消排队 |
| GET /api/audit | 操作审计 |
| POST /api/enroll | Agent 一次性注册 |
| POST /api/agent/{id}/poll | Bearer 身份认证、心跳、领取任务 |
| POST /api/agent/{id}/tasks/{task}/result | 提交本节点任务结果 |
| GET /downloads/agent.tar.gz / agent.sha256 | 无凭据的 Agent 程序包 |

写入任务示例（params 不允许任意 shell 参数）：

```json
{"action":"update","protocol":"vless","core":"xray","port":24443,"params":{"port":24444},"revision":"节点上报的64位配置哈希"}
```
