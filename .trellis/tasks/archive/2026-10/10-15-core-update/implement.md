# 实施步骤

1. common：`validate_core_task`、动作名。
2. 节点程序：runtime 增加捕获输出的脚本函数调用与 `core_versions()` / `core_latest()`；`watch_cores` 线程与快照字段；bridge 新任务 `core_update` 的执行与回滚。
3. 面板：单台与批量接口、跳过原因、任务摘要。
4. 前端：服务器详情内核区、一键更新内核对话框、任务记录显示。
5. 测试：`tests/test_core_update.py`（节点端流程用模拟 runtime；面板接口）；cjs 增加内核区与批量对话框。
6. 预览截图；版本 1.4.0、CHANGELOG、README；全部测试、提交、推送、CI。
7. 发布前询问用户；真实验收需授权。

验证：`python -m unittest discover -s tests`、三个 cjs、`node --check web/app.js`。
