# v3.7.0-preview.3 本地预览记录

- 实时流量按已安装协议的用户列表显示，不再隐藏零流量用户。
- Xray/Sing-box API 失败、核心停止、Snell 计数器缺失时显示“统计不可用”，不冒充零流量。
- 补齐 Sing-box VLESS、Trojan 用户显示，与 HY2、TUIC、AnyTLS 使用同一统计键规则。
- Sing-box 未接入命名用户计数的协议仍显示用户，并标注不可用。不改变核心配置、历史用量、自动同步或配额逻辑。
- Snell 不再与 Xray 用户统计重复列出；解释 API 重置计数与防火墙累计计数的区别。
- `--show-traffic` 每行新增第六列状态；不可用时数值列为空。

验证：Bash 语法检查、Git diff 检查，以及 tests 下三套回归测试通过。新增测试覆盖混合核心、零流量、VLESS/Trojan、API 失败、核心停止、Snell 缺失计数器、重置后空响应。未在真实 Linux 服务器进行连通性或服务集成验证。

仅推送预览分支，不创建或更新 GitHub Release。
