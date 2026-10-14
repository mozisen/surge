# Vaio Panel 正式版发布流程

面板在本仓库 `platform/` 开发，正式版同步发布到 [mozisen/vaio-panel](https://github.com/mozisen/vaio-panel)（仓库根即 `platform/` 的内容）。

## 1.0.0（2026-10-14）

- 来源：surge `codex/platform-3.7.4`，面板与节点程序 1.0.0，内置节点脚本 3.7.4-preview.12。
- 经用户确认：vaio-panel 原有内容（0.2.x 面板及 6 个 `codex/*` 分支）清空，`main` 强制替换为单个 1.0.0 提交，打标签 `v1.0.0`。
- 安装与升级默认来源改为 `mozisen/vaio-panel`（`install-panel.sh` 的 `VAIO_SOURCE_REPO`/`VAIO_SOURCE_REF`，`vaio-panel update --repo/--ref`，默认 `main`）；仍可用 `mozisen/surge` 安装或升级预览版，两种源码包布局都能解包。
- 已部署的 0.3.x 预览版面板：旧更新器只认 surge，先 `vaio-panel update --ref codex/platform-3.7.4` 升到 1.0.0，之后默认从 vaio-panel 升级。

## 发布步骤

1. 在 surge 完成改动、测试与 CI，版本号写入 `platform/vaio/__init__.py`、`platform/web/index.html`、`platform/CHANGELOG.md`。
2. 导出：`git archive <提交>:platform` 解包到空目录，确认 `python -m unittest discover -s tests` 与三个 cjs 测试在导出目录独立通过。
3. 在导出目录提交（作者为仓库所有者），推送到 vaio-panel `main`，打标签 `v<版本>` 并推送；在 GitHub 由标签创建 Release，标为最新正式版。
4. 在本文件记录版本、来源提交与验证结果。预览版不发布到 vaio-panel。
