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

## 详细运行日志（新增）

模块新增 `log_level` 编辑参数，支持：

- `detail`（默认）：记录每一步，包括触发源、网络类型、Token 序号和槽位、po0 API 的底层 HTTP 尝试及重试、HTTP 状态码、请求耗时、白名单数量与出口 IP、代理策略/检测 URL、HEAD 状态、耗时、失败原因、重新加白轮次、停止原因以及本次运行汇总。
- `summary`：只记录开始、每个 Token 最终结果、异常与运行汇总，不输出普通成功步骤。
- `off`：不输出脚本控制台日志；设备通知和重要状态变化/失败的 Logbook 记录仍照常运行。

例如编辑模块：

```ini
test_proxy = 台湾家宽-SS
retry_count = 3
log_level = detail
```

示例日志（示意值，非真实线上执行）：

```text
[po0fw][...Z][run-id][INFO][启动] trigger=network-changed iface=cellular tokens=1 proxy=台湾家宽-SS ... log_level=detail
[po0fw][...Z][run-id][DETAIL][网络] network-changed，等待 1500ms 路由稳定后加白
[po0fw][...Z][run-id][DETAIL][加白/开始] token#1 第 1/4 轮；POST /api/firewall/[REDACTED]/add；slot=0；加白 API 策略=DIRECT
[po0fw][...Z][run-id][DETAIL][API/HTTP] token#1 底层 POST 尝试 1/3 policy=DIRECT timeout=15
[po0fw][...Z][run-id][DETAIL][API/HTTP] token#1 底层尝试 1 结果 HTTP=200 duration=160ms
[po0fw][...Z][run-id][DETAIL][加白/成功] token#1 轮次=1 HTTP=200 duration=165ms currentIp=198.51.100.8 ... count=1/5
[po0fw][...Z][run-id][DETAIL][代理/开始] token#1 第 1 次 HEAD policy=台湾家宽-SS url=http://cp.cloudflare.com/generate_204 timeout=5s
[po0fw][...Z][run-id][WARN][代理/结果] token#1 policy=台湾家宽-SS result=FAIL HTTP=- latency=5000ms reason=timeout
[po0fw][...Z][run-id][WARN][流程/重试] token#1 节点仍不可用，1800ms 后重新请求 po0 加白；下一轮 2/4
[po0fw][...Z][run-id][DETAIL][加白/开始] token#1 第 2/4 轮 ...
[po0fw][...Z][run-id][DETAIL][代理/结果] token#1 policy=台湾家宽-SS result=PASS HTTP=204 latency=240ms
[po0fw][...Z][run-id][INFO][Token/小结] token#1 status=PASS ... add_rounds=2 proxy_http=204 proxy_ms=240
[po0fw][...Z][run-id][INFO][本轮汇总] trigger=network-changed passed=1/1 duration=...ms ... notify=true
```

日志每行包含 **UTC 时间、单轮运行 ID、等级及执行阶段**。多个 Token 并行时，可通过 `token#1`、`token#2` 区分。

### 在哪里查看？

Surge 的 `console.log()` 会写入对应的 **脚本日志文件**。你可以从 Surge 的脚本日志或 **Logbook（日志簿）** 查看脚本执行记录；具体入口取决于你的 Surge 版本。支持 `$surge.logbook()` 的版本还会在 **状态发生变化或执行失败** 时写入一条简要汇总，正常且无变化的定时执行不会反复往 Logbook 添加摘要。

此外，每次运行的结构化摘要保存在 Surge 本地 `$persistentStore` 中，key 为 `po0_fw_run_history`，**最多保留最近 20 次**，不需要外部服务。该存储并非单独的文件或自动显示的可视化面板，后续可由其他脚本读取。

隐私：日志使用 `token#序号` 和 `[REDACTED]` 标记，不写入完整 po0 Token；测试 URL 的查询参数不输出。日志会包含你的出口公网 IP、代理名称与错误原因，分享截图时仍应留意隐私。

## 注意事项

- **这是 HTTP 连通性检测，不是 ICMP Ping**；它检测该 Surge 策略是否能正常完成 HTTP HEAD 请求，比只检测服务器 IP 更接近实际代理用途。
- 节点名必须精确匹配。没有匹配策略时，Surge 会报告请求错误；脚本将显示失败而不会切换成默认代理来测试。
- 代理可用但测试网址不可访问、被阻断或不返回预期状态，也会判为失败。遇到这种情况可以修改 `test_url`，默认 URL 严格要求返回 204。
- 如果 po0 API 重复加白但返回的公网出口 IP 未发生变化，那么持续重试未必能修复问题。
- `test_proxy` 留空时，模块按原方式自动加白，不做额外检测。
- 脚本执行超时为 90 秒。极端慢速网络或 API 失败重试可能导致本轮超时，后续由定时触发继续执行。
- 不要把真实 token 写进 GitHub 文件，保持 token 只在 Surge 的模块编辑参数中。
