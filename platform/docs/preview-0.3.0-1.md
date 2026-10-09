# 0.3.0-preview.1

测试分支：`codex/platform-api`（mozisen/surge）。不创建 GitHub Release，不改变最新正式版本。

包含统一仓库平台/Agent、9 种已声明协议与内核组合的管理适配、凭据重置、配置预校验和事务回滚保护。详见 `all-protocol-management.md`，未实现的全协议与关联资源写入仍不开放。

发布前验证：59 项平台 Python 隔离测试，12 套根脚本回归，前端 Node 语法、Shell 语法及 diff 检查。核心真实握手、Docker/OpenRC 和浏览器视觉回归不属于此次已通过项。

已有旧独立仓库面板不能直接用旧升级器下载此单仓库包。需使用本提交的 `scripts/update-panel.py`，固定 Git 提交 SHA 执行升级；升级器会先运行测试、备份数据库与配置，再切换程序并验证健康，失败恢复旧程序。面板升级后在节点运行 `sudo vaio-agent update`，由现有面板下载校验 Agent 并保留身份及协议数据。

新安装测试面板可下载本分支的 `platform/scripts/install-panel.sh`，设置 `VAIO_SOURCE_REF` 为固定提交 SHA 后执行。不要在已有安装上重复安装或重新注册节点。

这是受限测试版：原脚本全量重建配置与 Agent 独立证书/用户策略的双向同步尚未完成。测试期间不要混用 CLI 与平台改写同一实例；此次升级只更新管理程序，不主动改动代理核心、协议、用户或流量数据。

## 2026-09-21 部署验证

用户确认升级目标后，通过 termark 部署固定提交 `f766d00a36481ae8656f207fcf474c66bce628b6`：

- vps.town 面板：0.2.1 → 0.3.0-preview.1；服务器上 59 项测试通过，`/healthz` 返回正常与预期版本。
- 面板备份：`/var/backups/vaio-panel/1789977813410332311`。
- ovh-vps-1 Agent：0.2.1 → 0.3.0-preview.1；旧程序：`/opt/vaio-agent-backup-1789977868442776027`。
- Agent 身份文件及 Xray/Sing-box 配置 SHA-256 升级前后一致；原有代理服务均保持 running。
- 面板收到新版心跳，维护模式为 0，9 种能力、7 个实例上报正常；没有 queued/running/unknown 任务。
- 未执行安装/卸载代理或修改用户的真实写入测试，未验证客户端握手。升级与心跳正常不等同于全部协议功能验收。

已接入本面板的其他测试节点可使用 `sudo vaio-agent update` 升级；本次仅操作上述两台，不自动更新其他机器。
