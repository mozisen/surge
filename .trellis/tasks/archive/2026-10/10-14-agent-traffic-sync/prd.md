# 节点程序定时同步用户流量

## 问题
平台用户用量一直为 0。用量来自节点脚本 `--sync-traffic` 写入 db.json 的 `used`，但脚本只在启用自身 TG 通知/用户机器人时安装同步 cron；平台接管 TG 后节点从未同步（vps.town 只读检查确认：victoria 无 sync-traffic cron、无同步日志，各节点 traffic_status=unavailable、used=0）。

## 要求
- 节点程序每分钟（例行维护，与节点任务串行）运行内置脚本 `--sync-traffic`，校验脚本完整性，输出写 `/etc/vless-reality/traffic-sync.log`（超过 1 MiB 清空），超时 120 秒。
- 同步失败只记日志，不影响到期/配额检查；同步后下一次上报立即刷新快照。
- 与脚本 cron 并存安全（脚本自带同步锁与 db.json flock）。
- 版本 1.2.1；节点需一键更新后生效。

## 验收
- 单元测试覆盖调用参数、失败、超时、完整性、日志上限、维护顺序与失败隔离。
- 真实验收：节点更新到 1.2.1 后，平台用户用量在约 1 分钟内随实际流量增长。
