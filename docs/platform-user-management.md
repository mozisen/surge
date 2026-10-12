# 统一用户管理（脚本 3.7.4-preview.4 / 面板与 Agent 0.3.0-preview.11）

分支 `codex/platform-3.7.4`。只推送预览分支，不更新 main，不创建 GitHub Release。

## 目标
一个用户可以使用多个协议，时限和流量统一管理。脚本、节点程序和面板三层同步更新：

- **脚本（可独立运行）**：节点级「统一用户」挂多个协议用户，到期、合计配额、每月重置日和启停统一设置，由脚本自己执行。不需要 Agent 和面板。
- **面板**：「平台用户」在多台节点上各关联一个统一用户，跨节点合计流量由面板判断；与节点双向同步，同一字段两边都改时以后改的为准。
- **Agent**：上报统一用户，通过脚本的事务接口 `--api account_apply` 执行面板下发的同步。

## 版本与文档
| 层 | 版本 | 文档 |
|---|---|---|
| 脚本统一用户 | 3.7.4-preview.3 | `docs/script-accounts.md` |
| 脚本写接口 `account_apply` | 3.7.4-preview.4 | `docs/script-accounts.md`「写接口」 |
| Agent 同步 | 0.3.0-preview.11 | `platform/docs/platform-users.md`「Agent」 |
| 面板平台用户 | 0.3.0-preview.11 | `platform/docs/platform-users.md`「面板」 |

规划、决策和设计见 `.trellis/tasks/archive/2026-10/10-12-platform-user-management/`（`prd.md`、`design.md`、`research/current-state.md`）。

## 关键决策
- 面板判断，节点兜底：跨节点配额由面板汇总后下发 `block`；到期日作为同步字段下发，节点离线时也按本地日期停用；节点按本机用量兜底（本机超额一定意味着总量超额）。
- 超额停用该用户在所有节点上的统一用户，到重置日、调高配额或重置用量后自动恢复；手动停用不会自动恢复。
- 现有协议用户手动「归入」统一用户，节点统一用户手动「认领」为平台用户，都保留凭据和已用流量。
- 每个协议的凭据独立；重置凭据可以针对单个协议成员，也可以一次重置全部。
- 只有宣告 `accounts_version=1` 的新版节点能关联；离线节点显示待同步，上线后补发；结果未知的任务不重放，等人工核对。
- Snell 和 SS 一用户一端口：先安装实例，再归入。

## 测试结果
**隔离测试（本机与 GitHub Actions）**：
- 脚本：`tests/accounts.sh`（15 组）、`tests/accounts-api.sh`（9 组），其余脚本测试全部通过（`singbox-stats-live.sh` 需要真实统计核心，未运行）。本机 Bash 3.2 下 `[[ ]]` 失败不会触发 `set -e`，新测试的断言都改为显式失败；最终结果以 CI 的 Bash 5 为准。
- 完整 CLI 进程：`tests/accounts-cli.sh` 只在 CI 中以 root 运行真实脚本的 `--api`：能力声明、事务、幂等、文件权限、真实 flock 下的并发、版本冲突、inventory 不含凭据，以及 Agent 的 `ScriptAPI` 直接调用 vendor 脚本。本机没有 root 和 Bash 4，会自动跳过。
- Agent：`tests/test_platform_users_agent.py`（15 项）。
- 面板：`tests/test_platform_users_panel.py`（11 项，模拟节点）、`tests/platform-users.cjs`（界面）。全部 unittest 119 项通过（跳过 2 项），`node --check`、`install-form.cjs`、`traffic-display.cjs`、`platform-users.cjs` 通过。
- 本地预览截图（1280 / 375 宽度）检查了新页面和对话框。

**未覆盖的部分**：真实 Xray / Sing-box / Snell 核心下的重建与回滚（CI 中没有安装核心，相关路径用替身测试）；Agent 进程与面板之间的长时间运行；多台真实节点之间的时钟偏差。

**真实验收**：未执行。没有部署到测试面板 vps.town，没有升级或连接任何真实节点；「香港维多利亚」等生产节点未做任何操作。真实验收需要另行授权，建议先在测试面板和一台测试节点上进行：升级节点脚本到 3.7.4-preview.4、升级面板和 Agent 到 0.3.0-preview.11，然后验证新建与认领、双向修改、跨节点超额停用与恢复、离线补发。
