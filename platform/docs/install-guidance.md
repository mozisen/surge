# 安装引导参数核对（2026-09-21）

对照根脚本 install_protocol、ask_sni_config、gen_sni 及平台安装任务契约。
仅显示节点能力和平台实际适配组合的交集，不为未实现的参数提供无效输入框。

| 脚本协议 | 需要用户提供 / 选择的参数 | SNI 规则 | 平台当前状态 |
| --- | --- | --- | --- |
| vless | 端口、Reality 目标域名；密钥自动生成 | Reality 需要真实 TLS 1.3 目标；脚本 encryption 模式另行处理 | Xray / Sing-box，限 Reality |
| vless-xhttp | 安全模式、路径、目标域名 | Reality 候选域名或 TLS/CDN 真实证书域名 | 未接入 |
| vless-xhttp-cdn | 域名、证书、路径、内部端口 | 必须对应真实域名，不可随机替代 | 未接入 |
| vless-ws | TLS、路径、域名、证书 | TLS 需要；回落须与主协议一致 | 未接入 |
| vless-ws-notls | 端口、路径、Host / Tunnel | 无服务端 TLS，不显示证书 SNI | 未接入 |
| vmess-ws | 端口、路径、域名、证书 | TLS / 回落域名 | 未接入 |
| vless-vision | 端口、域名、证书 | TLS 域名 | 未接入 |
| trojan | 端口、证书 SNI；密码自动生成 | 自签可从脚本列表生成 | Xray / Sing-box，原生 TCP、自签 |
| trojan-ws | 端口、路径、域名、证书 | TLS / 回落域名 | 未接入 |
| socks | 认证模式、用户名密码、监听地址、可选 TLS | 仅启用 TLS 时需要 | 未接入 |
| ss2022 | 端口、加密方法、密钥 | 无 | 未接入 |
| ss-legacy | 端口、加密方法、密码 | 无 | 未接入 |
| hy2 | 端口、证书 SNI、可选跳跃端口范围 | 自签可生成 | Sing-box，自签、不启用跳跃 |
| tuic | 端口、证书 SNI、可选跳跃范围；UUID / 密码自动生成 | 自签可生成 | 未接入 |
| anytls | 端口、证书模式、证书域名 | 自签可生成；ACME / 复用证书应绑定实际域名 | Sing-box，仅自签 |
| snell | 端口、用户名、PSK | 无；不要混同 ShadowTLS | 独立 v4 核心 |
| snell-v5 | 端口、用户名、PSK | 无 | 独立 v5 核心 |
| snell-v6 | 端口、用户名、PSK；脚本另有模式 / DNS / TFO | 无 | 独立 v6 核心，高级项沿用节点默认 |
| snell-shadowtls | 公网 / 内部端口、PSK、ShadowTLS 密码、握手域名 | 外层 ShadowTLS 需要 | 未接入 |
| snell-v5-shadowtls | 公网 / 内部端口、PSK、ShadowTLS 密码、握手域名 | 外层 ShadowTLS 需要 | 未接入 |
| ss2022-shadowtls | 公网 / 内部端口、方法密钥、ShadowTLS 密码、握手域名 | 外层 ShadowTLS 需要 | 未接入 |
| naive | 用户名密码、端口、真实域名 | Caddy ACME，必须使用可验证域名，不能随机生成 | 未接入 |

## 本次界面行为

- 9 个可写组合分别显示协议说明。Snell 隐藏并禁用 SNI，同时取消必填校验；提交只包含用户名。
- Reality 显示目标 SNI，TLS 协议显示证书 SNI。自动生成使用脚本 COMMON_SNI_LIST 的完整候选池，测试防止名单漂移；不声称候选域名已经通过连通性测试。
- 保留手动输入与原默认值；生成按钮不会提交任务。连续生成避免返回当前域名。
- 生成按钮与输入框相距 12px，灰底、强调边框、加粗文字、至少 44px 高；安装仍是唯一主操作。
- 未扩大 Agent 安装契约，未修改节点核心或已安装实例。本次不创建 Release，不部署生产服务器。

## 验证

前端测试覆盖全部 9 个组合的字段显示、必填状态、任务参数隔离、候选池一致性及生成不触发提交。
本地结果：平台 62 项测试通过；前端语法与安装表单测试通过；根目录 Shell 模拟回归套件全部通过；git diff --check 通过。
未运行 singbox-stats-live.sh：需要真实统计核心和运行环境。
实际浏览器视觉验收与 VPS 安装需单独测试，不能由模拟表单测试替代。
