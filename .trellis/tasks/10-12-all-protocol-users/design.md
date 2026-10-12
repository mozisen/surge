# 技术设计

版本：脚本 3.7.4-preview.6 起，面板与 Agent 0.3.0-preview.13 起。

## 1. 协议用户能力表（脚本为准，三层共用）

脚本新增 `_proto_user_mode <proto>` → `multi|single|none`，`_proto_user_stats <proto>` → `user|inbound|port|none`：

| 协议 | 模式 | 统计 |
|---|---|---|
| Xray vless、vless-vision、vless-ws、vless-ws-notls、vless-xhttp、vless-xhttp-cdn、vmess-ws、trojan、trojan-ws、ss-legacy、ss2022 | multi | user |
| Sing-box vless、trojan、hy2、tuic、anytls、ss-legacy、ss2022 | multi | user |
| Xray socks | single | inbound（Xray 入站统计） |
| snell、snell-v5、snell-v6 | single | port（nft，现状） |
| snell-shadowtls、snell-v5-shadowtls、ss2022-shadowtls | single | port（nft） |
| naive | single | port（nft） |
| SOCKS 免认证（`auth_mode=noauth`） | none | — |

`capabilities` 增加 `user_modes`（协议 → 模式与统计），`inventory` 的每个实例增加 `user_mode`、`user_stats`。`accounts_api.version` 升为 3。

## 2. 阶段 A：多用户协议与分配语义（子任务 1，脚本 3.7.4-preview.6）

### 2.1 SS2022 多用户
- 行字段 `password` 作为服务端密钥；用户的 `uuid` 作为用户密钥（长度与加密方式一致）。
- 生成器：当 `users` 只有一个且其 `uuid == password`（旧单用户）时，保持原来的单密码入站；否则 Xray 生成 `settings.password=服务端密钥, clients=[{password, email}]`，Sing-box 生成 `password=服务端密钥, users=[{name, password}]`。
- 分享链接：多用户时 `ss2022` 密码为 `服务端密钥:用户密钥`。
- 统计：Xray 按 email，Sing-box 按 users name，与其他多用户协议一致。

### 2.2 分配语义（single）
- `account_apply` 的 `member_add` 对 `single` 实例：实例没有用户时分配（生成新凭据、写入用户记录、按协议重写服务配置、按状态启停）；已有用户则拒绝（`instance_occupied`）。
- Snell：沿用现有一用户一实例布局，`member_add` 走分配路径（重写 PSK、按状态启停），不再需要「安装后归入」。
- 菜单「添加协议」同样按模式区分：multi 新建账号；single 只列空实例。

### 2.3 连接信息
- `account_apply` 之外新增 `--api account_share {target, name}`，按协议调用现有的 `_gen_user_share_link`，返回链接文本。只读，不写结果记录；Agent 把它作为 `share` 任务的结果（现有的 10 分钟清理逻辑）。

### 2.4 安装提示
- 安装菜单在选择协议后，按能力表提示：`single` 显示「一用户一实例，流量按端口/入站统计」；`none`（SOCKS 选择免认证时）显示「该协议不支持用户管理」。
- 平台模式下脚本安装不生成 default 用户（空实例）。

## 3. 阶段 B：一用户一实例适配（子任务 2，脚本 3.7.4-preview.7）

对 SOCKS、Naive、Snell+ShadowTLS、Snell v5+ShadowTLS、SS2022+ShadowTLS：

- **多实例**：数据库行改为数组（每个实例独立端口、`instance_id`），沿用 Snell 用户实例的显式迁移思路：现有单实例原样保留为第一个实例，迁移只在管理员分配或新增实例时发生。
  - SOCKS：Xray 每个实例一个入站（已支持多端口数组），入站标签固定，统计按入站标签计入该实例的唯一用户。
  - Naive：同一个 Caddy，每个实例一个站点块（独立端口、独立 `basic_auth`）；停用一个实例就移除它的站点块并重载 Caddy。nft 按端口计数。
  - ShadowTLS 组合：每个实例一套独立的前端 shadow-tls 服务和后端服务（`vless-<proto>-<instance_id>`、`...-backend-<instance_id>`），后端端口自动分配。停用就停这两个服务。nft 按前端端口计数。
- **用户记录**：每个实例 `users=[{name, uuid, ...}]`（最多一个）。凭据映射：SOCKS 用户名=name、密码=uuid；Naive basic_auth 同上；Snell PSK=uuid；SS2022 密钥=uuid；ShadowTLS 密码随实例生成，分配时一并更换。
- **启停门控**：沿用 `_snell_prepare_user` 的模式：服务启动前检查用户启用、未到期、未超额；统一用户结算后状态变化时重写配置并启停。
- **计数**：nft 计数器复用 Snell 的 `vless_snell_users` 表结构（改名为通用的端口计数表并兼容旧表），流量同步写入用户 `used`；SOCKS 用 Xray 入站统计。

## 4. Agent（子任务 3，0.3.0-preview.13）
- `share` 任务：实例不在 Agent 适配器范围内时，改为调用脚本 `account_share`（同样不保存凭据到面板之外）。
- `install` 任务：节点为平台模式时，安装空实例（不生成 default 用户）。
- 快照透传 `user_mode`、`user_stats`；sanitize 枚举校验。

## 5. 面板（子任务 4，0.3.0-preview.13）
- **成员选择**：「协议」对话框的新建账号列出所有 `multi` 实例（不再限于 `managed`）；新增「分配实例」列出空的 `single` 实例。
- **安装时选择用户**（仅平台模式节点）：
  - 多用户协议：先下发 `install`（空实例），成功后为每个选中用户确保关联（必要时新建节点统一用户）并 `member_add` 到该实例。
  - SS、Snell：每个选中用户各装一个实例（端口按现有候选规则递增），成功后分配给对应用户。
  - 编排：`platform_pending` 中记录「等待安装完成后执行」的操作，安装任务成功后释放；失败时丢弃并提示。
- **显示**：成员与实例旁标注模式（一用户一实例）和统计方式（按入站/端口）；按入站或端口统计的协议同样计入配额。
- **提示**：安装表单对 `none` 显示「该协议不支持用户管理」。

## 6. 兼容
- SS2022 单密码实例、现有 SOCKS/Naive/ShadowTLS 单实例在未分配或迁移前行为不变。
- 旧 Agent / 旧脚本不上报 `user_mode`：面板按现状处理（只允许 managed 多用户实例）。
