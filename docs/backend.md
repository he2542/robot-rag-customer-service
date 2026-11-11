# 后端开发

工作目录：services/backend。解释器使用该目录 .venv/bin/python（Ubuntu）或 .venv/Scripts/python.exe（Windows）。

```bash
python -m venv .venv
# 激活对应环境后：
python -m pip install -e . -c constraints.txt
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

依赖只在 pyproject.toml 声明；constraints.txt 是当前验证版本约束，不保证未来所有 Python/操作系统组合。更换依赖时更新约束并回归，历史快照位于 archive/dependencies。

复制 .env.example 为 .env，填写专用数据库和模型配置，不提交真实配置。管理员先在目标库启用 pgvector，确认连接目标后才执行：

```bash
python -m src.cli init-db
python -m src.cli import-knowledge
python -m src.cli import-knowledge --apply
```

导入默认仅预览，无模型调用和数据库写入；--apply 才嵌入、写库。重复版本跳过，旧版本保留但不召回。安装本项目后也可使用 robot-rag import-knowledge / robot-rag init-db，均调用同一实现。

更换聊天模型无需重建向量；更换嵌入模型或维度必须使用迁移方案，不能直接覆盖已有空间。历史 namespace 保持 chat_history/robot_internal_v1，RAG_DATA_DIR 默认指向仓库 runtime。

## PyCharm

本地工作目录为 services/backend；SSH 解释器为 /home/ubuntu/robot-rag-dev/services/backend/.venv/bin/python。运行配置 module=uvicorn，参数=src.main:app --host 127.0.0.1 --port 8000。开发预览使用 8120，已有服务运行时请勿重复占用。

仓库根 SFTP 映射不变：本地 robot-rag-dev 对应 /home/ubuntu/robot-rag-dev。将 services/backend 标记为导入根，src 是 Python 包。IDE 配置不属于 Git 仓库。
