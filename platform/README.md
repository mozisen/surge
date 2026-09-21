# Vaio Panel

已合并至 `mozisen/surge` 的 `platform/` 目录。来源及当前开发边界见 [合并说明](docs/monorepo.md)。合并不代表全协议写接口已完成；下列既有能力保持原边界。

基于 `vless` 的自托管多服务器管理平台。主服务器运行面板，节点安装 Python Agent 并主动通过 HTTPS 上线。

**v0.2.1 / 第二阶段第一批。** 增加节点设置、回收站、版本诊断与保留身份的升级流程。自动化测试和真实服务器验收分别记录在 [验证说明](docs/validation.md)，未验证的环境不视为通过。

## 当前能力

- 中文黑白控制台：节点总览、分组筛选、名称/分组/备注编辑、回收站、资源状态、协议实例、用户、任务记录和审计。
- 面板与节点版本诊断，维护模式下暂停派发任务；节点升级保留身份，面板升级备份数据库并检查服务健康。
- 管理员密码登录、服务端会话、CSRF 校验、登录限速；公网部署强制 HTTPS。
- 添加服务器、下载独立安装脚本、一次性注册凭据、自动上线、显式接管和身份撤销。
- 识别原脚本 `db.json` 的单对象/多端口格式；只上传白名单字段，不上传私钥、PSK 或 UUID。
- **Xray VLESS Reality、Hysteria2（无端口跳跃）、Snell v4/v5/v6**：安装、修改端口、按实例卸载、启停/重启对应服务。共享核心的启停影响其所有实例。
- 用户新增、启停、到期日期、删除及连接信息导出。Snell 一用户一端口，新增/删除用户通过新增/卸载实例完成。
- 任务串行执行、请求去重、Agent 持久化执行记录；结果不明确时标记“待核对”，不自动重放。
- 修改前保存节点本地配置备份；运行配置校验和服务启动失败后尝试恢复。
- 配额与流量继承原脚本；**配额首版只读**，流量是节点数据库中的最近同步值。新节点没有自动开启核心用户流量接口，不把缺失数据当作可用统计。

## 快捷安装（Debian / Ubuntu）

将域名解析到主服务器，放行 TCP 80/443，在 root 终端执行：

```sh
(f=$(mktemp) && trap 'rm -f "$f"' EXIT HUP INT TERM && curl -fsSL https://raw.githubusercontent.com/mozisen/surge/codex/platform-api/platform/scripts/install-panel.sh -o "$f" && sh "$f")
```

按提示输入域名、管理员账号和密码。安装器自动配置运行环境、后台服务、Nginx 与 HTTPS，无需手动准备 Docker。仅用于首次安装，不覆盖已有面板；申请证书失败会停止上线，保留文件供排错。

- 节点：面板「添加服务器」→「复制安装命令」→ 在节点 root 终端执行。无需手动传输脚本；没有 curl 时可下载脚本执行。
- 账号：右上角「账号设置」修改账号或密码，验证当前密码后保存，所有会话退出。
- 旧面板升级后账号默认为 `admin`，原密码不变。忘记密码时，在主服务器运行 `vaio-panel account` 重置。
- 主服务器命令：`vaio-panel status` 查看状态，`vaio-panel restart` 重启，`vaio-panel logs` 查看日志，`vaio-panel update` 升级。
- 节点命令：`vaio-agent status`、`vaio-agent logs`、`vaio-agent update`；旧节点在「节点设置」复制升级命令，无需重新注册。
- 节点仍支持 Debian/Ubuntu、Alpine、dnf 系统；脚本负责依赖与服务管理，后台的备份、校验、恢复机制保持完整。

快捷安装器经过脚本检查，尚未在全新 VPS 上完整验收；当前在线面板沿用现有部署升级。

## 容器部署（可选）

前提：Linux 主服务器、Docker Compose、一个解析到主服务器的域名，放行 TCP 80/443。

```sh
git clone --branch codex/platform-api https://github.com/mozisen/surge.git
cd surge/platform
cp .env.example .env
# 编辑 .env，将 VAIO_DOMAIN 改成自己的面板域名
docker compose build
docker compose run --rm panel python -m vaio init
docker compose up -d
```

打开 `https://你的面板域名` 登录。密码最少 12 位，通过终端交互输入，不写入 Git 或镜像。

1. 在面板添加服务器，设置名称和分组。
2. 复制生成的安装命令。
3. 在节点以 root 粘贴执行。凭据 30 分钟内有效，使用一次即失效；也可下载脚本执行。
4. 回到面板确认节点上线、检查协议列表，然后点击“确认接管”。
5. 执行协议管理任务，在任务记录查看结果；安装完自行放行云安全组/主机防火墙对应端口。

面板生成的安装脚本只用于指定节点。不要公开上传，安装后删除。Agent 不需要额外开放入站管理端口。

### 节点要求

- Python **3.9+**、Bash **4.1+**。
- 安装器覆盖 Debian/Ubuntu（apt）、Alpine（apk）和 dnf 系统，使用 systemd 或 OpenRC。
- 原脚本二进制安装器继续决定各协议的架构兼容性。首版建议先在 Debian/Ubuntu amd64/arm64 测试节点验收。
- 现有节点配置目录：`/etc/vless-reality`。已有脚本不会被替换。

### 不用容器的面板开发环境

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m vaio init
.venv/bin/python -m vaio serve
```

访问 `http://127.0.0.1:8080`。开发服务器仅绑定回环地址。公网使用 Gunicorn + TLS 反向代理，配置 `VAIO_PUBLIC_URL=https://panel.example.com` 和持久化 `VAIO_DATABASE`。

```sh
.venv/bin/gunicorn --bind 127.0.0.1:8080 --workers 2 --threads 4 'vaio.server:create_app()'
```

## 首版边界

- 其他协议、Sing-box 承载的 VLESS、带端口跳跃的 Hysteria2 为只读；不提供任意 Shell、自动核心升级、内核切换或批量操作。
- 旧版 Snell 多端口但没有独立实例 ID 的记录需先用原脚本迁移；拒绝猜测服务归属。
- 共享 Xray/Sing-box 核心的修改会重启整个核心，面板展示其影响范围。
- 不建议同时通过 SSH 菜单和面板修改同一节点。Agent 使用兼容的数据库锁，但原脚本并非所有操作都在完整事务内。
- 新增 Hysteria2 使用自签证书，导出包含 `insecure=1`；首版尚未提供 ACME 证书管理界面。
- 到期检查在 Agent 本地每分钟运行；面板离线不影响执行。停止 Agent 会停止这部分检查。原脚本已有配额任务继续运行。
- 备份覆盖数据库、目标运行配置和服务文件；安装下载的二进制、证书、系统依赖不自动卸载，避免误删共享资源。
- 首版展示任务步骤、失败原因和节点本地日志位置；不将可能含凭据的原始进程日志上传面板。
- 主面板 SQLite 支持单机部署，不提供高可用、多管理员、订阅聚合、历史监控或主动告警。

详细设计见 [架构与接口](docs/architecture.md)，运维及恢复见 [运维说明](docs/operations.md)。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check web/app.js
sh -n scripts/install-agent.sh
bash -n vendor/vless-server.sh
```

GitHub Actions 在 Python 3.9/3.12 执行回归，并构建容器镜像。真实节点验收清单见 [验证说明](docs/validation.md)。

## 源码与 Git

`vendor/vless-server.sh` 固定为原项目 3.7.2 快照，
