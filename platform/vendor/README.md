# 上游来源与固定版本

`vless-server.sh` 是本提交根目录同名脚本的逐字节快照，保留原作者声明：

- 仓库：https://github.com/mozisen/surge
- 分支：`codex/platform-api`
- 提交：与当前根目录脚本同一 Git 提交；使用下列摘要固定内容。
- 版本：`3.7.3-preview.2`（兼容平台的统一配置渲染预览版）
- SHA-256：`4c83a5cda311efd5969906467088b49e0daeea5d97ffd8cc0b57c7369788e1f8`

原快照未提供许可证，不对该文件另行声明许可证。

上一固定版本为 3.7.3-preview.1，提交 `a0dcff02383fd8cda48d9e54ebe95027367e91cd`，SHA-256 为 `fc38833fc12d9f1bff8adfa4f12ac1f3aca41aee5978059af68fb27222044c32`。本次加入共享渲染器及 CLI 对已接管实例的适配。

Agent 只加载 CLI 分派前的定义，调用白名单内的二进制安装器与 Snell 计数器辅助函数；配置渲染只提取固定的 `_platform_render_inbound` 函数，通过标准输入传递私有数据，不执行菜单。事务仍由按实例定位的 Python Bridge 管理，不动态下载最新脚本。

新增接口检查调用完整 CLI 的 capabilities/inventory，缓存 60 秒，只上报版本、接口状态和数量。不转发原始响应，不使用其包含流量的 revision 派发写任务。新接口的 write_actions 为空；现有五种写入组合继续使用原有 Python 适配器，其他协议不因此开放。未知能力契约按不可用处理。
