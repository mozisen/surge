# 只读管理接口接入验收

2026-09-21，面板/Agent 开发版本 `0.2.2-preview.1`，上游脚本 `3.7.3-preview.1`。

## 已完成

- 固定上游提交、脚本校验值和来源说明；原配置适配器行为不变。
- Agent 只读接口桥接：查询 capabilities/inventory，验证请求 ID、协议版本和能力契约；60 秒缓存，失败不影响原有任务能力。
- 脚本的全数据库 revision 与面板的配置 revision 保持独立；未将只读响应当作写权限或可执行计划。
- 快照再次白名单过滤；面板展示只读接口状态、版本与协议组合数量。
- 49 项隔离回归通过，JavaScript 及 Bash 语法检查通过。

## 真实 VPS 验收

通过 termark 更新授权测试节点 ovh-vps-1 的 `/usr/local/bin/vless-server.sh`；`vless` 软链接保持原状。旧脚本及配置保存在节点 `/var/backups/vaio-script-preview/1789972845090043342`，权限限制为 root。

在数据库锁内运行完整 Linux CLI，验证 capabilities/inventory、plan 的版本冲突与不支持操作、11 种写入/分享/迁移动作拒绝，以及未知 result 不允许重放。识别到 26 种协议与内核组合、7 个既有实例。响应未包含 UUID、密码、PSK、私钥及 Telegram 绑定字段；前后数据库、Xray/Sing-box 配置和 Agent 身份内容一致。原代理与 Agent 服务运行正常。隔离运行新 Agent 桥接器并经过面板快照过滤后，正确得到 ready、预览版本、26 种组合和 7 个实例；临时执行目录已自动清理。

## 尚未完成的依赖

上游 `write_actions=[]`，全部协议 `write_supported=false`，plan 不生成可执行计划。新增、修改、删除、用户操作、分享、迁移和完整事务仍须在原脚本实现后逐协议接入。此次验收不能用于声明全协议管理完成，也不属于写入或客户端连通性测试。

本分支为预览适配，未替换 vps.town 正式面板及节点运行中的 Agent。节点上的独立原脚本预览版与 Agent 内固定脚本是两份文件，升级前者不会自动改变后者。
