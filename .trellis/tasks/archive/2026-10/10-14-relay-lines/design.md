# 设计

## 数据（面板 SQLite，新表，CREATE IF NOT EXISTS）
relay_lines(id, user_id → platform_users ON DELETE CASCADE, landing_node_id, landing_core, landing_protocol, landing_port, landing_host,
            hops TEXT(JSON), state, created, updated)
hops: [{node_id, backend, listen_port, transport, target_host, target_port, forward_id, task_id, status: pending|active|failed|removing}]
state 由各层状态派生：creating / active / partial / removing。

## 创建
- `POST /api/relays` {user_id, hops:[{node_id, backend, listen_port}], landing:{node_id, core, protocol, port, host}}。
- 校验：用户存在；各中转节点已接管、在线、未维护、forward_version=1、上报公网 IPv4（多层时下一层需要）；落地实例存在于快照；服务器不重复；入口端口不与该节点快照中的转发规则或协议端口冲突；落地 host 为 IP 或域名（nftables 层的目标必须为 IPv4）。
- 计算每层目标：hop[i] → hop[i+1].public_ipv4:hop[i+1].listen_port；最后一层 → landing.host:landing.port。transport 按落地协议映射。
- 为每层构造 forward add 规则（remark「中转：<用户> → <落地服务器>」）并直接写入 tasks（同 node_task 的检查：节点无未完成任务，否则整体拒绝）。
- 用户未关联落地协议：无该节点 link → add_link(members=[target])；已有 link 但无该成员 → member_op add。
- 在 result 回调中：forward_apply 任务对应某线路的层 → 成功则记录 forward_id（任务结果 rule.id）并置 active，失败置 failed。

## 删除 / 重试
- 删除：对有 forward_id 的层排队 forward delete（base 取快照中该规则），层置 removing；无 forward_id 的层直接移除；所有层完成后删除线路。节点上规则已不存在则视为完成。
- 重试：对 failed 层重新排队 add。

## 连接信息
- `POST /api/relays/<id>/share` → 对落地节点创建 share 任务，params {name: 用户在该协议的成员名, host: 入口中转公网 IP, port: 入口端口}。
- 脚本 `account_share` 新增可选 `port`（覆盖链接端口，`VAIO_SHARE_PORT`）；Agent `ScriptAPI.share(target, name, host, port)`；common.validate_task 的 share params 接受 `port`。

## 节点公网地址
- Agent 快照增加 `addresses: {ipv4, ipv6}`（addresses.discover，5 分钟缓存）；sanitize 只保留全局单播地址。

## 前端
- `relaysPage`（筛选菜单：服务器）、`relayDialog`：用户 select-menu；`.relay-flow` 两栏 + 中间箭头（窄屏上下排列，箭头向下）；中转层列表可增删；落地协议选项标注「已关联 / 将关联」。
