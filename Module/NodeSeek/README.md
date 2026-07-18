# NodeSeek 自动签到（Surge）

参考 Rabbit-Spec 的 SMZDM 模块结构制作，支持自动获取 Cookie、刷新 NodeSeek refract 签名、每日自动签到和结果通知。

## 安装链接

```
https://raw.githubusercontent.com/mozisen/surge/main/Module/NodeSeek/nodeseek.sgmodule
```

## 使用方法

1. 在 Surge 中开启 MITM、脚本和重写，并安装、信任 Surge 证书。
2. 安装上面的模块链接。
3. 使用 iPhone Safari 打开 https://www.nodeseek.com/，登录并通过 Cloudflare 验证。
4. 登录后刷新任意 NodeSeek 页面，即可捕获 Cookie；仅在首次保存或 Cookie 变化时通知。
5. 收到“Cookie 获取成功”通知后，手动运行一次 `NodeSeek_每日签到` 测试。
6. 默认每天 00:05 自动执行，时间按 Surge 所在设备时区计算。

Cookie 和 User-Agent 仅保存在 Surge 本机，不会上传到 GitHub。若出现 403，请保持同一网络，用 Safari 重新通过验证并进入个人主页更新 Cookie。
