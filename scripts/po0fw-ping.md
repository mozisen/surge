# po0 防火墙自动加白：可选 ICMP Ping 验证

## 为什么需要 Ping 探针？

Surge 脚本的 `$httpClient` 仅支持 HTTP(S)，不能直接发送 ICMP Echo Request。模块中的 **Ping 结果是真实 ICMP**，由配套的 Python 探针执行；向探针发起的 HTTP GET 仅负责取回 Ping 检测结果，**不是用 HTTP 连通性替代 Ping**。

> ⚠️ 重要：探针必须与要验证的设备使用相同的网络出口。若 Surge 在 iPhone 蜂窝网络上运行，而探针部署在家庭 NAS 或远程 VPS，Ping 结果不代表手机蜂窝网络能否连通。Surge iOS 的纯 JavaScript 模块无法在本机直接实现 ICMP Ping，此情况暂不能实现可靠的自动校验。不要将异地 Ping 的成功结果当成手机已成功加白。

## 模块参数

通过 Surge → 模块 → 编辑参数设置：

- `tokens`：原有 po0 token，多个用英文逗号分隔，支持 `@0` 固定槽位
- `ping_ip`：需要 Ping 的 IPv4，例如 `203.0.113.10`（示例地址）。**留空则关闭 Ping 检测和额外重试，原有加白逻辑不变**
- `retry_count`：Ping 失败后额外进行几次加白，范围 0～5，默认 3（加上首次请求，总请求次数最多 4 次）
- `ping_api`：ICMP 探针 HTTP 接口，默认 `http://127.0.0.1:18765/ping`；这个默认地址**仅适用于同一台 Mac 上运行的探针**
- `ping_key`：可选的探针访问密钥，和服务端 `--key` 保持一致

## 启动 ICMP 探针

在 **Surge Mac 所在机器**上安装 Python 3（无需第三方 Python 依赖），运行：

```sh
python3 scripts/po0fw-icmp-probe.py --target 203.0.113.10
```

把示例 IP 换成目标 IP，须与模块的 `ping_ip` 相同。程序监听 `127.0.0.1:18765`，不会默认暴露到公网。

验证本机 Ping 服务（仅查询，不加白）：

```sh
curl --noproxy '*' 'http://127.0.0.1:18765/ping?ip=203.0.113.10'
```

返回如 `{"ip":"203.0.113.10","ok":true}` 表示 Ping 收到回应；`ok:false` 表示本次 ICMP 测试未收到回应。

如果需要在另一台同出口的 LAN 设备上运行，可使用 `--host 0.0.0.0 --key YOUR_STRONG_KEY`，并把模块的 `ping_api` 指向内网该设备的地址、填好 `ping_key`。**必须使用防火墙限制来源**，不要直接将 HTTP 服务暴露到公网；跨网络使用需加 TLS，且须验证同出口条件。

## 执行行为

1. 原有 cron（10 分钟）、`network-changed`、`engine-started` 触发保持不变
2. 首先 POST po0 加白；仅当返回本机 IP 已加白时进行 Ping
3. Ping 成功：完成本轮
4. Ping 返回 `ok:false`：等待 1.8 秒，再次调用加白 API，重复至 Ping 成功或达到 `retry_count`
5. 探针连接失败、未授权、返回非 JSON 或出错：报告错误、**不把探针故障当成目标不通**，不盲目重复加白
6. 达到上限后停止本轮重试，未来 cron/网络事件仍会重新验证

原有 API 网络层重试机制保持不变，`retry_count` 仅控制 **Ping 不通后的额外加白请求**。

## 注意事项

- 某些服务器禁用 ICMP Echo Reply，即使它们的真实服务可以正常访问，Ping 也可能一直失败。
- IP /24 的加白由 po0 服务端处理；相同公网出口重复 POST 未必能改变白名单。
- 不要在公开 GitHub 仓库填写真实的 po0 token 或 Ping 密钥；它们应仅保存在模块编辑参数中。
- 使用 iPhone 蜂窝网络时，如果没有**真正从 iPhone 发出的 ICMP**检测能力，不要把异地 Ping 作为加白成功依据。
