# surge / Vaio Panel 统一项目

本仓库同时包含节点脚本和面板。协作规则见 @AGENTS.md 与 @platform/AGENTS.md，必须遵守；本文件只补充入口信息。

## 结构

- `vless-server.sh`：节点交互管理脚本及版本化接口（`--api`）。
- `platform/`：Vaio Panel 面板（`vaio`、`web`）、节点 Agent（`agent`）、安装升级脚本和测试。面板开发以这里为准，独立的 `mozisen/vaio-panel` 仓库是较旧的 0.2.x 代码。
- `platform/vendor/vless-server.sh`：根目录脚本的逐字节副本。改动根脚本后必须同步副本、`platform/agent/runtime.py` 的 `UPSTREAM_SHA` 和 `platform/vendor/README.md`。
- 入口说明见 `docs/unified-project.md` 与 `platform/docs/monorepo.md`。

## 分支与版本

- `main` 是正式版，只在发布时更新。预览版在 `codex/*` 分支开发和推送，不创建或更新 GitHub Release。
- 当前开发分支：`codex/platform-3.7.4`（脚本 3.7.4-preview.2，面板 0.3.0-preview.8），合并说明见 `docs/platform-3.7.4-merge.md`。
- 每个预览版在 `docs/` 或 `platform/docs/` 记录版本、改动和测试结果。

## 修改后的检查

```sh
bash -n vless-server.sh
for t in tests/*.sh; do bash "$t" || echo "FAILED $t"; done   # singbox-stats-live.sh 需要真实统计核心
cd platform
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node --check web/app.js && node tests/install-form.cjs && node tests/traffic-display.cjs
```

推送后以 GitHub Actions（`.github/workflows/platform.yml`）结果为准。

## 提交与验证

- 提交信息沿用现有格式：`feat:`、`fix:`、`docs:`、`chore:` 前缀加英文摘要；每次改动一个提交。
- 已有提交的作者信息不改写，不强制推送。
- 隔离或模拟测试通过不等于真实 VPS 验收通过，汇报时分开说明。没有明确授权不操作生产节点。
- 界面文案使用中文、黑白简约风格。
