# 脚本统一用户（3.7.4-preview.3 至 preview.7）

预览版本：`3.7.4-preview.3`，分支 `codex/platform-3.7.4`。只推送预览分支，不更新 main，不创建 GitHub Release。

这是「平台统一用户管理」的第一步：脚本自己就能让一个用户使用多个协议，到期和流量统一管理，**不需要安装 Agent，也不需要接入面板**。面板的平台用户和双向同步在后续预览版实现。

## 使用

`vless` → 用户管理 → `a` 统一用户：

- **新建统一用户**：用户名、流量配额（GB，0 表示不限）、到期日期（天数或日期，0 表示永不过期）、每月重置日（1–28，0 表示累计不重置）、备注。
- **添加协议**：在已安装的多用户协议实例里，为这个用户新建一个协议账号，凭据自动生成，每个协议的凭据互相独立。Snell（已启用一用户一实例的 v4/v5/v6）会为该用户新建一个独立端口实例。SOCKS 和其他独立协议不支持。
- **归入现有协议用户**：把已有的协议用户加入统一用户，凭据不变，客户端不用改。可以选择是否把它已用的流量计入本周期。
- **按用户名批量归并**：列出出现在两个及以上协议里的同名用户（不含 default 和已归属的用户），预览确认后才执行。名字已有统一用户的就加入它；没有的就新建一个配额不限的统一用户，到期日取各成员中最晚的，只要有一个成员永不过期，新用户就永不过期。
- 查看和修改（到期、配额、重置日、启停、备注、用户名）、移除协议（保留为普通协议用户或一并删除）、查看全部分享链接、重置凭据（全部或单个成员）、重置本周期用量、删除统一用户（保留或删除成员）、解除 Vaio 平台关联。

在按协议的用户菜单里，统一用户的成员会标注「属于 xxx」。修改成员的配额、到期、启停或删除成员时，脚本会提示去修改统一用户，避免同一个用户出现两套规则。

## 执行规则

- 每次流量同步（`--sync-traffic`）、到期检查（`--check-expire`）和每次修改统一用户之后都会结算一次，重复结算结果不变：
  - 用量：按成员协议用户的累计计数取增量，计入本周期；计数回落（核心重启、手动清零）时按新计数计入，不会重复计算，也不会出现负数。
  - 周期：按统一用户自己的重置日和节点本地日期切换，清零后自动恢复因超额停用的协议。修改重置日只换算周期，不清零本周期用量。
  - 状态：手动停用 > 已到期 > 本机流量用尽 > 平台总流量用尽。只要有一项成立，就停用全部成员协议；手动停用不会被月度重置恢复。
- 成员协议用户的到期日随统一用户同步，配额置 0，启停由统一用户决定。现有的配置生成器、Agent 和到期检查不需要任何改动就能正确执行。
- 节点全局月度重置和协议级配额停用都会跳过成员。
- 配置只在成员状态有变化时重建，每个核心最多重建一次。重建失败时数据库仍保存新状态，失败的协议记在 `meta.accounts_reload_pending`，下次结算时重试。

## 数据结构

`db.json` 新增顶层 `accounts`（按 id 索引），协议用户新增 `account_id`。都是附加字段，旧数据不会被自动迁移。统一用户包含 `rev` 和各字段的 `mtime`，修改同步字段时会更新；另有 `platform_user_id`、`platform_block` 字段，为后续的面板双向同步预留。面板的配置版本号忽略 `cycle_used`、`last_raw`、`accounts_reload_pending`，避免每次流量同步都让面板任务因配置变化被拒绝。

## 兼容与回滚

- 回滚到 3.7.4-preview.2：旧脚本忽略 `accounts` 和 `account_id`；成员保留最后一次派生的启停状态和到期日，配额为 0，不会被误停，但统一配额不再生效。
- 面板和 Agent 0.3.0-preview.10 不认识统一用户：在旧面板上单独修改成员协议用户的到期或启停，会在下一次脚本结算时被统一用户的设置覆盖。0.3.0-preview.11 起，面板会拒绝这类修改，并通过平台用户同步（见 `platform/docs/platform-users.md`）。

## 测试

**隔离测试（本机，函数级加载）**：

- 新增 `tests/accounts.sh`，共 15 组：创建与校验；新建成员（旧单用户实例补 default，凭据独立）；跨协议合计超额停用全部成员，重复结算不重建；重建失败后记录待重建并重试；调高配额恢复，计数回落只计一次；月度切换清零恢复，手动停用跨周期保持；到期停用与延长恢复；修改重置日保留用量；归入保留凭据和用量，并清除旧的面板计费字段，防止重复归属；平台停用标记和解除关联；单个或全部重置凭据，实例级凭据同步；Snell 独立实例成员；外部删除协议用户后自动移除成员；批量归并候选；删除统一用户保留成员；全局月重置跳过成员；菜单辅助函数；交互菜单冒烟（新建、添加协议、改配额、分享、批量归并、删除）。已加入 GitHub Actions。
- `tests/singbox-stats-query.sh` 补了统一用户结算的桩。
- 其余 `tests/*.sh` 全部通过（`singbox-stats-live.sh` 需要真实统计核心，未运行）。`bash -n` 通过；`platform` 的 unittest 93 项通过（跳过 2 项），其中新增的一项验证统一用户用量字段不影响配置版本号。
- 注意：本机是 Bash 3.2，`set -e` 不会让 `[[ ]]` 失败的测试退出。`tests/accounts.sh` 已改为每条断言显式失败；其他旧测试在本机的通过结果以 GitHub Actions（Bash 5）为准。脚本主体要求 Bash 4.1+，本机无法运行完整的 CLI 进程，菜单只做了函数级的冒烟测试。

**真实验收**：未执行。没有在任何 VPS 上运行，也没有操作生产节点。

## 写接口（3.7.4-preview.4）

`bash vless-server.sh --api` 新增 `account_apply`，供 Agent 写入统一用户。它和交互菜单共用同一套 `db_account_*` 函数，修改同步字段时同样会更新 `rev` 和 `mtime`。

```json
{"api_version":1,"request_id":"<任务ID>","action":"account_apply","params":{"ops":[
  {"op":"create","account_id":"<uuid>","platform_user_id":"<uuid>","fields":{"name":"alice","quota":0,"expire_date":"","reset_day":1,"note":""},
   "members":[{"target":{"core":"xray","protocol":"vless","port":443},"name":"alice"}]},
  {"op":"update","account_id":"<uuid>","base_rev":7,"fields":{"expire_date":"2026-12-31"}},
  {"op":"block","account_id":"<uuid>","platform_block":"quota"}
]}}
```

- **操作：** `create`、`update`（需要 `base_rev`）、`link`、`unlink`、`block`（`""` 或 `quota`）、`member_add`（新建协议账号）、`member_claim`（归入，`count_existing` 默认 true）、`member_remove`（`release`/`delete`）、`reset_credentials`（可指定 `member`）、`reset_usage`、`delete`（`release`/`delete`）。一个请求最多 200 项；字段按白名单逐项校验，所有值都通过 jq 传参，不会拼进 shell。
- **事务：** 获取 `$CFG/.txn.lock` → 幂等记录 `$CFG/api-results/<request_id>.json`（先写 running 意图）→ 备份数据库和核心配置、Snell 配置到 `$CFG/api-backups/<request_id>/`（0700）→ 预检（账户是否存在、`base_rev`、协议范围）→ 逐项执行，重建延后 → 每个核心统一重建一次 → 写入结果。任一步失败就恢复备份，结果为 `apply_failed`，带 `rolled_back:true` 和脚本的中文提示（不含凭据）；如果统一重建已经执行过，恢复后会再重建一次。恢复也失败时结果为 `unknown`。
- **乐观并发：** `base_rev` 与当前 `rev` 不一致时整体拒绝，不写入，返回 `rev_conflict` 和当前 `rev`。
- **幂等：** 同一个 `request_id` 内容相同，直接返回已存结果，不会再执行；内容不同返回 `request_id_conflict`；遗留的 running 意图返回 `unknown`，`replay_allowed:false`。`result` 用 `params.request_id` 查询结果，只读。记录和备份保留 30 天。
- **Snell 限制：** 新建 Snell 成员需要新建独立实例和计数规则，删除成员要卸载实例，这两件事无法在事务里回滚，所以接口拒绝 `member_add` 和带 `delete` 的移除，返回 `unsupported_snell_operation`。平台应先用现有的安装任务创建实例，再用 `member_claim` 归入；移除时用 `release`。
- **能力声明：** `capabilities` 保持 `stage=read_only_foundation` 和 `write_actions=[]`（协议级写入仍然关闭，现有 Agent 的接口检查不受影响），另外用 `accounts_api.version=1` 声明统一用户接口和支持的操作。
- **inventory：** 新增 `accounts`（除凭据外的全部字段；成员附带当前累计计数、启停和停用原因）和用户的 `account_id`。

### 测试（preview.4）

**隔离测试：** 新增 `tests/accounts-api.sh`，共 9 组：能力声明；创建（带成员和平台关联，每个核心只重建一次，inventory 不含凭据）；幂等重放与 request_id 冲突；过期 `base_rev` 被拒且不写入；格式校验（未知字段、日期、非 uuid、未知操作、空列表、换行、超过 200 项）；多项操作中途失败时整体回滚数据库和配置；统一重建失败时回滚，恢复也失败时为 unknown 且不重放；中断遗留的意图；归入、平台停用与解除、凭据重置、Snell 限制、删除保留成员。已加入 GitHub Actions。在 Bash 4.1+ 且有 flock 的环境（CI）下使用真实的事务锁，macOS Bash 3.2 下锁被替换为空操作。原有的 `tests/platform-api.sh` 和其余脚本测试、面板 unittest 93 项都通过（跳过 2 项）。

**真实验收：** 未执行。

## 用户管理方式：以脚本或以平台为准（3.7.4-preview.5）

每台节点只认一方，保存在 `meta.user_authority`（缺省 `script`）。

- **以脚本为准**：本机菜单照常管理用户；Vaio 面板对用户只读，不能写入（接口返回 `authority_script`）。
- **以平台为准**：用户只由 Vaio 平台写入。本机菜单的新增、删除、配额、重置流量、启停、到期、路由、Snell 用户设置、TG 绑定和统一用户写操作全部禁用，提示去面板操作；仍可查看用户、查看分享链接、看流量。
- **切换**：用户管理 → `m` 用户管理方式，或由面板下发 `set_authority`。
  - 切到平台：列出各实例将删除的用户数，输入 `CLEAR` 确认。删除受管实例（Xray/Sing-box 的多用户协议、SS、已迁移的 Snell 用户实例）的全部用户（`users` 置为空数组），把行级 `uuid`/`password`/`psk` 换成同类新随机值（SS2022 按加密方式生成 16/32 字节密钥），删除统一用户及待重建记录；TG 绑定、用户路由、配额和到期都存在用户上，随用户一起删除。协议实例保留，现有客户端全部失效。未迁移的独立协议（旧 Snell、ShadowTLS、Naive）不受影响。菜单路径会先备份数据库和配置，重建失败就恢复并重建；接口路径走 `account_apply` 的事务。
  - 切回脚本：去掉统一用户的平台关联，用户和凭据保留。
- `--api`：`set_authority` 必须单独成请求；`accounts_api.version` 为 2；能力声明和 inventory 带 `user_authority`。

### 测试（preview.5）
**隔离测试**：
- 新增 `tests/user-authority.sh`，共 6 组：缺省模式与各实例的用户数统计（不含独立 Snell）；重建失败时回滚数据库和配置；接管后清空用户、凭据、统一用户、TG/路由数据，检查新凭据格式，独立协议不变；平台模式下 8 个菜单写操作全部被拒绝；切回保留用户并解除关联；菜单必须输入 CLEAR 才接管，切回需要确认。
- `tests/accounts-api.sh` 新增一组：脚本模式拒绝写入；混合请求被拒绝；接管清空凭据；切回。
- `tests/accounts-cli.sh` 在 CI 中用真实进程验证切换、脚本模式拒绝和接管清空。
- 其余脚本测试和面板 unittest 119 项通过（跳过 2 项）。

**真实验收**：未执行。

## 全协议用户能力与 SS2022 多用户（3.7.4-preview.6）

- **能力表**：`_proto_user_mode` / `_proto_user_stats`。多用户（一个实例多个用户，按用户统计）：VLESS 全系列、VMess-WS、Trojan、Trojan-WS、SS、SS2022、Hysteria2、TUIC、AnyTLS。一用户一实例：SOCKS（按入站统计）、Snell v4/v5/v6、Snell+ShadowTLS、Snell v5+ShadowTLS、SS2022+ShadowTLS（按端口统计）。不支持：Naive，以及免认证的 SOCKS。本版本已接入的一用户一实例只有迁移后的 Snell；SOCKS 和 ShadowTLS 组合的多实例适配在 preview.7 提供。能力声明 `user_modes` 和 inventory 每个实例的 `user_mode`、`user_stats`、`user_available` 会上报给面板；`accounts_api.version` 为 3。
- **安装提示**：选择协议后，一用户一实例会提示统计方式；Naive 会提示「该协议不支持用户管理」；尚未接入的协议也会提示。
- **SS2022 多用户**：实例 `password` 作为服务端密钥，每个用户的 `uuid` 作为用户密钥。Xray 生成 `clients`（按 email 统计），Sing-box 和共享渲染器生成 `users`。users 缺失，或只有一个用户且密钥等于实例密钥的旧实例，保持原来的单密码格式，现有客户端不受影响。多用户的分享链接密码为 `服务端密钥:用户密钥`。共享渲染器里的 SS 传统版也支持多用户。
- **一用户一实例的分配**：`member_add` 指定 Snell 实例时，空实例会分配给该用户（重新生成 PSK、写入唯一用户、按状态启停）；已有用户返回 `instance_occupied`。菜单里不指定端口时仍然新建实例。
- **成员连接信息**：新增只读的 `--api account_share {target, name, host?}`，返回 `connection`。可以指定连接地址，此时不探测公网地址和国家；不写任何记录。
- **平台模式安装空实例**：以平台为准时，脚本安装的多用户协议实例不生成 default 用户。

### 测试（preview.6）
**隔离测试**：
- 新增 `tests/protocol-users.sh`，共 6 组：22 个协议的模式和统计方式；免认证 SOCKS；能力 JSON；安装提示。Xray 的 SS2022 用真实的入站生成函数验证多用户和旧格式兼容。共享渲染器覆盖 SS2022 多用户与旧格式、SS 传统版多用户、全部停用时的占位用户。另外覆盖 Snell 分配（新凭据、已占用拒绝）、连接信息（指定地址、未知用户、不支持的协议、地址注入）、平台模式空实例。
- 其余脚本测试和面板 unittest 131 项通过（跳过 2 项）。
- Sing-box 的 SS2022 多用户生成器（`generate_singbox_config`）依赖太多，没有单独的函数级测试；它与共享渲染器的格式一致，渲染器已有测试。

**真实验收**：未执行。

## SOCKS 与 ShadowTLS 组合按一用户一实例接入（3.7.4-preview.7）

- **SOCKS**：每个端口实例最多一个用户，用户名就是用户名，密码就是用户凭据。唯一用户停用、到期或超额时，入站换成随机账号，原连接失效。流量按 Xray 入站标签（`socks-<端口>`）统计：生成的 Xray 配置在 policy 中开启了 `statsInboundUplink/Downlink`，流量同步时计入该实例的唯一用户。旧实例（没有 users）沿用原来的实例账号；把旧实例归入统一用户时，原用户名和密码保留为这个用户。
- **ShadowTLS 组合**（Snell+ShadowTLS、Snell v5+ShadowTLS、SS2022+ShadowTLS）：保持「每台节点一份」，实例归一个用户。分配时更换后端凭据（Snell PSK 或 SS2022 密钥，按加密方式生成 16/32 字节）和 ShadowTLS 握手密码，重写后端配置和前端服务。唯一用户停用、到期或超额时，停止并禁用前后端两个服务；恢复后重新启动。「启动全部服务」也会跳过停用的实例。流量用 nft 按前端端口计数（复用 Snell 的计数表，计数器 ID 由协议名派生），按代际累计。旧实例（没有 users）保持常开。
- **分享链接**：ShadowTLS 组合按 Surge 格式输出（包含握手密码和 SNI）；SOCKS 沿用原有格式。
- **能力表**：SOCKS（免认证除外）与三种 ShadowTLS 组合标为已接入；`member_add` 只能分配到空实例，否则返回 `instance_occupied`。

### 测试（preview.7）
**隔离测试**：新增 `tests/single-user-instances.sh`，共 6 组：
- SOCKS 账号生成（旧格式、有效用户、停用/到期/超额换成随机账号），用真实的 Xray 入站生成函数验证，并检查入站统计策略。
- SOCKS 归入旧实例时保留原账号，分配空实例会更换账号，已占用的实例被拒绝，入站流量计入用户。
- ShadowTLS 分配：重写后端凭据、更换握手密码、重写服务、重启前后端。
- 停用统一用户时停止服务，恢复时重新启动。
- nft 端口计数的累计与代际。
- ShadowTLS 和 SOCKS 成员的分享链接。

其余脚本测试和面板 unittest 151 项通过（跳过 2 项）。没有在真实的 shadow-tls、snell-server、Xray 和 nftables 环境中运行；systemd/OpenRC 服务启停只验证了调用顺序。

**真实验收**：未执行。

## 以平台为准时 TG 通知交由平台管理（3.7.4-preview.8）

- 节点切到「以平台为准」后，管理员 TG 通知、每日报告、用户查询机器人和绑定码都由 Vaio 面板「通知配置」统一管理，本机不再使用自己的 TG 配置。
- 清理（`_tg_platform_cleanup`，幂等）：`telegram.json` 写回默认值（不含 Token、Chat ID，开关关闭，权限 600）、删除 `db.json` 中旧版的 `.telegram`、移除 `tg-user-bot` 轮询 cron。触发点：`set_authority` 切到平台时；已是平台模式的节点在每次流量同步、`--tg-bot-poll` 和打开 TG 菜单时。
- 平台模式下 `tg_send_message`、`send_tg_message`、`tg_send_bound_user_message`、`check_daily_report` 直接返回，即使配置文件被手动写回也不发送；「TG 通知配置」菜单只显示「TG 通知由 Vaio 平台管理」。
- 以脚本为准的节点行为不变，脚本仍可独立使用 TG 通知。切回脚本不会恢复已清除的 TG 配置，需要重新设置。
- 测试：新增 `tests/tg-platform.sh`（脚本模式保留配置与发送、平台模式清除配置/旧数据库配置/cron 且权限 600、幂等、平台模式不发送任何消息、机器人轮询清理后退出、菜单只读、切换与流量同步调用清理）；其余脚本测试通过（`singbox-stats-live.sh` 需要真实统计核心，`accounts-cli.sh` 仅在 CI 以 root 运行）。

## 端口转发：Realm 与 nftables 统一管理（3.7.4-preview.9）

- 规则模型：`{id, backend: realm|nftables, remark, transport, listen_host, listen_port, remote_host, remote_port, enabled}`。Realm 规则存于 `realm/rules.json`，旧规则首次读取时补 12 位十六进制 `id`。nftables 启用中的规则以 nft.sh 兼容的 `/etc/nftables.d/port-forward.conf`（`table ip port_forward`）为准，id 为 `nft-<监听端口>`；备注和停用的规则存于 `realm/rules.json`。用 nft.sh 新增或删除的规则会直接反映出来。
- nftables 约束（与 nft.sh 一致）：固定 TCP+UDP、监听所有地址、目标必须是 IPv4。启用时按需安装 nftables、在 `/etc/nftables.conf` 加入 `include "/etc/nftables.d/*.conf"`、开机启用 nftables 服务、写入 `/etc/sysctl.d/99-nft-forward.conf` 开启 IPv4 转发。生成的配置先声明再删除表，重复加载不叠加；回程改用 `masquerade`，不再需要本机 IP。
- 端口冲突：同一服务器上监听端口（同协议）不得与其他转发规则重复，也不得与代理实例端口重复（停用的规则也计入）。
- 流量：Realm 沿用 iptables `VLESS_REALM_COUNTERS` 的入站计数；nftables 用独立表 `inet vless_forward_stats` 在 forward 链按目标和回程计数，每次应用时重建，流量同步时只在规则集合变化（含 nft.sh 改动）时重建。重启后清零。
- 菜单「端口转发」：新建（选择 Realm 或 nftables）、查看（含状态与流量）、修改、启用/停用、删除、状态/日志；原 nft.sh 工具入口保留在上一级（诊断、BBR 等）。
- 接口：`--api forward_apply`，`params.ops` 只含一个操作（add / update / delete / enable / disable，非新增须带 `id` 与 `base`）。`base` 是平台看到的规则，与节点当前规则不同则返回 `rule_changed`，不覆盖脚本或 nft.sh 的修改。事务共用 `.txn.lock`、`api-results` 幂等记录，备份 `rules.json`、Realm 配置和 nftables 配置；应用失败（如 nftables 校验失败、Realm 未能保持运行）恢复备份并重载，恢复失败为 unknown 且不重放。inventory 增加 `forwards`（规则 + `status` running/stopped/disabled + `bytes`）与 `forward_status`；capabilities 增加 `forward_api.version=1`。
- 测试：新增 `tests/port-forward.sh`（旧规则补 id 与 nft.sh 规则识别、新增 Realm、各项校验与端口冲突、nftables 写入保留 nft.sh 规则并开启转发与计数、修改拒绝过期快照且 id 规则、停用保留元数据与启用恢复、应用失败回滚、幂等重放与结果查询、删除最后 Realm 规则停止服务、删除 nft.sh 规则、流量汇总与按需重建、请求格式）。其余脚本测试通过（`singbox-stats-live.sh` 需要真实统计核心，`accounts-cli.sh` 仅在 CI 以 root 运行）。

## 已接管节点不能在本机切回（3.7.4-preview.10）

- 节点已注册 Vaio 节点程序（存在 `/etc/vaio-agent/config.json`，可用 `VAIO_AGENT_CONFIG` 覆盖路径）且为「以平台为准」时，「用户管理方式」菜单只提示由面板统一管理，不再提供切回「以脚本为准」。如需改回本机管理，需先在面板删除该服务器并卸载节点程序。未注册的节点行为不变；面板自身的 `set_authority` 接口不受影响。
- 测试：`tests/user-authority.sh` 新增已注册节点不能切回一项。
