# 私有开发预览

当前后端代码与环境位于 services/backend，启动目标为 src.main:app。模板 robot-rag-internal-dev.service 仅供现有开发预览；不替换已停用的 robot-rag.service，也不自动启用开机启动。

现有凭据由管理员环境提供，不把 /etc/robot-rag.env 复制进仓库。开发库配置保存在 services/backend/.env；RAG_SERVE_FRONTEND=1 时托管 services/frontend/dist。仅监听 127.0.0.1:8120，不能绕过公开认证条件直接暴露端口。

本地预览使用 SSH：

```powershell
ssh -N -L 18080:127.0.0.1:8120 -i C:\Users\Administrator\.ssh\id_ed25519_new ubuntu@124.220.177.67
```

建立连接后打开 http://127.0.0.1:18080。这是本机转发地址。停止开发预览用 sudo systemctl stop robot-rag-internal-dev.service。

旧生产 OpenResty、访问控制及构建说明保存在 ../docs/archive/deploy-before-20261111，仅用于历史恢复参考，不代表当前开发版已经发布。
