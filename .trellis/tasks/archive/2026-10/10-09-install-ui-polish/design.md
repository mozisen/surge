# 设计

## 边界
只改前端三处：`web/app.js` 的 `install()`、`installForm()`（含 `updateFields`）；`web/style.css` 的弹窗和安装表单样式；`tests/install-form.cjs`。`modal()` 仅增加可选的类名参数，其他调用方不受影响。

## 第一步：卡片
- 仍渲染 `<form id="protocol-choice-form">`，内部每张卡片是 `<button type="submit" class="protocol-card" value="<protocol>">`。submit 处理读取 `e.submitter.value`，校验在可选列表内后调用 `installForm(protocol)`。按钮天然支持 Tab/Enter/空格。
- 卡片元数据放在一个常量 `INSTALL_CARD_META`：`{vless:'Reality · TCP', hy2:'QUIC · UDP', trojan:'TLS · TCP', anytls:'TLS · TCP', 'ss-legacy':'TCP + UDP', ss2022:'TCP + UDP', snell/snell-v5/snell-v6:'独立核心 · TCP'}`（只写现有说明里已有的事实）。
- 内核列表来自 `installCombinations()`，已安装数来自 `selected.snapshot.instances`。
- 保留 `#protocol-choice` 为隐藏 input，兼容测试中的 id 列表；也可从测试中删除，优先删除以免留无用元素。

## 第二步：表单结构
```
.install-intro      协议说明（#protocol-guidance）+ 返回（#install-back）+ 内核（#install-core-field）
section 基础设置     端口 | SNI ；用户名 ；SS 加密方式（ss 时）
section 证书设置     #certificate-fields（保留 id）
details 高级设置     #credential-fields、#reality-fields、#snell-fields（保留 id）
.install-status     #install-options-status、#generation-feedback、.error
.modal-foot (sticky) 安装可能需要数分钟提示 + 安装实例
```
- `#ss-method-field` 从凭据 fieldset 移到基础设置；仍由 `updateFields` 控制 hidden。
- 「高级设置」用 `<details id="install-advanced">`；当内部三个分组都隐藏时整个 details 也隐藏（`install_options_version` 0 的节点）。
- 输入 + 生成按钮用 `.input-action` 包裹（grid: 1fr auto），按钮 id 不变。
- `#generated-credentials` 移到高级设置内部顶部。

## 样式
- `dialog.install` 宽 760px；`.modal-body` 在该类下为 flex 列，中间 `.install-scroll` 滚动，`.modal-foot` sticky bottom，带上边框和背景。
- `.protocol-grid`：`repeat(auto-fill, minmax(200px, 1fr))`；卡片 1px 边框，hover/focus-visible 改为 `--ink` 边框。
- 分组标题 13px 600，上方 1px 分隔线；去掉 fieldset 默认边框（fieldset 保留语义，样式 `border:0;padding:0`）。
- 窄屏沿用 `.form-grid` 单列断点。

## 兼容与回滚
- 无数据和接口变化；回滚即 revert 提交。
- 风险点是 `updateFields` 依赖的元素被移动后 hidden 逻辑失效，由 install-form.cjs 的现有断言和截图核对覆盖。
