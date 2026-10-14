#!/bin/sh
# Debian/Ubuntu installer. Run as root from a downloaded file.
set -eu
umask 022
[ "$(id -u)" = 0 ] || { echo '请使用 root 运行'; exit 1; }
command -v apt-get >/dev/null && command -v systemctl >/dev/null || {
  echo '此快捷安装器支持 Debian/Ubuntu + systemd；其他系统请使用容器部署。'; exit 1;
}
[ ! -e /opt/vaio-panel ] || {
  echo '检测到已有面板，已停止安装以保留数据。升级请运行 vaio-panel update，修改登录信息请运行 vaio-panel account。'; exit 1;
}
printf '面板域名（需先解析到本服务器；没有域名直接回车，使用本机 IP 以 HTTP 访问）: '
read -r VAIO_DOMAIN </dev/tty
if [ -n "$VAIO_DOMAIN" ]; then
  # Validate before using the domain in generated configuration.
  printf '%s' "$VAIO_DOMAIN" | grep -Eq '^([a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$' || {
    echo '域名格式无效，请输入不带 https:// 和路径的域名。'; exit 1;
  }
  DEFAULT_PORT=443
else
  VAIO_IP=$(curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)
  [ -n "$VAIO_IP" ] || VAIO_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
  printf '本机 IP [%s]: ' "$VAIO_IP"
  read -r INPUT_IP </dev/tty
  [ -z "$INPUT_IP" ] || VAIO_IP=$INPUT_IP
  printf '%s' "$VAIO_IP" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' || { echo 'IP 地址无效。'; exit 1; }
  DEFAULT_PORT=8080
fi
printf '面板端口 [%s]: ' "$DEFAULT_PORT"
read -r VAIO_PORT </dev/tty
[ -n "$VAIO_PORT" ] || VAIO_PORT=$DEFAULT_PORT
case "$VAIO_PORT" in ''|*[!0-9]*) echo '端口必须是数字。'; exit 1 ;; esac
[ "$VAIO_PORT" -ge 1 ] && [ "$VAIO_PORT" -le 65535 ] || { echo '端口必须在 1–65535 之间。'; exit 1; }
[ "$VAIO_PORT" != 18080 ] || { echo '18080 为面板后台端口，请换一个。'; exit 1; }
[ ! -e /etc/nginx/sites-available/vaio-panel ] || { echo '已有同名 Nginx 配置，请先检查。'; exit 1; }
if command -v ss >/dev/null && ss -lntH | grep -Eq '[:.]18080[[:space:]]'; then
  echo '本机 18080 端口已被占用，请先检查现有服务。'; exit 1
fi
if [ -z "$VAIO_DOMAIN" ]; then
  echo '注意：未绑定域名时面板以 HTTP 访问，登录密码与节点通信不加密；可之后在面板「面板地址」中绑定域名切换为 HTTPS。'
fi
echo '正在安装运行环境…'
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv nginx certbot python3-certbot-nginx curl ca-certificates jq openssl
# Do not take over an existing domain's virtual host.
if [ -n "$VAIO_DOMAIN" ] && nginx -T 2>/dev/null | grep -F "server_name $VAIO_DOMAIN" >/dev/null; then
  echo '此域名已有 Nginx 站点，请使用一个未配置的面板域名。'; exit 1
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
# 正式版来自 mozisen/vaio-panel（仓库根即面板）；预览版可用 VAIO_SOURCE_REPO=mozisen/surge（platform/ 目录）。
SOURCE_REPO=${VAIO_SOURCE_REPO:-mozisen/vaio-panel}
SOURCE_REF=${VAIO_SOURCE_REF:-main}
case "$SOURCE_REPO" in mozisen/vaio-panel|mozisen/surge) ;; *) echo '源码仓库只能是 mozisen/vaio-panel 或 mozisen/surge'; exit 1 ;; esac
printf '%s' "$SOURCE_REF" | grep -Eq '^[A-Za-z0-9._/-]+$' || { echo '源码版本格式无效'; exit 1; }
curl -fSL --max-time 180 "https://github.com/$SOURCE_REPO/archive/$SOURCE_REF.tar.gz" -o "$WORK/panel.tar.gz"
mkdir "$WORK/source"
tar -xzf "$WORK/panel.tar.gz" -C "$WORK/source" --strip-components=1
id vaio-panel >/dev/null 2>&1 || useradd --system --home-dir /var/lib/vaio-panel --shell /usr/sbin/nologin vaio-panel
install -d -m 755 /opt/vaio-panel
if [ -f "$WORK/source/requirements.txt" ]; then SOURCE_DIR="$WORK/source"
elif [ -f "$WORK/source/platform/requirements.txt" ]; then SOURCE_DIR="$WORK/source/platform"
else echo '源码包缺少面板文件（requirements.txt）'; exit 1; fi
cp -R "$SOURCE_DIR/." /opt/vaio-panel/
python3 -m venv /opt/vaio-panel/.venv
/opt/vaio-panel/.venv/bin/pip install -q -r /opt/vaio-panel/requirements.txt
install -d -m 700 /etc/vaio-panel
install -d -m 700 -o vaio-panel -g vaio-panel /var/lib/vaio-panel
cat > /etc/vaio-panel/panel.env <<EOF
VAIO_DATABASE=/var/lib/vaio-panel/panel.sqlite
PYTHONDONTWRITEBYTECODE=1
EOF
chmod 600 /etc/vaio-panel/panel.env
cd /opt/vaio-panel
VAIO_DATABASE=/var/lib/vaio-panel/panel.sqlite .venv/bin/python -m vaio init </dev/tty
chown -R vaio-panel:vaio-panel /var/lib/vaio-panel
cat > /etc/systemd/system/vaio-panel.service <<'EOF'
[Unit]
Description=Vaio Panel
After=network.target
[Service]
User=vaio-panel
Group=vaio-panel
WorkingDirectory=/opt/vaio-panel
EnvironmentFile=/etc/vaio-panel/panel.env
ExecStart=/opt/vaio-panel/.venv/bin/gunicorn --bind 127.0.0.1:18080 --workers 2 --threads 4 vaio.server:create_app()
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/vaio-panel
[Install]
WantedBy=multi-user.target
EOF
install -m 755 /opt/vaio-panel/scripts/vaio-panel /usr/local/bin/vaio-panel
# Root helper for changing the panel address from the panel (bind a domain, close the old HTTP address).
cat > /etc/systemd/system/vaio-panel-address.service <<'EOF'
[Unit]
Description=Vaio Panel address change
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/vaio-panel/scripts/panel-address.py apply
EOF
cat > /etc/systemd/system/vaio-panel-address.path <<'EOF'
[Unit]
Description=Vaio Panel address change requests
[Path]
PathExists=/var/lib/vaio-panel/address-request.json
[Install]
WantedBy=multi-user.target
EOF
# Root helper for updating the panel from the panel (the update itself is update-panel.py with backup and rollback).
cat > /etc/systemd/system/vaio-panel-update.service <<'EOF'
[Unit]
Description=Vaio Panel update from the panel
[Service]
Type=oneshot
TimeoutStartSec=1800
ExecStart=/usr/bin/python3 /opt/vaio-panel/scripts/update-panel.py --from-request /var/lib/vaio-panel/panel-update-request.json
EOF
cat > /etc/systemd/system/vaio-panel-update.path <<'EOF'
[Unit]
Description=Vaio Panel update requests
[Path]
PathExists=/var/lib/vaio-panel/panel-update-request.json
[Install]
WantedBy=multi-user.target
EOF
# Nginx site, certificate (domain) and VAIO_PUBLIC_URL; restores its files on failure.
if [ -n "$VAIO_DOMAIN" ]; then
  python3 /opt/vaio-panel/scripts/panel-address.py install --domain "$VAIO_DOMAIN" --port "$VAIO_PORT" || {
    echo '证书申请或 Nginx 配置失败，面板未启动。请检查域名解析、TCP 80 与面板端口，修正后重新安装。'; exit 1; }
else
  python3 /opt/vaio-panel/scripts/panel-address.py install --ip "$VAIO_IP" --port "$VAIO_PORT" || {
    echo 'Nginx 配置失败，面板未启动。'; exit 1; }
fi
PANEL_URL=$(python3 /opt/vaio-panel/scripts/panel-address.py url)
systemctl daemon-reload
systemctl enable --now vaio-panel
systemctl enable --now vaio-panel-address.path vaio-panel-update.path
[ -z "$VAIO_DOMAIN" ] || systemctl enable --now certbot.timer
curl --fail --retry 5 --retry-connrefused --retry-delay 1 --max-time 10 -sS http://127.0.0.1:18080/healthz >/dev/null
echo "安装完成：$PANEL_URL"
[ -n "$VAIO_DOMAIN" ] || echo '请在云安全组与防火墙放行面板端口；建议之后在面板「面板地址」中绑定域名。'
echo '常用管理：vaio-panel status / restart / logs / account / domain / uninstall'
