# Sing-box 1.14.2 统计包发布记录

- 发布日期：2026-10-05。
- 构建运行：https://github.com/mozisen/surge/actions/runs/37215372298
- 构建脚本提交：`24d6e74205976038b385da1eccb4e75af4dcc636`。
- 产物分支：`singbox-stats-binaries`，发布提交 `f2dcfb7ee53403137c75a3d38dcbbef3024feb9a`。
- 四种平台：linux-amd64-glibc、linux-amd64-musl、linux-arm64-glibc、linux-arm64-musl。

四个构建任务与发布任务全部成功，构建流程执行了真实核心统计接口测试。发布后分别通过 raw 下载地址读取清单和压缩包，核对版本/架构/libc/统计功能标签，压缩包与内含二进制 SHA-256 均匹配清单。

本地 `tests/prebuilt-stats.sh`、`tests/singbox-stats-update.sh` 通过。没有在用户 VPS 上安装、替换核心或执行连接测试。

现有 v3.7.3 的统计保留更新路径已按目标版本与平台下载对应包；选择 1.14.2 即可获取本次产物，无需修改主脚本或创建新的 Release。此记录只代表 1.14.2 已发布，不代表后续版本会自动构建。下载失败后的停止状态处理不在本次包发布中修改。
