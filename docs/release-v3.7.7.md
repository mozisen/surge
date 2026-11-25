# v3.7.7

基于 v3.7.6。

## 新增

- 新装协议第 16 项：Mieru。
  - 服务端使用官方 mita，仅支持 x86_64 / aarch64，以 `mita` 用户运行（服务名 `vless-mieru`），只开 TCP，端口需在 1025-65535。
  - 节点信息提供 Clash Meta（mihomo）配置和 `mierus://` 分享链接，Clash 订阅也会加入 Mieru 节点。
  - Surge、Loon、sing-box、v2rayN 不支持 Mieru。
  - 与 Snell、NaïveProxy 一样不支持多用户、流量统计和配额。
- Hysteria2 可选 Salamander 混淆：安装时询问，默认不启用。
  - 启用后，分享链接、Surge（`salamander-password`，需 Surge Mac 6.4.3+）、Loon、Clash Meta 配置及各订阅都会带上混淆密码。
  - 启用后网页伪装失效。
  - 已有节点不受影响；要启用，需重装 Hysteria2 或新增端口实例。

## 修复

- Hysteria2 可使用 VLESS、Trojan 等 TCP 协议已占用的端口号。端口冲突改为按 TCP/UDP 分别判断。Hysteria2 与 TUIC、Shadowsocks、SOCKS5 同端口仍会提示冲突。

## 升级与验证

现有用户可在“检查脚本更新”中升级，或从主分支下载运行脚本。保留现有协议配置与用户数据，建议升级前备份。

GitHub Actions 在 Bash 5.2 上运行语法检查和全部 27 项脚本测试，均通过。其中：

- Mieru 测试使用真实 mita / mieru v3.40.0，经 systemd 启动后，客户端通过代理访问成功。
- Hysteria2 混淆配置已通过 sing-box 1.14.4 校验。

以下内容尚未在真实节点或客户端验证：

- Mieru 在真实 VPS 及 Alpine/OpenRC 上的安装运行，以及 mihomo 客户端连接。
- Hysteria2 与 VLESS 同端口号同时运行。
- 各客户端连接启用混淆的 Hysteria2 节点。
