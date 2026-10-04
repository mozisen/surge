# 普通 Shadowsocks 用户修复

基于 `codex/quota-enforcement-preview` 的 `28ccfe5`，发布预览版本 `3.7.3-preview.quota.4`，分支 `codex/ss-user-fix`，不创建 Release。

## 修复

- 普通 SS 安装时显示“SS密码”，不再显示“SS2022密码”。
- Xray 使用当前端口实例的 `settings.clients`，每个有效用户具有独立密码和统计 email。
- Sing-box 使用当前端口实例的 `users`，每个有效用户具有独立密码；`ss-legacy-用户名` 纳入统计配置、同步和实时显示。
- 旧单用户数据首次添加用户时保留默认密码。显式禁用、超额、过期及空用户列表不回退到原始密码。
- 修改 SS 用户不再进入 VLESS 局部更新路径；SS2022 配置不变。
- 不改动现有端口、不切换核心、不自动部署服务器。

## 验证范围

`tests/ss-legacy-users.sh` 检查三种 AEAD 加密、实际 Xray 入站及 Sing-box 入站生成、双方分享链接密码一致、多端口隔离、有效用户筛选、旧数据迁移和 SS2022 不变。

已核对官方实现：
- Xray v26.3.27 `infra/conf/shadowsocks.go`：普通 AEAD 使用 `clients`，每个用户配置 method/password/email。
- Sing-box v1.13.0、v1.14.0 `protocol/shadowsocks/inbound_multi.go`：普通 AEAD 使用独立用户密码，不是仅 SS2022 支持多用户。

本地模拟回归不等于 VPS 连通性验证。`tests/singbox-stats-live.sh` 需要提供带统计功能的真实核心，本次环境未提供，因此不声称该测试通过。服务器仍需更新脚本、重建对应核心配置后实际连接验证。
