# Vaio Panel UI 视觉重设计

## Goal

让 Vaio Panel 前端（`platform/web/`）从「通用 SaaS 卡片套件」的观感，变成更专业的运维控制台：黑白为主，提升字体、层级、留白与密度、表格、状态表达、图表和空状态的质感。完成后把测试面板 vps.town 升级到新版本。

## Subject / audience / primary job

- 对象：自托管代理节点的集中管理面板（若干台 VPS，每台运行多个协议实例）。
- 用户：一位或少数运维者，熟悉服务器，日常进来看健康状况、偶尔做安装/改端口/加用户。
- 首要任务：一眼看清哪台节点、哪个实例需要处理；其次是安全地发起变更并追踪结果。

## Requirements

- R1 黑白灰为唯一色彩体系，不引入任何彩色强调色；界面文案中文（CLAUDE.md 约定不变）。
- R2 覆盖页面：登录、总览、服务器节点列表、节点详情（含未接管 / 离线 / 待连接状态）、任务记录、流量统计、监控与通知、备份恢复、操作审计；覆盖弹窗：添加服务器、连接命令、协议选择、协议安装表单、实例管理、执行记录、资源历史、节点设置、账号设置、确认操作、用户编辑、通知设置、回收站、升级节点。
- R3 状态必须在无色彩的前提下可区分（形状 + 填充 + 字重），并对色弱/灰度打印同样有效。
- R4 默认只改视觉与布局：不改后端接口、`submitTask` 参数、`data-action` 名称、任何被处理器或测试使用的元素 id、业务判断逻辑。
- R5 协议安装弹窗（`c39fec1`）保持结构和全部 id、`protocol-card` 按钮的精确标记（`tests/install-form.cjs` 断言），只通过 CSS 统一视觉语言。
- R6 `trafficPage()` 只能使用测试上下文里已有的帮助函数（`esc/badge/bytes/date/icon/shell/names/nodes`）及切片内函数；保留测试断言的文案。
- R7 不加载任何外部资源（字体、CDN）：面板自托管，用户多在受限网络环境，且不应向第三方泄露访问。
- R8 响应式：1280×860 与 375px 两种宽度无横向滚动（表格容器内横滚除外），触屏目标 ≥ 44px；键盘焦点可见；尊重 `prefers-reduced-motion`。
- R9 空的 live region 不得 `display:none`（组件规范）。
- R10 缓存失效：面板版本号升到 `0.3.0-preview.10`，`index.html` 资源 `?v=` 同步。

## 结构性改动（2026-10-12 用户已确认：S1–S4 采用，S5 不做）

- S1 外壳：去掉顶部横栏，品牌、刷新状态、账号设置、退出移到左侧导航栏；移动端为顶栏 + 可横向滑动的导航条（替代当前 4 列换行网格）。
- S2 服务器列表：节点卡片改为「机架行」列表（每台一行：状态灯、名称/主机、内存与磁盘分段条、收发流量、协议标签、实例数）；移动端每行折成紧凑块。
- S3 指标：4 张独立统计卡改为一条分隔的读数带（一个容器、竖线分隔、数值与单位分开排版）。
- S4 资源历史图表：增加横向参考线、最大值/0 刻度、起止时间标注、断线区间留白保持；仍为内联 SVG，无依赖。
- ~~S5 文案细节~~（不做，保留现有文案）：去掉链接文字末尾的「→」、页脚中用「·」串起的说明拆成独立短句；只改界面装饰性文案，不改测试断言文案和业务提示。

## Acceptance Criteria

- [ ] 规划（本文件、design.md、implement.md）经用户确认，S1–S5 有明确取舍。
- [ ] 本地模拟面板截图核对：上述全部页面和弹窗，1280×860 与 375px 各一套，无横向溢出、无遮挡、文字不截断。
- [ ] `bash -n vless-server.sh`、`cd platform && python -m unittest discover -s tests` 通过；`node --check web/app.js`、`node tests/install-form.cjs`、`node tests/traffic-display.cjs` 以 GitHub Actions 结果为准（本机无 Node）。
- [ ] 每项改动一个提交（`feat:/fix:/docs:/chore:` + 英文摘要），推送到 `codex/platform-3.7.4`，CI 绿；不创建 Release。
- [ ] vps.town 通过 termark 执行 `sudo vaio-panel update --ref <完整SHA>`：`EXIT=0`、`/opt/vaio-panel/REVISION` 等于该 SHA、服务 active、首页 200、服务器上 `web/app.js` 与 `web/style.css` SHA-256 与本地一致；备份路径写进文档。
- [ ] `docs/platform-3.7.4-merge.md` 记录改动、测试结果（区分本地模拟 / CI / 测试面板）与部署情况。
- [ ] 不触碰任何节点。

## Out of scope

- 后端接口、Agent、节点脚本、安装升级脚本。
- 深色模式（`color-scheme: light` 保持不变）。
- 新增功能或交互流程。
