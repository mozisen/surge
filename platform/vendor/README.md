# 上游来源与固定版本

`vless-server.sh` 是原项目的未修改快照，保留原作者声明：

- 仓库：https://github.com/mozisen/surge
- 分支：`codex/platform-api`
- 提交：`a0dcff02383fd8cda48d9e54ebe95027367e91cd`
- 版本：`3.7.3-preview.1`（只读管理接口预览版）
- SHA-256：`fc38833fc12d9f1bff8adfa4f12ac1f3aca41aee5978059af68fb27222044c32`

原快照未提供许可证，不对该文件另行声明许可证。

上一固定版本为 3.7.2，提交 `8dfe4d0da1383ecde6bcd2c43227c5d407ecd7c5`，SHA-256 为 `efdb8e151a05e7ed1b0ce9ed0e48cff39d2c77b574d7f079435eb708fe983b03`。本次差异仅为版本号及只读 API，原安装器及配置函数不变。

Agent 只加载 CLI 分派前的定义，调用白名单内的二进制安装器与 Snell 计数器辅助函数。现有配置事务仍使用按实例定位的 Python 适配器，不驱动交互菜单、不动态下载最新脚本。

新增接口检查调用完整 CLI 的 capabilities/inventory，缓存 60 秒，只上报版本、接口状态和数量。不转发原始响应，不使用其包含流量的 revision 派发写任务。新接口的 write_actions 为空；现有五种写入组合继续使用原有 Python 适配器，其他协议不因此开放。未知能力契约按不可用处理。
