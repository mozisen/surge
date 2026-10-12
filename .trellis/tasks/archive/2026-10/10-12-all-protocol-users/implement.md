# 执行计划

按顺序实现 4 个子任务，每个单独提交、检查、推送。阶段 A（子任务 1、3、4 的多用户部分）可以先交付；阶段 B（子任务 2）工作量最大，单独验收。

## 子任务 1：脚本能力表与多用户（3.7.4-preview.6）
- [ ] `_proto_user_mode`、`_proto_user_stats`；capabilities `user_modes`、inventory `user_mode/user_stats`；`accounts_api.version=3`
- [ ] SS2022 多用户（Xray、Sing-box 生成器、分享链接、统计），单密码兼容
- [ ] `member_add` 的 single 分配语义（Snell 先接入）；`instance_occupied`
- [ ] `--api account_share`
- [ ] 安装菜单提示；平台模式安装空实例
- [ ] 测试：`tests/protocol-users.sh`（能力表全覆盖、SS2022 两核心生成与兼容、分配/占用、分享）

## 子任务 2：脚本一用户一实例适配（3.7.4-preview.7）
- [ ] 通用端口计数表（兼容 Snell 旧表）
- [ ] SOCKS 多实例 + 分配 + 入站统计 + 门控
- [ ] ShadowTLS 三种组合：每实例独立前后端服务 + 分配 + 端口计数 + 门控
- [ ] 显式迁移：现有单实例保留为第一个实例
- [ ] 测试：`tests/single-user-instances.sh`（每种协议：分配、到期/超额停服务、恢复、计数、移除、迁移）

## 子任务 3：Agent（0.3.0-preview.13）
- [ ] `share` 回退到脚本 `account_share`；平台模式安装空实例；快照字段
- [ ] 测试

## 子任务 4：面板（0.3.0-preview.13）
- [ ] 成员选择按模式；分配实例；安装时选择用户（编排）；模式与统计标注；`none` 提示
- [ ] 测试（unittest + cjs）、预览截图、文档

## 检查
同前（脚本测试、unittest、node 测试），推送后看 GitHub Actions。不部署、不操作节点。
