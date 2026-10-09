# 实施清单

1. `modal()` 支持额外类名（如 `install`），不影响现有 `wide` 调用。
2. 重写 `install()`：卡片网格，submit 读取 `e.submitter.value`。
3. 重排 `installForm()` 标记结构（保留全部现有 id），`updateFields()` 增加高级设置整体显隐；其余逻辑不动。
4. `style.css`：卡片、分组、`.input-action`、sticky 底栏、窄屏规则；删除被替代的 `.install-generate` 大按钮样式。
5. 更新 `tests/install-form.cjs`：卡片 submit 路径（含非法值被忽略），新元素 id 加入桩列表；原有提交参数断言保持不变。
6. 本地模拟节点截图：卡片页、VLESS、Hysteria2、SS2022、Snell v6，各一张 1280×860；卡片页和一个表单再各一张 375px。
7. 验证命令：
   - `node --check web/app.js && node tests/install-form.cjs && node tests/traffic-display.cjs`（本机无 Node，需要临时获取或以 CI 为准）
   - `python -m unittest discover -s tests`
8. 记录：在 `docs/platform-3.7.4-merge.md` 的 preview.9 段补一行界面改动；提交 `feat: redesign protocol install dialog`；推送预览分支，看 CI。

回滚点：单个提交，`git revert` 即可。
