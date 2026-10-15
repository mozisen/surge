# 实施步骤

1. 脚本：统计循环与统计配置检查加入 ss2022；新增 shell 测试；版本 preview.15；同步 vendor、SHA、README。
2. 节点程序：`ss_user_stats`、`mutable` 放宽、`traffic_state`、SS2022 多用户导出。
3. 测试：`tests/test_shadowsocks.py` 扩展（多用户端口修改、用户增删与停用渲染、统计状态、导出链接、到期执行）；更新原有断言（多用户不可写 → 可写）。
4. 面板版本 1.5.0、CHANGELOG、README、merge 文档；全部测试、提交、推送、CI。
5. 发布前询问；真实验收需授权。
