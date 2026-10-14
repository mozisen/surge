# 发布 Vaio Panel 1.0.0 到 mozisen/vaio-panel

## 已确认
- 内容：以 surge 的 `platform/` 为仓库根目录（面板、节点程序、安装升级脚本、内置节点脚本副本、测试、文档）。
- 清空：vaio-panel 的 main 强制替换为全新的 1.0.0 提交（不保留旧历史），删除 6 个 codex/* 旧分支。
- 安装与升级默认从 mozisen/vaio-panel 下载。

## Requirements
1. 版本改为正式版 1.0.0（面板与节点程序版本一致）。
2. 安装脚本 `install-panel.sh`：默认从 `mozisen/vaio-panel` 下载（`VAIO_SOURCE_REPO`、`VAIO_SOURCE_REF` 可覆盖，默认 `main`）；源码包兼容「仓库根即面板」与旧的 surge `platform/` 布局。
3. 升级 `vaio-panel update`：默认 `--repo mozisen/vaio-panel --ref main`，仍可 `--repo mozisen/surge --ref <分支>` 升级预览版；解包兼容两种布局。已部署的旧版面板第一次升级到 1.0.0 时需显式指定（旧更新器只认 surge）。
4. vaio-panel 仓库自身：README（安装、升级、节点接入、开发测试）、CHANGELOG（1.0.0 功能概览）、GitHub Actions（unittest、cjs、shell 语法、镜像构建）。
5. 发布：推送 1.0.0 提交到 vaio-panel main（强制），打标签 `v1.0.0`，删除旧分支；创建 GitHub Release「Vaio Panel 1.0.0」标为最新正式版（需要 GitHub 凭据，若无法用 API 创建则请用户在网页上由标签创建）。
6. surge 仓库：记录发布流程与版本；今后面板以 surge `platform/` 开发、按此流程同步到 vaio-panel。

## Acceptance Criteria
- [ ] 解包两种布局、默认仓库与参数校验有测试；全部测试通过；surge CI 通过
- [ ] 导出的 vaio-panel 目录可独立通过 unittest 与 cjs 测试
- [ ] vaio-panel main 为单个 1.0.0 提交、仅 main 分支、有 v1.0.0 标签；其 Actions 通过
