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
printf '面板域名（请先解析到本服务器）: '
read -r VAIO_DOMAIN </dev/tty
# Validate before using the domain in shell-generated configuration.
printf '%s' "$VAIO_DOMAIN" | grep -Eq '^([a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$' || {
  echo '域名格式无效，请输入不带 https:// 和路径的域名。'; exit 1;
}
[ ! -e /etc/nginx/sites-available/vaio-panel ] || { echo '已有同名 Nginx 配置，请先检查。'; exit 1; }
if command -v ss >/dev/null && ss -lntH | grep -Eq '[:.]18080[[:space:]]'; then
  echo '本机 18080 端口已被占用，请先检查现有服务。'; exit 1
fi
echo '正在安装运行环境…'
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv nginx certbot python3-certbot-nginx curl ca-certificates
# Do not take over an existing domain's virtual host.
if nginx -T 2>/dev/null | grep -F "server_name $VAIO_DOMAIN" >/dev/null; then
  echo '此域名已有 Nginx 站点，请使用一个未配置的面板域名。'; exit 1
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
SOURCE_REF=${VAIO_SOURCE_REF:-codex/platform-api}
printf '%s' "$SOURCE_REF" | grep -Eq '^[A-Za-z0-9._/-]+$' || { echo '源码版本格式无效'; exit 1; }
curl -fSL --max-time 180 "https://github.com/mozisen/surge/archive/$SOURCE_REF.tar.gz" -o "$WORK/panel.tar.gz"
mkdir "$WORK/source"
tar -xzf "$WORK/panel.tar.gz" -C "$WORK/source" --strip-components=1
id vaio-panel >/dev/null 2>&1 || useradd --system --home-dir /var/lib/vaio-panel --shell /usr/sbin/nologin vaio-panel
install -d -m 755 /opt/vaio-panel
[ -f "$WORK/source/platform/requirements.txt" ] || { echo '源码包缺少 platform 目录'; exit 1; }
cp -R "$WORK/source/platform/." /opt/vaio-panel/
python3 -m venv /opt/vaio-panel/.venv
/opt/vaio-panel/.venv/bin/pip install -q -r /opt/vaio-panel/requirements.txt
install -d -m 700 /etc/vaio-panel
install -d -m 700 -o vaio-panel -g vaio-panel /var/lib/vaio-panel
cat > /etc/vaio-panel/panel.env <<EOF
VAIO_DATABASE=/var/lib/vaio-panel/panel.sqlite
VAIO_PUBLIC_URL=https://$VAIO_DOMAIN
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
cat > /etc/nginx/sites-available/vaio-panel <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $VAIO_DOMAIN;
    client_max_body_size 1m;
    location / {
        proxy_pass http://127.0.0.1:18080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
ln -s /etc/nginx/sites-available/vaio-panel /etc/nginx/sites-enabled/vaio-panel
# Leave the backend stopped until HTTPS is ready.
nginx -t
systemctl reload nginx
if ! certbot --nginx -d "$VAIO_DOMAIN" --redirect --agree-tos --register-unsafely-without-email --non-interactive; then
  rm -f /etc/nginx/sites-enabled/vaio-panel
  nginx -t && systemctl reload nginx
  echo '证书申请失败，面板未启动。请检查域名解析和 TCP 80/443，配置 HTTPS 后再启动 vaio-panel。'; exit 1
fi
systemctl daemon-reload
systemctl enable --now vaio-panel
systemctl enable --now certbot.timer
curl --fail --retry 5 --retry-connrefused --retry-delay 1 --max-time 10 -sS http://127.0.0.1:18080/healthz >/dev/null
echo "安装完成：https://$VAIO_DOMAIN"
echo '常用管理：vaio-panel status / restart / logs / account'
