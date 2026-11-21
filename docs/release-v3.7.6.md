# v3.7.6

基于 v3.7.5。

## 修复与改进

- 修复增删 VLESS-Reality 或 VLESS-XHTTP 用户后，原有 VLESS+Reality+XHTTP（以及 VLESS-WS 等其他 VLESS 入站）连接失败：用户变更后 Xray 配置改为完整重建，不再把当前协议的用户和 vision flow 覆盖到所有 VLESS 入站。修改配额、到期等操作同样受益。已出问题的节点，升级后任意增删一次用户即可恢复。
- 修复 GitHub API 限流或不可达时，安装 Xray 等核心误报“下载包无法通过发布方 SHA-256 校验”：API 取不到校验值时改用发布页随附的 `.dgst` / `.sha256` 文件校验；“取不到校验值”与“校验值不一致”分开提示。
- Surge 支持 VLESS：
  - VLESS-Reality、VLESS-XHTTP、VLESS-XHTTP-CDN 节点信息中显示 Surge 配置（Reality 放在 Loon 配置之前），需 Surge iOS 6.0.0+ / Mac 6.12.0+。
  - 生成的 Surge 订阅加入以上三种 VLESS 节点。VLESS+Encryption 模式不写入 Surge 订阅。
  - XHTTP 提示改为“Loon 暂不支持 XHTTP，请使用 Surge 或分享链接导入 Shadowrocket”。

## 已知问题

- NekoBox、Karing、sing-box 官方客户端等基于 sing-box 内核的客户端，无法连接 Xray ≥ 26.9.9 的 REALITY 节点，需等上游修复（SagerNet/sing-box#4520）。有这类用户的节点，VLESS REALITY 可改用 sing-box 内核。
- Loon 仍不支持 XHTTP。

## 升级与验证

现有用户可在“检查脚本更新”中升级，或从主分支下载运行脚本。保留现有协议配置与用户数据，建议升级前备份。

GitHub Actions 在 Bash 5.2 上运行语法检查和全部 23 项脚本测试，均通过；新增测试在 v3.7.5 上均失败，能复现对应问题。

以下内容尚未在真实节点或客户端验证：用户增删后 XHTTP 连接恢复、API 限流时的 `.dgst` 校验、Surge 实际连接三种 VLESS 节点及导入新订阅。
