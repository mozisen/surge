# SS 与 SS2022 安装

面板和 Agent 版本 0.3.0-preview.5 新增 Sing-box 的 SS 与 SS2022。升级节点 Agent 后，进入节点详情的新增协议选择；旧 Agent 不显示未声明的安装能力。

- SS：aes-256-gcm、aes-128-gcm、chacha20-ietf-poly1305。
- SS2022：2022-blake3-aes-128-gcm、2022-blake3-aes-256-gcm；分别使用 16、32 字节的标准 Base64 密钥，可自动生成。
- 无需域名或证书，支持 TCP/UDP。
- 每个实例一个用户，更多用户请新增端口；支持编辑用户、停用、到期、重置凭据、导出连接及卸载实例。
- 暂不支持用户流量统计和流量配额。旧脚本创建的 SS 实例保持只读。

共享脚本渲染器同步升级至 3.7.3-preview.4；Agent 使用随包固定版本，不覆盖节点已有主脚本。

配置字段依据 [Sing-box Shadowsocks 文档](https://sing-box.sagernet.org/configuration/inbound/shadowsocks/)。测试中的真实内核检查仅验证配置可被接受，不代表已完成真实客户端连通测试。
