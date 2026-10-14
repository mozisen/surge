# Vaio Panel

自托管的多服务器代理管理面板。主服务器运行面板，节点安装 Vaio 节点程序后主动通过 HTTPS 上线；面板统一管理服务器、协议实例、用户、流量、中转与端口转发。

**当前版本：1.0.0（正式版）**。更新记录见 [CHANGELOG](CHANGELOG.md)。

## 功能

- **服务器管理**：添加服务器、一次性注册命令、接管后统一由平台管理用户；节点设置、回收站、资源历史曲线、一键升级节点程序。
- **节点管理**：集中查看所有服务器的协议实例，按服务器、协议、状态和用户模式筛选；单页安装协议（可选择服务器，支持 VLESS Reality、Hysteria2、Trojan、AnyTLS、SS、SS2022、Snell v4/v5/v6 等）。
- **中转管理**：用户 → 一层或多层中转服务器（Realm / nftables）→ 落地协议，自动建立端口转发并导出经中转的连接；也支持只转发端口的出口机。
- **端口转发**：查看和管理所有服务器的 Realm 与 nftables 转发规则，与节点脚本配置双向同步，显示状态与流量。
- **用户管理**：平台用户跨服务器统一管理到期、配额与月度重置，一个用户可关联多个协议，导出连接信息。
- **流量统计**：按服务器与用户汇总流量。
- **通知配置**：Telegram 管理员通知、每日报告、用户查询机器人与平台用户绑定码。
- **备份恢复、任务记录、操作审计**：每日自动备份；节点任务串行执行、结果不明不重放；管理操作留痕。
- 中文黑白简约界面，适配桌面与手机。

## 安装面板（Debian / Ubuntu）

将域名解析到主服务器，放行 TCP 80/443，在 root 终端执行：

```sh
(f=$(mktemp) && trap 'rm -f "$f"' EXIT HUP INT TERM && curl -fsSL https://raw.githubusercontent.com/mozisen/vaio-panel/main/scripts/install-panel.sh -o "$f" && sh "$f")
```

按提示输入域名、管理员账号和密码。安装器配置运行环境、后台服务、Nginx 与 HTTPS；只用于首次安装，不会覆盖已有面板。指定版本可在命令前加 `VAIO_SOURCE_REF=v1.0.0`。

## 升级面板

```sh
vaio-panel update              # 升级到 mozisen/vaio-panel 的 main
vaio-panel update --ref v1.0.0 # 升级到指定版本
```

升级前自动备份数据库，在新环境中运行测试，切换后检查服务健康，失败自动恢复旧版本。

从 0.3.x 预览版（来自 `mozisen/surge`）升级：旧版更新器只认 surge 仓库，请先执行 `vaio-panel update --ref codex/platform-3.7.4`（该分支已是 1.0.0）；升级到 1.0.0 后，之后的 `vaio-panel update` 默认使用本仓库。

主服务器命令：`vaio-panel status`、`restart`、`logs`、`account`（重置登录信息）、`update`、`backup`、`verify-backup`、`restore`。

## 接入节点

1. 面板「服务器管理」→「添加服务器」，复制安装命令。
2. 在节点以 root 执行（凭据 30 分钟内有效、只能用一次）。
3. 节点上线后在服务器详情页「确认接管」；接管后用户统一由平台管理。

节点要求：Python 3.9+、Bash 4.1+；支持 Debian/Ubuntu（apt）、Alpine（apk）与 dnf 系统，systemd 或 OpenRC。节点程序内置节点脚本副本（`vendor/vless-server.sh`），配置目录 `/etc/vless-reality`。节点命令：`vaio-agent status`、`vaio-agent logs`、`vaio-agent update`；也可在面板一键升级。

## 容器部署（可选）

```sh
git clone https://github.com/mozisen/vaio-panel.git
cd vaio-panel
cp .env.example .env   # 将 VAIO_DOMAIN 改为面板域名
docker compose build
docker compose run --rm panel python -m vaio init
docker compose up -d
```

## 开发与测试

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m vaio init
.venv/bin/python -m vaio serve            # http://127.0.0.1:8080
.venv/bin/python -m unittest discover -s tests -v
node --check web/app.js && node tests/install-form.cjs && node tests/traffic-display.cjs && node tests/platform-users.cjs
```

本仓库是 [mozisen/surge](https://github.com/mozisen/surge) 中 `platform/` 目录的正式发布版；节点脚本与面板在 surge 仓库一起开发，正式版本同步发布到这里。设计与运维文档见 [docs](docs/)。
