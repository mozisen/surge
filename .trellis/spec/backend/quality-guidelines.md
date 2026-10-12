# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

- `vless-server.sh` 开启了 `set -o pipefail`：不要用 `cmd | grep -q` 的返回值做判断（grep 提前退出时上游可能收到 SIGPIPE，返回非零），也不要把结果可能为空的 `grep -v` 放进需要成功的赋值。先把结果取到变量里再 `grep -q <<< "$var"`，过滤空行用 `sed '/^$/d'`。
- 不要在协议菜单里绕过统一用户直接修改成员协议用户的到期、配额、启停：这些字段由 `accounts` 派生，下一次结算会被覆盖。修改前调用 `_account_member_guard`。

---

## Required Patterns

<!-- Patterns that must always be used -->

- 改动根目录 `vless-server.sh` 后，同步 `platform/vendor/vless-server.sh`、`platform/agent/runtime.py` 的 `UPSTREAM_SHA` 和 `platform/vendor/README.md`，否则 `test_cli_compatibility` 会失败。
- 会随流量同步变化的数据库字段，必须加入 `platform/vaio/common.py:config_revision` 的 volatile 列表，否则面板写任务会因为「节点配置已变化」被拒绝。
- 统一用户的修改都走 `db_account_*` 函数，最后调用 `accounts_apply`：它负责结算、派生成员字段，并且只重建状态有变化的协议；重建失败的协议记入 `meta.accounts_reload_pending`，下次重试。

---

## Testing Requirements

<!-- What level of testing is expected -->

- 脚本测试按函数加载（awk 提取函数体），在 macOS 自带的 Bash 3.2 上也能运行。但 Bash 3.2 的 `set -e` **不会**因为 `[[ ]]` 失败而退出：新测试的每条断言都要写成 `[[ ... ]] || fail $LINENO`，并使用 `set -e -o pipefail`，与主脚本行为一致。本机通过不能代替 GitHub Actions（Bash 5）的结果。
- 读取标准输入的测试要用 `</dev/null` 运行，否则在非交互环境里会挂起（如 `singbox-stats-repair.sh`）。
- 新的脚本测试加入 `.github/workflows/platform.yml` 的脚本测试步骤。

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)
