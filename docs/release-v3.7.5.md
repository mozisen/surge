# v3.7.5

基于 v3.7.3，跳过 3.7.4。不包含仍在独立分支开发的 Vaio Panel、节点 Agent 改动。

## 修复与改进

- mihomo 连接 Xray ≥ 26.9.9 的 VLESS REALITY 节点超时：Clash/mihomo 订阅的 `reality-opts` 增加 `support-x25519mlkem768: true`，保留 `client-fingerprint: chrome`；分享链接增加参数 `support-x25519mlkem768=true`（mihomo v1.19.31 起支持）。
- 服务器公网 IP 变化后，节点信息和配置仍是旧 IP：新增每 30 分钟的检测任务（`vless-server.sh --check-ip`）。IPv4、IPv6 分别判断，两个探测站一致或连续两次相同才确认；确认后更新数据库、`.join` 文件和订阅，并在菜单提示一次。出口 IP 与入口 IP 不同的机器可用 `--check-ip off` 关闭。
- VLESS REALITY 从 Xray 切到 sing-box 后连不上：真实证书模式下，sing-box 握手目标改为本机 Nginx `127.0.0.1:8443`，与 Xray 一致。
- 看门狗反复重启已无配置的 `vless-reality`：只在确有 Xray 或 sing-box 核心协议时守护对应服务；旧看门狗脚本在打开菜单时自动重写。
- 统计版 sing-box 核心在没有 sing-box 协议时无法更新（报 `singbox.json: no such file or directory`）：此时只替换核心并备份旧核心，不启动服务，统计能力保留；有协议却缺少配置时拒绝替换。
- 流量同步在 Bash 5 严格模式下提前退出（`((updated++))` 改为普通赋值）。
- 统计核心预编译包新增 sing-box 1.14.4（`singbox-stats-binaries` 分支，四个平台）。

## 已知问题

- sing-box 客户端连接 Xray ≥ 26.9.9 的 REALITY 节点仍失败，需上游修复（SagerNet/sing-box#4520）。
- mihomo v1.19.30 及更早版本不认分享链接中的 ML-KEM 参数，请使用订阅。
- 没有配置订阅域名时，IP 变化后客户端保存的旧订阅链接会失效，需要换成菜单提示的新链接。
- 安装时写入的 `.join` 文件不会因分享链接格式变化自动重写，重新安装该协议后才更新。

## 升级与验证

现有用户可在“检查脚本更新”中升级，或从主分支下载运行脚本。保留现有协议配置与用户数据，建议升级前备份。

GitHub Actions 在 Bash 5.2 上运行语法检查和全部 20 项脚本测试，均通过；其中统计实测使用 1.14.4 预编译统计核心。

真实 VPS 验收情况：维多利亚节点运行 preview.2 正常。以下内容尚未在真实节点验证：订阅导入 mihomo 后的连接、IP 变化检测的实际触发、sing-box 切换后的连接、看门狗停止空转、统计核心在无 sing-box 协议时的更新。
