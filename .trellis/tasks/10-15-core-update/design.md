# 设计

## 内核与服务
| 内核 | 二进制 | 版本命令 | 最新版本（脚本函数） | 使用它的服务 |
|---|---|---|---|---|
| xray | /usr/local/bin/xray | `xray version` | `_get_latest_version XTLS/Xray-core` | `vless-reality` 及 core=xray 的非 Snell 行 |
| singbox | /usr/local/bin/sing-box | `sing-box version`（含 with_v2ray_api 即带统计） | 统计版预编译包：`mozisen/surge` 分支 `singbox-stats-binaries` 中含本机 `linux-架构-libc` 的最大 `vX.Y.Z`；官方 `_get_latest_version SagerNet/sing-box` 仅作参考 | 由脚本 `_update_singbox_preserving_stats` 自行停启与回滚 |
| snell-v5 | /usr/local/bin/snell-server-v5 | `--version` | `_get_latest_version surge-networks/snell` | protocol=snell-v5 的行（`vless-snellu-*` 或 `vless-snell-v5`） |
| snell-v6 | /usr/local/bin/snell-server-v6 | `--version` | `_get_snell_v6_stable_version`（只取稳定版） | protocol=snell-v6 的行 |

服务集合由节点程序按 db.json 的行与 `service_for` 计算，加上该内核的主服务。

## 节点程序
- 后台线程 `watch_cores`：每 10 分钟读当前版本；每 6 小时通过脚本库（与 `upstream` 相同的完整性校验）取最新稳定版本。快照增加 `cores: {xray: {current, latest}, singbox: {current, latest, stats}, ...}` 与 `core_update_version: 1`。
- Sing-box 一律更新到统计版预编译包（没有对应包就不提供更新；脚本不会编译），调用 `_update_singbox_preserving_stats stable 版本`，校验新版本与 with_v2ray_api；官方更新而统计包未发布时界面提示「统计版待发布」。
- 新任务 `core_update {core}`（`validate_core_task`），由 bridge 走事务记录（结果不明不重放）。执行流程：
  1. `runtime.sync_traffic()`（失败只记录，不阻止更新）。
  2. 解析目标版本 = 节点重新查询的最新稳定版；与当前相同则直接成功。
  3. 备份二进制到 state 目录。
  4. 记录在运行的服务，逐个停止（Sing-box 带统计时跳过此步，由脚本的保留统计路径自行停启与回滚）。
  5. `upstream(install_xray|install_singbox|install_snell_v5|install_snell_v6, "stable", "true", 版本)`；Snell v6 用 `install_snell_v6 版本`。
  6. 读取新版本，必须等于目标；启动原来在运行且未被面板暂停的服务，检查运行。
  7. 失败：恢复备份二进制，启动原服务，返回失败信息（恢复失败报结果未知）。
- `upstream` 白名单增加取版本的函数；新增可捕获输出的调用。

## 面板
- `validate_core_task`：`{"action": "core_update", "params": {"core": xray|singbox|snell-v5|snell-v6}}`。
- `POST /api/nodes/<id>/core-update {core}`：在线、已接管、未维护、`core_update_version == 1`、已安装、`latest` 存在且不同于 `current`、无未完成任务。
- `POST /api/nodes/core-update-all {core}`：同条件批量排队，返回 `{queued, skipped:[{name, reason}]}`。
- 任务记录：动作名「更新内核」，摘要「Xray 25.1.30 → 25.3.6」。

## 前端
- 服务器详情侧栏增加「内核」区：每个已安装内核一行（名称、当前 → 最新或「已是最新」、更新按钮）；Sing-box 无统计时提示。更新确认框说明会短暂中断。
- 服务器页标题按钮增加「一键更新内核」，对话框选择内核，显示可更新节点数，确认后显示排队与跳过结果。

## 兼容与回滚
- 旧节点程序不上报 `cores`，界面显示「需更新节点程序」。面板与节点均只新增字段与任务类型。
- 不修改节点脚本；Sing-box 统计核心的构建与恢复沿用脚本逻辑。
