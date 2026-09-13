# v3.7.1-preview.2：预编译统计核心

开启/修复统计前查询官方 Releases 的最新 1.14.x 稳定版，不一致时提示先在核心管理指定版本更新，不自动升级/降级。已有健康统计接口不因浏览统计而强制更新。查询失败安全退出。

新包路径为 linux-amd64-glibc、linux-amd64-musl、linux-arm64-glibc、linux-arm64-musl，清单额外校验 libc。glibc 在 Ubuntu、musl 在原生架构 Alpine 容器构建并执行真实计数测试；仍使用 CGO_ENABLED=0，不表示依赖某个动态 libc。未知平台或缺包提示手动本地编译 with_v2ray_api，网络/校验失败不自动编译。已有旧包不覆盖。

本次十套离线回归测试、Bash 语法和 diff 检查通过；四平台 CI 测试状态以对应 Actions 运行结果为准，服务器服务替换/回滚仍需测试机验证。预览版不创建 Release。

服务器不再下载 Go、源码依赖或编译缓存。修复和保留统计的核心升级统一下载同版本、同架构的预编译包；缺包、网络失败、SHA-256 错误时保留原核心，不现场编译、不自动降级。

包源为本项目 `singbox-stats-binaries` 专用分支，每个版本含 linux-amd64、linux-arm64 的归档及 manifest。包由 GitHub Actions 从官方固定版本源码构建，CGO 禁用；在各自原生 Linux runner 上运行 VLESS、AnyTLS、Trojan 的真实回环计数/reset 测试，两种架构全部通过才发布。已有版本目录不被重复构建覆盖。

下载时校验版本/架构、归档和二进制 SHA-256，再检查核心版本、统计标签与现有配置。保留现有备份、服务重启、API 健康检查及失败恢复流程。仍需归档、解压核心和旧核心备份空间，但不再需要完整编译环境的磁盘空间。

## 构建新版本

GitHub Actions → Build precompiled Sing-box statistics cores → Run workflow，填写官方稳定版本（例如 1.14.0）。构建成功后服务器才可下载该版本。此流程不自动跟踪上游、不创建 Release；未来版本仍需实际编译和测试，不能预先保证支持。

工作流及 CI 构建脚本可独立部署到主分支，正式安装脚本仍保持 3.7.0；新下载逻辑在 `codex/singbox-prebuilt-stats` 预览分支测试。

## 验证

九套离线回归测试及 Bash 语法/diff 检查；新增正常包、缺包、损坏包、未知架构测试。Linux amd64/arm64 真实计数测试由 CI 执行，只有 CI 成功后才交付对应下载包。Linux 服务替换/自动回滚流程仍需用户测试机验证。

SHA-256 用于完整性校验，信任来源是本项目 GitHub 仓库及其工作流，并非上游官方发布的二进制。源码版本、构建提交及编译标签记录在 manifest 中。
