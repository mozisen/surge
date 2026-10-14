# 设计

## 安装脚本（scripts/install-panel.sh）
- 读取域名；为空 → `curl -4 -fsS https://api.ipify.org`（失败再 `ip route get`）得到 IPv4，提示确认或手动输入。
- 读取端口：默认域名 443 / IP 8080；校验数字范围与 `ss` 未监听；域名模式额外要求 80 可用于申请证书。
- Nginx：IP 模式 `listen PORT default_server`（HTTP 反代 18080）；域名模式先建 80 端口 server 申请证书（`certbot certonly --nginx`），再写最终配置：`listen PORT ssl`（证书路径 /etc/letsencrypt/live/<domain>），80 端口保留 ACME 与跳转到 https://domain:PORT。
- panel.env：VAIO_PUBLIC_URL、VAIO_ALLOW_HTTP（IP 模式）。
- 注册 root 辅助：`/opt/vaio-panel/scripts/panel-address.py`，由 systemd path 单元 `vaio-panel-address.path` 监听 `/var/lib/vaio-panel/address-request.json` 触发 `vaio-panel-address.service`（root, oneshot）。

## 面板
- create_app：`VAIO_ALLOW_HTTP=1` 时允许 http 公网地址；secure cookie 跟随 scheme。
- `GET/POST /api/panel-address`：读取当前地址与申请状态；提交 {domain, port} 写请求文件（面板用户可写目录），辅助服务处理后写 `address-status.json`；`POST /api/panel-address/close-legacy` 写关闭旧地址请求。
- 节点切换：地址切换成功后（面板以新地址启动），为每个已接管在线节点排队 `agent_set_url` 任务（params {url}）；节点验证 `GET <url>/healthz` 通过 TLS 校验后写入配置并在下一轮使用；结果回写。设置页显示「已切换 N / 总 M」。

## 辅助程序（root）
- 校验域名格式与端口；生成 Nginx 配置（保留旧 HTTP server 作为 legacy）；`certbot certonly --nginx -d`；成功后写最终配置、`nginx -t`、更新 panel.env（VAIO_PUBLIC_URL=https://…，VAIO_ALLOW_HTTP 保留到关闭旧地址），重启面板；失败恢复 Nginx 配置与 panel.env，写失败原因。
- 关闭旧地址：删除 legacy server，去掉 VAIO_ALLOW_HTTP，重启面板。

## 节点程序
- valid_url(url, allow_http)：配置中 `allow_http: true` 时接受 http。
- 新任务 `agent_set_url`：仅接受 https；先验证新地址可达（正常证书校验），写 config.json（原子替换），清除 allow_http。

## 卸载
- `scripts/vaio-panel uninstall [--yes] [--keep-backup PATH]`、`scripts/vaio-agent uninstall [--yes]`；可通过环境变量覆盖根路径用于测试。
