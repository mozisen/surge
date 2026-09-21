# 平台管理接口：阶段一（未完成全协议写入）

依据平台任务「评估 VLESS 节点统一管理平台」及 Vaio 项目的 `docs/all-protocol-management.md` 接口提案实现。本次是只读接入基础，不代表全协议管理已经完成；不修改线上面板、Agent 或节点。

## 入口

`bash vless-server.sh --api` 从标准输入读取一个 JSON 对象（限制约 1 MiB），标准输出为一个 JSON 响应。不进入菜单，不初始化/迁移数据库，不下载、不启动服务。需要 jq、Bash 4.1+ 及 SHA-256 工具，读取数据库需要对应文件权限。不要将此入口直接暴露到公网。

```json
{"api_version":1,"request_id":"inventory-001","action":"inventory"}
```

响应包含 `api_version`、`request_id`、`script_version`、`status`、`code`、`data`。`status` 为 succeeded/failed/unknown。请求仅接受 api_version/request_id/action/expected_revision/target/params 顶层字段。

## 实际能力

- capabilities：返回注册协议/核心及操作能力。所有协议 `write_supported=false`，`write_actions=[]`，面板必须据此关闭写按钮。
- inventory：从同一数据库快照输出脱敏实例、用户和 revision。不输出 UUID、密码、PSK、私钥、TG Chat ID。standalone 与数据库存储核心分开标识。资源归属尚未验证，不可据此删除共享资源。
- plan：只做请求、版本和目标定位的前置检查；返回 revision_conflict/target_not_found/ambiguous_target 或 unsupported_operation。没有可执行变更计划，不声称已完成证书/NAT/端口冲突验证。
- result：当前无写入执行日志，返回 unknown/result_not_found/replay_allowed=false，绝不重新执行。
- 所有其他操作（包括 share）拒绝执行。不会把请求字符串解释为 Shell。

Snell 使用现有 snell_id。旧记录没有持久 ID 时返回 instance_id=null、identity_kind=legacy_locator，使用 `{core,protocol,port}` 精确定位，不伪造随端口变化的稳定 ID。正式写接口前必须实现显式迁移。

revision 当前是完整数据库快照的 SHA-256，流量变化也会使其变化，属于保守的只读前置版本。后续事务接口需要独立配置 revision、数据库锁内重新定位及检查。

## 下一阶段（尚未实现）

稳定 ID 显式迁移、写入互斥、持久执行意图与幂等结果、暂存配置校验、共享资源引用、失败/中断恢复，以及 install/update/delete/service/user/share 全协议适配器。必须按提案逐个覆盖双实例、故障注入、真实客户端与授权 VPS 验证后才开放相应 capability。

本次十二套回归测试、脚本语法及 diff 检查通过。验证为函数隔离测试；本机默认 Bash 3.2，不支持主脚本要求的 Bash 4.1+，未验证 Linux 完整 CLI 进程及真实节点/平台端到端联调。不发布正式版。
