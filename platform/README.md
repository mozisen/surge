# Vaio Panel

自托管的多服务器代理管理面板。主服务器运行面板，节点安装 Vaio 节点程序后主动通过 HTTPS 上线；面板统一管理服务器、协议实例、用户、流量、中转与端口转发。

**当前版本：1.3.2（正式版）**。更新记录见 [CHANGELOG](CHANGELOG.md)。

## 功能

- **服务器管理**：添加服务器、一次性注册命令、接管后统一由平台管理用户；节点设置、回收站、资源历史曲线；列表显示节点程序当前与最新版本，可一键更新全部节点程序。
- **节点管理**：集中查看所有服务器的协议实例，按服务器、协议、状态和用户模式筛选；单页安装协议（可选择服务器，支持 VLESS Reality、Hysteria2、Trojan、AnyTLS、SS、SS2022、Snell v4/v5/v6 等）。
- **中转管理**：用户 → 一层或多层中转服务器（Realm / nftables）→ 落地协议，自动建立端口转发并导出经中转的连接；也支持只转发端口的出口机。
- **端口转发**：查看和管理所有服务器的 Realm 与 nftables 转发规则，与节点脚本配置双向同步，显示状态与流量。
- **用户管理**：平台用户跨服务器统一管理到期、配额与月度重置，一个用户可关联多个协议，导出连接信息。
- **用户自助**：新建用户时设置登录密码，用户可登录「我的账号」查看用量、到期、协议与中转线路的连接信息，并自助绑定 Telegram 机器人；只能看到自己的内容。
- **流量统计**：按服务器与用户汇总流量；节点程序每分钟同步一次用户用量。
- **通知配置**：Telegram 管理员通知、每日报告、用户查询机器人与平台用户绑定码。
- **备份恢复（系统设置）、任务记录、操作审计**：每日自动备份；节点任务串行执行、结果不明不重放；管理操作留痕。
- 中文黑白简约界面，适配桌面与手机。

## 安装面板（Debian / Ubuntu）

将域名解析到主服务器，放行 TCP 80/443，在 root 终端执行：

```sh
(f=$(mktemp) && trap 'rm -f "$f"' EXIT HUP INT TERM && curl -fsSL https://raw.githubusercontent.com/mozisen/vaio-panel/main/scripts/install-panel.sh -o "$f" && sh "$f")
```

按提示依次输入：

- **域名**：已解析到本服务器的域名，安装器自动申请 Let's Encrypt 证书并启用 HTTPS（需放行 TCP 80）。**没有域名直接回车**，使用本机公网 IP 以 HTTP 访问（登录密码与节点通信不加密，建议之后绑定域名）。
- **面板端口**：访问面板的端口，有域名时默认 443，用 IP 时默认 8080，可自定义（如 8443）。请在云安全组和防火墙放行。
- 管理员账号和密码。

安装完成后显示面板地址，例如 `https://panel.example.com:8443` 或 `http://1.2.3.4:8080`。只用于首次安装，不会覆盖已有面板。指定版本可在命令前加 `VAIO_SOURCE_REF=v1.2.0`。

### 绑定或更换域名

在面板左下角「系统设置 → 面板地址」中填写域名和 HTTPS 端口，面板会自动申请证书、配置 Nginx 并切换到 HTTPS（失败自动恢复原配置），各节点会自动改用新地址。原来的 IP 地址（或旧域名）在点「关闭旧地址」前继续可用；节点都切换完成后再关闭。也可在服务器以 root 执行：

```sh
vaio-panel domain panel.example.com 8443
```

## 升级面板

面板打开时在后台检查本仓库的正式版本（缓存 1 小时，打开「面板更新」时立即重新检查），有新版本时左下角「面板更新」会提示，点开即可在面板中直接更新（需要没有未完成的节点任务）。也可以在服务器以 root 执行：

```sh
vaio-panel update              # 升级到 mozisen/vaio-panel 的 main
vaio-panel update --ref v1.2.0 # 升级到指定版本
```

升级前自动备份数据库，在新环境中运行测试，切换后检查服务健康，失败自动恢复旧版本。

从 0.3.x 预览版（来自 `mozisen/surge`）升级：旧版更新器只认 surge 仓库，请先执行 `vaio-panel update --ref codex/platform-3.7.4`（该分支已是 1.0.0）；升级到 1.0.0 后，之后的 `vaio-panel update` 默认使用本仓库。

主服务器命令：`vaio-panel status`、`restart`、`logs`、`account`（重置登录信息）、`update`、`domain`（绑定域名）、`backup`、`verify-backup`、`restore`、`uninstall`。

## 接入节点

1. 面板「服务器管理」→「添加服务器」，复制安装命令。
2. 在节点以 root 执行（凭据 30 分钟内有效、只能用一次）。
3. 节点上线后在服务器详情页「确认接管」；接管后用户统一由平台管理。

节点要求：Python 3.9+、Bash 4.1+；支持 Debian/Ubuntu（apt）、Alpine（apk）与 dnf 系统，systemd 或 OpenRC。节点程序内置节点脚本副本（`vendor/vless-server.sh`），配置目录 `/etc/vless-reality`。节点命令：`vaio-agent status`、`vaio-agent logs`、`vaio-agent update`；也可在面板一键升级。

## 卸载

卸载面板（在主服务器以 root 执行）：

```sh
vaio-panel uninstall
```

删除面板服务、程序、配置、数据库与面板备份、Nginx 站点和系统用户 `vaio-panel`；证书、其他网站和各节点的代理与用户不受影响。需要保留数据可先导出：`vaio-panel uninstall --backup /root/vaio-panel-backup.tar.gz`。确认提示需输入 `UNINSTALL`，脚本中可加 `--yes` 跳过。

卸载节点程序（在节点以 root 执行）：

```sh
vaio-agent uninstall
```

只删除节点程序（服务、`/opt/vaio-agent`、节点身份与日志）；节点脚本、代理配置和用户保留，代理照常运行，原来由节点程序执行的定时任务改回 `/usr/local/bin/vless-server.sh`。

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
