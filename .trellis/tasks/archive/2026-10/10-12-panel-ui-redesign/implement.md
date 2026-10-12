# Implement: Vaio Panel 黑白运维控制台

前置：用户确认 prd.md（含 S1–S5 取舍）与 design.md 后执行 `task.py start`。实现由 trellis-implement 子代理完成，检查由 trellis-check 子代理完成；提交由主会话执行。

## 有序清单

1. **chore: bump panel to 0.3.0-preview.10**
   - `platform/vaio/__init__.py`、`platform/web/index.html` 两处 `?v=`、CLAUDE.md「当前开发分支」一行。
2. **feat: redesign panel shell and design tokens**（style.css 基础 + `shell()`）
   - 重写 `:root` token（保留旧变量名为别名）、基础元素、按钮、输入、徽章（伪元素状态标记）、表格、面板、提示条、弹窗、toast。
   - 清理 style.css 末尾多次层叠覆盖的重复规则，合并为一套（当前文件后半段大量「再覆盖一次」的块）。
   - S1：`shell()` 侧栏含品牌/导航/底部状态与账号；移动端顶栏 + 横滑导航。
3. **feat: redesign overview and node list**
   - S3 读数带：`summary()`、`stat()`；S2 机架行：`card()`、`nodeCards()`，新增 `meter()` 分段条（放在 `card()` 前）；`emptyNodes()`。
4. **feat: redesign node detail, tasks, traffic, monitor, backups and audit pages**
   - `detail()` 头部/提示条/侧栏；`taskTable()`、`protocolTable()`、`trafficPage()`、`monitorPage()`、`backupPage()`、审计表：加 `.num` 列类、紧凑按钮。`trafficPage()` 不调用切片外的新函数。
5. **feat: unify dialog styling**
   - CSS 统一弹窗头/体/尾；安装弹窗只调 CSS（卡片、分组、状态区与新 token 对齐），不改其模板。
   - 其余弹窗模板只做展示性调整（类名、包装元素），不动 id 和处理器。
6. **feat: redraw resource history charts**（S4）
   - `historyDialog()` SVG：参考线、刻度、起止时间、面积填充。实现前加载 `dataviz` 技能核对图表规范。
7. ~~S5 文案~~：用户决定不做，现有文案保持不变。
8. **docs: record panel UI redesign**：`docs/platform-3.7.4-merge.md` 记录版本、改动、测试与部署。

每步完成后：本地预览（scratchpad `preview.py`）+ `shots.py after` 截图核对 1280×860 与 375px。

## 验证命令

```sh
bash -n vless-server.sh
cd platform && ../<venv>/bin/python -m unittest discover -s tests
# 本机无 Node：以下以 GitHub Actions 为准
node --check web/app.js && node tests/install-form.cjs && node tests/traffic-display.cjs
```

额外本地静态检查（替代部分 Node 检查）：
- 用 Python 抽取 app.js 中所有 `$('#…')` 与模板 `id="…"`，对比改动前后集合，确保无 id 丢失。
- 抽取所有 `data-action="…"` 集合前后对比。
- 用 Chrome 无头（playwright）加载页面，收集 console error，确认 JS 无语法/运行错误（等同 `node --check` 的实际效果）。

## 审查关口

- 关口 A（步骤 2 后）：截图自审外壳与 token，不合格则回到步骤 2。
- 关口 B（步骤 6 后）：trellis-check 全量检查（规范、id/data-action 对比、测试切片边界、可访问性、375px 溢出）。
- 关口 C：推送后 CI 绿才部署测试面板。

## 部署（CI 绿后）

```sh
termark … 5g9gYsAk9m7sthic: nohup sudo vaio-panel update --ref <SHA> > /root/vaio-update-<short>.log 2>&1; echo EXIT=$? >> 同一日志 &
```
检查：日志 `EXIT=0`、`/opt/vaio-panel/REVISION`、`systemctl is-active`、首页 200、服务器 `web/app.js`、`web/style.css` 的 `sha256sum` 与本地一致；记录备份路径。

## 回滚点

- 每个提交可单独 `git revert`。
- 测试面板回退：`sudo vaio-panel update --ref 3a2d844…`（部署前记录当前 REVISION 的完整 SHA）。
