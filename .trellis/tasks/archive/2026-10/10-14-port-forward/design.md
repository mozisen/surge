# 设计

## 规则模型（脚本与平台统一）
`{id, backend: realm|nftables, remark, transport: tcp|udp|tcp+udp, listen_host, listen_port, remote_host, remote_port, enabled}`
- Realm：`id` 为 12 位十六进制，缺失时脚本首次读取补齐并写回。
- nftables：`id = "nft-<listen_port>"`（监听端口在该类型内唯一）。transport 固定 `tcp+udp`，listen_host 固定 `0.0.0.0`。

## 脚本存储
- `realm/rules.json`：Realm 全部规则；nftables 的元数据（remark）与停用规则（enabled=false）。
- `/etc/nftables.d/port-forward.conf`：启用中的 nftables 规则，与 nft.sh 相同的生成格式（table ip port_forward；DNAT + `ct status dnat` SNAT 到本机 IP）。读取时按 nft.sh 的方式解析 tcp dnat 行；conf 中有而 rules.json 没有的规则视为脚本/nft.sh 新增（无备注）；rules.json 中标记启用但 conf 中已没有的视为已被 nft.sh 删除。
- nftables 启用：确保 `/etc/nftables.conf` include `/etc/nftables.d/*.conf`、nftables 服务开机启用、`/etc/sysctl.d/99-nft-forward.conf` 写入 ip_forward=1（与 nft.sh 相同路径），`nft -f` 加载前 `nft -c` 校验。
- 流量：Realm 沿用 iptables `VLESS_REALM_COUNTERS`（入站）；nftables 使用独立表 `inet vless_forward_stats`（forward 链按目标及回程计数），每次应用与流量同步时重建，重启后清零。状态：Realm 服务是否运行、端口是否在监听；nftables 规则是否已加载到内核。

## 脚本接口
- inventory：`forwards: [{...rule, status: running|stopped|disabled, bytes: n|null}]`、`forward_status: {realm_installed, realm_running, nft_available}`。
- `forward_apply`：`params.ops = [{op: add|update|delete|enable|disable, id?, base?, rule?}]`，单请求单操作。`base` 为修改前规则的指纹（排序后 JSON 的 sha256 前 16 位），与当前不一致返回 `rule_changed`。事务：共用 `.txn.lock`、`api-results` 幂等、备份 rules.json / realm config / port-forward.conf、执行、Realm 重启或 nft 重载；失败恢复备份并重载，恢复失败为 unknown。
- 校验失败码：`invalid_request`、`port_conflict`、`rule_not_found`、`rule_changed`、`nft_unavailable`、`realm_install_failed`、`apply_failed`。
- capabilities 增加 `forward_api: {version: 1, backends: [...可用的]}`。

## 节点程序
- `ScriptAPI.forward(params, id)` 与 `result()`；Bridge 新动作 `forward_apply`（同 platform_apply 的记录/未知处理）。
- 快照从 script inventory 读取 forwards（60 秒缓存，随 status 刷新），`forward_version = 1` 当能力声明存在。清洗：最多 500 条，字段类型与长度检查。

## 面板
- `common.validate_forward_task`；`POST /api/nodes/<id>/forwards`（body: op/id/base/rule）→ node_task；离线、维护、无能力时 409。规则校验与脚本一致（端口范围、地址格式、nftables 约束、同服务器端口冲突用快照预检）。
- 前端 `forwardsPage`：筛选菜单、表格、弹窗（复用 select-menu）、启停与删除确认、提交后打开任务记录。

## 兼容
- 旧节点没有 forwards：页面列出但标注「需升级节点程序」，不可新增。
- 不改变用户管理方式；转发规则与用户归属无关，脚本与平台都可修改。
