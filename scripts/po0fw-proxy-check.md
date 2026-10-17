# po0fw：Surge 指定代理节点连通性检测

不需要 Ping API、ICMP 探针、Python 服务或额外服务器。

Surge 的 JavaScript API 支持 `$httpClient.head({url, policy, timeout}, callback)`。本模块在 po0 API **加白成功后**通过用户指定的代理节点发送 HTTP HEAD 测试请求，失败则重新请求加白（最多达到配置的次数）。

## 如何在 Surge 中设置

安装或更新 [po0fw.sgmodule](https://raw.githubusercontent.com/mozisen/surge/refs/heads/main/scripts/po0fw.sgmodule)，打开 **模块 → 编辑参数**：

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `tokens` | `pgnfw_xxx@0` | po0 token；支持多 token，使用英文逗号分隔；保留固定槽位功能 |
| `test_proxy` | `台湾家宽-SS` | **与 Surge 配置的代理节点名称完全一致**；留空则关闭测试与额外加白重试 |
| `retry_count` | `3` | 代理测试失败后额外请求加白的次数，允许 0 到 5，默认 3 |
| `test_url` | `http://cp.cloudflare.com/generate_204` | HTTP HEAD 测试目标；默认地址应返回 HTTP 204。自定义地址以 HTTP 2xx/3xx 为成功标准 |

> 推荐填写 **具体代理节点名称**，不要使用可自动选择其他节点的策略组，否则策略组可能切换到其他节点，导致测试成功但原节点依然不可用。`DIRECT` 和 `REJECT` 不允许用作 `test_proxy`。

## 执行规则

1. 原有 `network-changed`、`engine-started` 和每 10 分钟 cron 触发不变；网络变化后原有 1.5 秒稳定延迟不变。
2. 每个 token 发起 po0 白名单 POST 请求；po0 API 始终走 `DIRECT`，不会走测试代理。
3. API 返回确认本机出口 IP 已加白后，使用 `policy: test_proxy` 发出 HTTP HEAD 请求（单次超时 5 秒）。
4. 如果默认 URL 返回 HTTP 204，测试通过，结束当前 token 流程并输出耗时。
5. 网络错误、超时或响应不符合条件时，等待 1.8 秒并再次 POST 加白，然后再检测。
6. 最多执行 `1 + retry_count` 次加白请求（例如 `retry_count=3`，最多 4 轮；po0 API 本身的底层网络重试另计）。
7. 达到限制仍不可用则报告失败；下次 cron 或网络事件触发时再次验证。
8. 如果 po0 API 加白失败，则不进行代理连接测试。

## 简洁日志（当前默认）

日志只保留**触发原因、加白结果、当前出口、白名单占用、代理状态/延迟**；不再逐行输出底层 HTTP 请求、URL、完整白名单、UTC 时间及运行 ID（Surge 已自行显示时间和会话 ID）。

正常运行（示例，非实际 IP）：

```text
[po0] ✅ 网络变化｜加白成功 · 出口 198.51.100.8 · 白名单 4/5 · Po0-HK 133ms
```

节点暂时不可用，重试后恢复：

```text
[po0] ⚠️ Po0-HK 连接失败，准备第 2/4 次加白
[po0] ✅ 网络变化｜加白成功 · 出口 198.51.100.8 · 白名单 4/5 · Po0-HK 142ms · 加白 2 次
```

失败达到次数上限：

```text
[po0] ⚠️ Po0-HK 连接失败，准备第 2/4 次加白
[po0] ⚠️ Po0-HK 连接失败，准备第 3/4 次加白
[po0] ⚠️ Po0-HK 连接失败，准备第 4/4 次加白
[po0] ❌ 网络变化｜代理检测失败（加白成功） · 出口 198.51.100.8 · 白名单 4/5 · Po0-HK 不可用（timeout） · 加白 4 次
```

### 编辑参数

- `log_level=simple`（默认）：只显示简洁结果和必要的重试信息
- `log_level=debug`：需要排障时显示每轮底层 HTTP 状态码、请求耗时、代理 HEAD 检测、错误原因和白名单详细信息，但不重复 Surge 自带的时间和会话 ID
- `log_level=off`：关闭脚本控制台日志，不影响加白与代理测试

**向后兼容：** 之前模块里已经保存的 `detail`、`summary` 参数会自动按 `simple` 模式显示，不需要手动改参数。

### 日志保存位置

Surge「脚本详情 → 日志」查看本次运行控制台输出；支持 `$surge.logbook()` 的版本，状态变化或失败时还会写入一条简洁的日志簿记录。正常且状态没有变化时不会重复追加日志簿记录。

每次运行的详细结构化摘要仍保存在本机 `$persistentStore`，键 `po0_fw_run_history`，最多保留最近 20 次。这个记录不是自动可见的页面，主要供后续排障脚本读取。

日志中不打印完整 Token；出口 IP 和节点名称仍会显示，分享截图时请注意。

## 注意事项

- **这是 HTTP 连通性检测，不是 ICMP Ping**；它检测该 Surge 策略是否能正常完成 HTTP HEAD 请求，比只检测服务器 IP 更接近实际代理用途。
- 节点名必须精确匹配。没有匹配策略时，Surge 会报告请求错误；脚本将显示失败而不会切换成默认代理来测试。
- 代理可用但测试网址不可访问、被阻断或不返回预期状态，也会判为失败。遇到这种情况可以修改 `test_url`，默认 URL 严格要求返回 204。
- 如果 po0 API 重复加白但返回的公网出口 IP 未发生变化，那么持续重试未必能修复问题。
- `test_proxy` 留空时，模块按原方式自动加白，不做额外检测。
- 脚本执行超时为 90 秒。极端慢速网络或 API 失败重试可能导致本轮超时，后续由定时触发继续执行。
- 不要把真实 token 写进 GitHub 文件，保持 token 只在 Surge 的模块编辑参数中。
