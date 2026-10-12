# 各协议的用户支持现状（2026-10-12，HEAD 5fa695d：脚本 3.7.4-preview.5，面板 0.3.0-preview.12）

## 脚本协议（`XRAY_PROTOCOLS` / `SINGBOX_PROTOCOLS` / `STANDALONE_PROTOCOLS`）

| 核心 | 协议 | 多用户 | 每用户流量统计 | 现状备注 |
|---|---|---|---|---|
| Xray | vless（Reality/Vision）、vless-vision、vless-ws、vless-ws-notls、vless-xhttp、vless-xhttp-cdn | 是（`gen_xray_vless_clients`） | 是（email） | 统一用户已支持；面板只能装 Reality |
| Xray | vmess-ws | 是（`gen_xray_vmess_clients`） | 是 | 统一用户已支持；面板只读 |
| Xray | trojan、trojan-ws | 是（`gen_xray_trojan_clients`） | 是 | trojan 面板可装；trojan-ws 只读 |
| Xray | ss-legacy | 是（`_ss_legacy_xray_settings`） | 是 | 面板只读 |
| Xray | ss2022 | **否**：单个 `password` | 否 | Xray 原生支持 SS2022 多用户（服务端密钥 + 每用户密钥 + email），可改 |
| Xray | socks | **否**：单个 `accounts` | **否**：socks 账号没有 email，Xray 无法按用户统计 | 可改为多账号，但只能按入站统计 |
| Sing-box | vless、trojan、hy2、tuic、anytls | 是（`_singbox_effective_users`） | 是（v2ray_api users） | tuic 面板只读 |
| Sing-box | ss-legacy | 是（`_ss_legacy_singbox_inbound`） | 是 | 面板管理的 SS 实例在 Agent 渲染器里只取第一个用户 |
| Sing-box | ss2022 | **否**：单个 `password` | 单用户时按入站计数 | Sing-box 原生支持 SS2022 多用户（服务端密钥 + users），可改 |
| 独立 | snell、snell-v5、snell-v6 | 否（单 PSK） | 是（nft 按端口计数） | 已是一用户一实例（`snell_users` 布局） |
| 独立 | snell-shadowtls、snell-v5-shadowtls | 否（Snell 单 PSK，ShadowTLS v3 单密码） | 否 | 前端 shadow-tls + 后端 snell 两个服务；只能一用户一实例，需要新增启停门控与计数 |
| 独立 | ss2022-shadowtls | 后端 Xray SS2022 可多用户，但 ShadowTLS 前端只有一个共享密码 | 否 | 若按多用户处理，所有用户共享 ShadowTLS 密码；否则一用户一实例 |
| 独立 | naive（Caddy forward_proxy） | 可：`basic_auth` 可写多行 | **否**：Caddy 没有按用户的流量统计 | 改多用户后到期、启停可以执行，配额无法执行 |

## 面板现状
- 面板安装与实例写入只支持 9 种协议/内核组合（`vaio/common.py:PROTOCOL_CORES`），由 Agent 的 Python 适配器实现。其他协议在面板上是「仅查看」，`share`、端口等任务会因 `managed=false` 失败（vps.town 上 3 个失败的「配置信息」任务就是这个原因）。
- 平台用户管理通过脚本 `account_apply` 写入，脚本侧的重建覆盖所有多用户协议。但面板界面只把 `managed` 实例列为可选成员；连接信息走 Agent 的 `share`，只支持 9 种组合。
- 安装表单只能填一个用户名，不能选择平台用户。

## 要做到「一个用户关联多个协议、一个协议关联多个用户」
1. 能力表：每个实例上报用户模式 `multi` / `single`（一用户一实例）/ `none`，以及是否有每用户流量统计。脚本、Agent、面板共用。
2. 脚本改造：SS2022（Xray、Sing-box）改成多用户；SOCKS、Naive 改成多用户（流量按入站统计或不统计）；ShadowTLS 组合、Snell 按一用户一实例，加启停门控；Agent 渲染器的 SS 支持多用户。
3. 连接信息：非 Agent 适配器协议的成员连接信息需要脚本接口生成（新增 `account_share`，结果只在任务里短暂保存，与现有 share 一致）。
4. 面板：成员可选所有多用户实例；一用户一实例的协议以「为该用户安装实例」的方式关联；安装时可以选平台用户；不支持用户管理的协议在安装时提示。
