# 全协议管理：适配范围与上游接口提案

状态：接口设计与兼容性审查，尚未实现全协议写入。当前线上版本仍为 0.2.1。

## 已核对的范围

依据固定的 `vendor/vless-server.sh` 3.7.2，`XRAY_PROTOCOLS`、`SINGBOX_PROTOCOLS`、`STANDALONE_PROTOCOLS` 共定义 26 个协议/运行方式组合，去重后为 22 个协议标识。

| 运行方式 | 协议 | 当前面板 |
|---|---|---|
| Xray | vless | Reality 模式已支持 |
| Xray | vless-xhttp、vless-xhttp-cdn、vless-ws、vless-ws-notls、vmess-ws、vless-vision | 只读 |
| Xray | trojan、trojan-ws、socks、ss2022、ss-legacy | 只读 |
| Sing-box | vless、trojan、ss2022、ss-legacy、tuic、anytls | 只读 |
| Sing-box | hy2 | 不含端口跳跃的实例已支持 |
| 独立服务 | snell、snell-v5、snell-v6 | 已支持；旧多端口格式必须先迁移 |
| 独立服务 | snell-shadowtls、snell-v5-shadowtls、ss2022-shadowtls、naive | 只读 |

“已支持”不等于每种环境均已通过真实连通性验收；现有记录见 `validation.md`。

## 为什么建议先改原脚本

当前 CLI 没有全协议安装、修改、卸载和用户管理的结构化入口。面板 Agent 目前只复用固定白名单中的二进制安装器及 Snell 计数器辅助函数，配置事务由 Python 独立实现。

源码中的 `generate_xray_config` 和 `generate_singbox_config` 会重建整个核心配置，并涉及路由、统计及临时数据库记录。`_add_single_xray_inbound` 还是直接返回成功的占位函数，不能当作单实例生成接口使用。ShadowTLS 组合实例涉及前后端配置，NaïveProxy 涉及 Caddy，端口跳跃涉及 NAT；它们需要完整的资源归属及恢复计划。

技术上可以继续在 Agent 中独立实现全部适配器，不存在“所有新增协议必须升级脚本”的硬限制。但这会维护两套协议生成、迁移与恢复逻辑。为长期保持与原脚本一致，推荐先在原项目提供受限、版本化的接口，再由面板接入。该提案不是现有脚本已具备的功能。

## 拟新增的非交互接口

建议入口：`vless-server.sh --api`，通过标准输入读取单个 JSON 请求；标准输出只输出 JSON，日志写标准错误。不得执行请求中的 Shell 文本、任意命令、任意文件路径或未列入白名单的服务。

请求包含 `api_version`、`request_id`、`action`、`expected_revision`、`target`、`params`。目标优先使用稳定实例 ID；兼容旧记录时使用内核、协议和端口精确定位，并拒绝歧义。端口修改不得改变实例身份。

| 操作 | 约定 |
|---|---|
| capabilities | 返回支持的内核/协议/操作、参数结构、脚本版本及 API 版本 |
| inventory | 返回脱敏实例与用户、稳定 ID、配置版本及外部资源归属 |
| plan | 校验参数、端口和证书条件，返回将修改的文件、服务、NAT/CDN 资源与影响范围；不得下载或修改系统 |
| install / update / delete | 仅操作目标实例，包含所有关联资源的事务与恢复 |
| start / stop / restart | 返回共享服务影响范围，禁止按用户传入的任意服务名执行 |
| user_add / user_update / user_delete | 按实例定位，保留其他用户、统计和 Telegram 绑定；不支持多用户的协议明确报告能力限制 |
| share | 按目标用户生成必要连接信息，不把私钥或其他用户凭据混入返回值 |
| migrate | 显式迁移旧实例格式，预览计划、备份、验证，禁止隐式全量迁移 |
| result | 只查询已有 request_id 的结果，未知结果不得自动重做 |

更新字段必须按协议声明：监听端口、SNI、传输路径/Host、证书选择、加密方式、QUIC 参数、ShadowTLS 后端、NaïveProxy 域名以及 HY2 跳跃端口范围。敏感字段使用“保留/重置”语义，不通过 inventory 回填原值。配额写入需同时确认实际可用的统计与执行能力。

## 必须满足的事务约束

1. 获取兼容原脚本的数据库锁，检查 expected_revision，重新定位实例；校验失败不产生副作用。
2. 先生成变更计划，备份目标数据库记录、运行配置、关联服务、证书引用与相关 NAT 规则；证书和二进制按共享资源处理。
3. 保存执行意图与 request_id，再开始写入；同一请求重复提交不得再次执行。
4. 在暂存文件中生成配置并调用对应核心验证，保留非目标 inbound、路由和出站配置。
5. 应用后检查对应服务和资源状态，返回明确的 succeeded / failed / unknown、步骤及备份位置。
6. 失败恢复配置及原服务状态；恢复不完整必须明确报告。进程中断后返回 unknown，禁止自动重放。
7. 拒绝删除仍被其他实例引用的后端、证书、Nginx/Caddy 配置或防火墙规则。

## 面板接入顺序

1. 固定上游接口版本、提交与 SHA-256，更新来源说明；不直接执行远程最新脚本。
2. 面板与 Agent 共用协议能力表，同时校验参数；旧 Agent 未声明能力时不开放新操作。
3. 安装界面按协议/内核显示必要字段；实例编辑支持对应参数，用户操作以实际能力控制。
4. 展示变更影响、恢复结果和明确的不可管理原因；保持中文黑白风格。
5. 按协议运行隔离回归，再在授权测试节点逐个验证，最后更新主面板及 Agent。

## 验收要求

- 对每个支持组合安装两个实例；修改、删除一个后，另一个的配置、凭据、计数、路由和服务归属不变。
- 用户新增、禁用、启用、到期、删除及凭据重置；最后一个用户禁用后不能恢复默认凭据。
- 端口冲突、过期配置版本、无效字段、跨实例引用及非法文件路径均拒绝，面板和 Agent 结果一致。
- 注入配置验证失败、第二关联服务启动失败、NAT 应用失败和回滚失败；验证部分成功不会冒充完整成功。
- 任务中断后人工核对，重复 request_id 不重放。
- Reality、TLS、WebSocket、XHTTP、QUIC、ShadowTLS 和 NaïveProxy 分别使用实际客户端验证，明确区分模拟结果与真实结果。
- CDN/证书签发使用专门的测试域名；验证失败不更改现有公网网站配置。

现有 vps.town 面板和 ovh-vps-1 原有实例不因本次接口审查而变更。
