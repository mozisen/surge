# 统一升级预览：脚本 3.7.3-preview.2 / 平台 0.3.0-preview.2

目标：正式验收后合并 main，让 3.7.2 用户通过原脚本更新入口原地升级；平台为可选接入能力，不注册则不向面板上传数据。本次只推送 codex/platform-api，不创建 Release，不改变 main 的 3.7.2。

本轮将已支持的共享核心入站渲染放入独立脚本 `_platform_render_inbound`，Agent 直接调用经过 SHA-256 校验的固定快照中同一函数，不再维护第二份 Python 协议生成规则。CLI 为 panel_managed 实例使用同一渲染器；未接管实例保留原路径。无需安装 Agent 也能运行新脚本。

范围：VLESS Reality、Trojan 的 Xray/Sing-box 组合，以及 Sing-box Hysteria2、AnyTLS。Snell 保持已有独立实例机制。保留独立证书、用户凭据、禁用/到期/配额状态和稳定入站 tag；防止 CLI 重新生成时合并不同端口用户或复活默认凭据。平台修改端口后，后续 CLI 重建仍按稳定 tag 定位原入站。

升级方式只替换程序文件，并备份旧文件与配置，不重建数据库、不强制迁移旧用户、不替换代理核心。测试节点先备份系统脚本与 /etc/vless-reality，再原子替换已校验脚本；平台和 Agent 使用自带备份/健康检查升级流程。原有快捷命令路径保持不变。

本地验收：62 项平台回归（新增共享渲染一致性、禁用/过期用户、固定快照一致性测试），12 套脚本回归、Shell/Node 语法和 diff 检查。尚不代表全协议生产兼容完成：剩余协议、CLI 全流程与平台并发操作的事务统一、所有传输参数编辑及客户端握手仍待验收；测试时避免同时通过两端修改同一节点。不得将这版作为已完成全部 3.7.2 升级验收的正式版。

## 部署记录（2026-09-21）

- 部署提交：`4c31b1e7bddf2c22c744e94f2f346400e4d2d28e`。
- vps.town 面板升级至 0.3.0-preview.2，备份 `/var/backups/vaio-panel/1789980663456547664`；服务器运行 62 项测试，61 项通过，1 项因部署包无根脚本而跳过（该快照一致性项本地已通过）。HTTPS 健康接口正常。
- ovh-vps-1 Agent 升级至 0.3.0-preview.2，旧程序 `/opt/vaio-agent-backup-1789980747696578038`。
- 同节点系统脚本由 3.7.3-preview.1 升级为 3.7.3-preview.2，旧脚本及配置备份 `/var/backups/vless-preview2.rkjve3`；未运行安装菜单或更换代理核心。
- 节点身份及 Xray/Sing-box 配置摘要不变，服务保持 active。面板收到正常心跳、7 个实例及新脚本 API 版本，维护模式关闭，无待处理任务。
- 使用临时配置在实际 Xray（2 实例）与 Sing-box（1 实例）上验证共享渲染结果，核心校验均退出 0；未替换运行文件，未做客户端握手或真实用户变更。实际测试节点此前已是预览版，不能以此次部署代替从 3.7.2 正式版起步的完整升级验收。

独立测试节点可下载固定脚本再运行（会进入原脚本交互界面，不自动接入平台）：

```sh
curl -fL https://raw.githubusercontent.com/mozisen/surge/4c31b1e7bddf2c22c744e94f2f346400e4d2d28e/vless-server.sh -o vless-preview.sh
sudo bash vless-preview.sh
```

已有测试 Agent 在面板升级后运行 `sudo vaio-agent update`，不重新注册。
