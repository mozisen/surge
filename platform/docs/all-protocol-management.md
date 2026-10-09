# 全协议管理：适配范围与上游接口提案

状态：本地开发版本 0.3.0-dev.1，已扩展至 9 种协议/内核组合，尚未实现全协议写入。本轮未部署或更改线上版本。

## 已核对的范围

依据固定的 `vendor/vless-server.sh` 3.7.2，`XRAY_PROTOCOLS`、`SINGBOX_PROTOCOLS`、`STANDALONE_PROTOCOLS` 共定义 26 个协议/运行方式组合，去重后为 22 个协议标识。

| 运行方式 | 协议 | 当前面板 |
|---|---|---|
| Xray | vless | Reality 模式已支持 |
| Xray | vless-xhttp、vless-xhttp-cdn、vless-ws、vless-ws-notls、vmess-ws、vless-vision | 只读 |
| Xray | trojan | 已实现，待真实节点验收 |
| Xray | trojan-ws、socks、ss2022、ss-legacy | 只读 |
| Sing-box | vless、trojan、anytls | 已实现，VLESS 限 Reality；待真实节点验收 |
| Sing-box | ss2022、ss-legacy、tuic | 只读 |
| Sing-box | hy2 | 不含端口跳跃的实例已支持 |
| 独立服务 | snell、snell-v5、snell-v6 | 已支持；旧多端口格式必须先迁移 |
| 独立服务 | snell-shadowtls、snell-v5-shadowtls、ss2022-shadowtls、naive | 只读 |

“已支持”不等于每种环境均已通过真实连通性验收；现有记录见 `validation.md`。

## 0.3.0-dev.1 本地增量

- 新增 AnyTLS/Sing-box、Trojan/Xray、Trojan/Sing-box、VLESS Reality/Sing-box：安装、端口修改、单实例卸载、用户增删/启停/到期、凭据重置及连接导出。
- 新安装实例保存稳定 UUID，并使用独立证书目录；同协议多端口默认用户名不重复，避免统计键冲突。
- 平台安装表单按节点 `write_capabilities` 显示协议/内核组合。`task_api_version=2` 才允许凭据重置；旧节点拒绝新协议，不通过前端绕过校验。
- 共享核心先校验私有暂存配置，再替换正式文件；保留无关入站、路由、出站和原有统计用户。添加用户补充已有 Sing-box 统计白名单，不自动安装统计核心。
- 回滚备份增加 `recovery.json`，记录服务原启停/自启状态及备份文件映射。恢复失败为 unknown，禁止自动重放；平台有未核对 unknown 任务时拒绝新写入。
- UI 按 ui-ux-pro-max 的表单错误提示与破坏性操作说明规则调整，保留既有中文黑白界面。

验证：59 项 Python 隔离回归（包括全部 9 种已声明组合的双实例增删改及凭据重置）、12 套根脚本回归、Node/Shell 语法、diff 空白检查。未执行真实核心握手、真实 systemd/OpenRC/nft、Docker、Python 3.12 及线上升级。

重要边界：`vless-server.sh --api` 仍是只读接口，写入通过本仓库 Agent 的 Bridge 实现。本轮不发布正式版或预览版，不更换固定 vendor 快照。原脚本的全量配置重建与面板独立证书/用户策略的双向同步仍需接入统一生成器并回归，因此不能将这次 Agent 适配直接作为全协议生产升级。WS/XHTTP/CDN、SS、TUIC、SOCKS、ShadowTLS、NaïveProxy、HY2 跳跃端口和关联资源跨服务事务仍未开放。协议参数编辑目前仅端口，SNI/证书/传输参数编辑及配额写入仍待实现。失败回滚恢复数据库、配置及服务，不卸载下载的二进制、系统包或新证书。

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
