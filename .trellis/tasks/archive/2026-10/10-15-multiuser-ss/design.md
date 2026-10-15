# 设计

## 节点脚本（3.7.4-preview.15）
- `_sync_all_user_traffic_unlocked` 的 Sing-box 用户循环加入 `ss2022`（多用户 SS2022 已由渲染器命名为 `ss2022-用户名`）。单用户 SS2022（无 users 字段的入站）仍由 `_sync_ss_inbound_traffic` 按入站计数，用户键查询得 0，不会重复计数。
- `_singbox_stats_config_ready` 的协议列表加入 `ss2022`。
- 同步 vendor 副本、UPSTREAM_SHA、vendor README。

## 节点程序
- `inventory.mutable`：去掉 SS/SS2022 的「面板安装 + 单用户」限制；写入前仍由 runtime 校验运行配置是受管的 shadowsocks 入站（类型、无 destinations/中转），不符合时拒绝。
- 新增 `ss_user_stats(proto, row)`，与渲染器判断一致：
  - ss-legacy：用户数 > 1 → 按用户统计；
  - ss2022：有实例密钥且（用户数 ≠ 1 或唯一用户密钥 ≠ 实例密钥）→ 按用户统计；
  - 其余按入站统计。
- `billing.traffic_state`：按入站统计的单用户 SS 看该用户的 `traffic_observed_at`；按用户统计的看 `meta.traffic_observed_singbox`。
- `Bridge.share`：按用户统计格式的 SS2022 输出 `方法:服务端密钥:用户密钥`。
- 本地到期 / 配额执行（reconcile）随 `mutable` 自动覆盖多用户 SS。

## 面板
- 无接口变化；实例弹窗按节点上报的 `managed` 与 `traffic_state` 显示。
- 版本 1.5.0（节点程序需一键更新到 1.5.0，脚本随之更新）。

## 兼容
- 单用户旧实例格式不变；多用户的渲染沿用脚本已有格式。
- 回滚：节点程序回到旧版即恢复只读限制。
