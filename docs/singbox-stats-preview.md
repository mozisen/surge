# v3.7.0-preview.4 本地预览记录

## 修复内容

- 删除对没有安装来源的 `singbox-v2ray-client` 的依赖，改用官方 grpcurl 1.9.4，安装包使用 GitHub Release digest / 发布方 SHA-256 校验。
- 内置 Sing-box 的 V2Ray gRPC 定义，使用 `v2ray.core.app.stats.command.StatsService/QueryStats`，同时兼容 pattern / patterns 字段；正确传递 reset，查询使用 10 秒超时。
- Sing-box 自动同步、手动同步、配额处理覆盖 VLESS、Trojan、HY2、TUIC、AnyTLS，沿用 `协议-用户名` 统计键。修复之前仅遍历后三种协议及 reset 参数错误的问题。
- Sing-box 读取失败不再悄悄跳过后返回同步成功；其他已读取核心数据仍处理，整体返回失败状态。
- 进入实时统计或手动同步时检查依赖及统计配置中的用户名。必要时询问是否重建配置并重启。

## 现有服务器使用

更新脚本后，进入「用户管理 → 实时流量统计」或「同步流量数据」。

如果核心缺少 `with_v2ray_api`，会询问是否从官方源码构建**相同版本**的统计核心。此操作需要较多内存、磁盘空间和下载时间。支持 1.10–1.13 正式版本；其他版本拒绝自动构建，不会自行降级。

构建使用校验过的官方 Go 1.25.7 作为启动工具链、Go 模块校验服务以及明确的构建标签；源码要求更高 Go 版本时允许 Go 自动下载其所需工具链。现有服务在构建期间继续运行；新核心先检查现有配置是否兼容，再备份原核心及配置，替换并重启。API 验证失败会尝试恢复原核心与配置。备份路径为配置目录中的 `singbox-stats-backup.*`，成功后也保留。

确认重启后请让客户端重新连接，再产生一些流量测试。原先没有统计接口期间漏记的流量无法追回。以后如果更换成不带统计接口的官方核心，需要再次启用统计构建。仅更新脚本不会静默替换服务器核心。

## 验证记录

- Bash 语法检查、Git diff 检查及四套离线测试通过。
- 使用官方 Sing-box 1.13.0 macOS 包复现“v2ray api is not included in this build”。
- 本机从官方同版本源码构建统计核心后，真实 VLESS、AnyTLS、Trojan 回环传输产生对应用户的非零计数；gRPC reset 后计数归零。
- 模拟 API 回归验证 VLESS、Trojan、HY2、TUIC、AnyTLS 分别正确累加入库、同步后空计数不重复累加、失败不报成功、旧配置缺少统计用户名能被识别。
- HY2/TUIC 未做真实网络传输测试；Linux 构建替换、systemd/OpenRC 重启与自动恢复尚待服务器测试。本机 VLESS 测试验证协议计数，不包含 Reality 握手。

真实核心测试运行方式：设置 `SINGBOX_TEST_BIN`、`GRPCURL_TEST_BIN` 为已校验的二进制绝对路径，再执行 `bash tests/singbox-stats-live.sh`。测试仅监听本机回环地址。

上游依据：[Sing-box V2Ray API](https://sing-box.sagernet.org/configuration/experimental/v2ray-api/)、[Sing-box 1.13.0 统计实现](https://github.com/SagerNet/sing-box/blob/v1.13.0/experimental/v2rayapi/stats.go)。

本预览版仅记录并推送预览分支，不创建 GitHub Release。
