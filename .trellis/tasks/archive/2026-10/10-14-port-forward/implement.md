# 实施计划
1. 脚本：规则读取/规范化（Realm id、nft conf 解析与合并）、写入（Realm 重启、nft 生成与加载）、统计、菜单（新建选类型/修改/启停/删除）、`--api forward_apply` 与 inventory/capabilities；`tests/port-forward.sh`；版本 3.7.4-preview.9；vendor 同步。
2. 节点程序：script_api.forward、bridge forward_apply、快照 forwards 与清洗；unittest。
3. 面板：common 校验、接口、`forwardsPage`、导航；unittest 与 cjs。
4. 版本 0.3.0-preview.22；文档。
5. 全部测试、本地预览截图、分提交、推送、CI。
