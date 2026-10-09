# 现有安装界面调查（2026-10-09，本地模拟节点，视口 1280×860）

代码位置
- `platform/web/app.js:475` `installCombinations()`：按节点 `write_capabilities` 过滤出已实现表单的 `core:protocol` 组合。
- `platform/web/app.js:487` `install()`：第一步，下拉框 `#protocol-choice` + 「下一步」，提交 `#protocol-choice-form`。
- `platform/web/app.js:500` `installForm(protocol)`：第二步，一个长表单字符串；`updateFields()` 按协议和 `install_options_version` 切换 hidden/disabled/required。
- `platform/web/app.js:140` `modal(title, body, wide)`：所有弹窗共用，`wide` 加 `.wide` 类。
- `platform/web/style.css:827` `dialog` 宽 560px，`max-height: 90vh`；`style.css:872-913` 安装表单专用样式。
- `platform/tests/install-form.cjs`：在 vm 中执行 `installPortCandidate` 到 `editUser` 之间的代码，按元素 id 断言行为，并调用 `#protocol-choice-form` 的 submit 事件。

观察到的问题
1. 协议选择只有一个下拉框，看不到内核、传输方式或已安装数量。
2. 表单弹窗 560px 宽，Hysteria2 表单 scrollHeight 1219px，可视 774px；底部「安装实例」按钮需滚动才能看到。
3. 「自动生成端口/SNI/用户名/凭据/Short ID」按钮各自独占一行（min-height 44px），视觉权重高于输入框。
4. fieldset/legend 使用浏览器默认样式，分组像套框。
5. 协议说明（`#protocol-guidance`）、凭据生成说明（`#generated-credentials`）、生成反馈（`#generation-feedback`）全部堆在表单底部，离相关字段很远。
6. 高级参数（凭据、Reality 密钥、Snell v6 连接设置）与必填项同等展示。

约束
- 界面文案中文、黑白简约（CLAUDE.md）。
- 提交给 `submitTask('install', …)` 的参数结构不能变；`install_options_version` 0/1/2 三种节点都要可用。
