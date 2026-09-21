# 统一项目入口

- 根目录 `vless-server.sh`：服务器交互管理及版本化接口。
- `platform/vaio`、`platform/web`：主面板后端和界面。
- `platform/agent`：节点接入、实例适配及事务执行。
- `platform/scripts`：面板/Agent 安装与升级。
- `platform/tests`：平台与节点隔离回归。

来源、迁移路径和当前边界见 [平台合并说明](../platform/docs/monorepo.md)。
协议全量写接口仍在开发中，合并后不会自动开放未实现的操作；不要将本地合并视为生产部署或正式发布。
