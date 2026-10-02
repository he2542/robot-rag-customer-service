# Robot RAG Customer Service

基于 Vue 3、FastAPI、LangChain 和 PostgreSQL + pgvector 的扫地机器人智能客服示例。

项目将前端展示与 RAG 服务解耦：Vue 负责聊天和知识库上传，FastAPI 负责会话管理、向量检索、模型调用和 SSE 流式输出。

## 功能

- 基于 PostgreSQL + pgvector 的向量知识库检索和 HNSW 余弦索引
- 基于文件的多轮会话历史
- Vue 3 聊天界面和 SSE 流式回答
- TXT 知识库上传、文本切分和 SHA-256 去重；文档与向量在同一事务中写入
- FastAPI 健康检查接口
- Vite 开发代理和基础 CI 检查

## 项目结构

```text
RAG项目实例/
├── api.py                    # FastAPI 接口入口
├── rag.py                    # RAG 检索和问答链
├── knowledge_base.py         # 知识库写入服务
├── vector_stores.py          # PGVectorStore 检索器
├── database.py               # 数据库初始化、去重与事务写入
├── file_history_store.py     # 文件会话历史
├── config_data.py            # 配置和本地数据路径
├── frontend/                 # Vue 3 + Vite 前端
├── tests/                    # API 与真实 PostgreSQL 集成测试
├── deploy/                   # 生产服务配置与维护说明
├── .env.example              # 环境变量模板
├── requirements.txt          # 运行依赖
└── .github/workflows/ci.yml  # GitHub Actions
```

## 环境准备

需要 Python 3.10+、Node.js 18+、PostgreSQL + pgvector，以及 DashScope API Key。

```powershell
Set-Location "path\to\robot-rag-customer-service"

python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
Copy-Item .env.example .env
```

将 `.env` 中的 `DASHSCOPE_API_KEY` 替换为真实密钥。`.env` 已被 Git 忽略，不会上传。

在数据库中由管理员执行 `CREATE EXTENSION vector`，然后配置 `DATABASE_URL`。
开发环境可使用 `postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/robot_rag`；不要提交真实连接凭据。
生产部署使用专用操作系统用户与 PostgreSQL peer 认证，无需数据库密码，连接信息见 `.env.example`。
数据库可创建后执行 `python database.py` 初始化业务表；`EMBEDDING_MODEL` 和 `EMBEDDING_DIMENSIONS` 必须与数据库记录一致，默认使用 `text-embedding-v4` 的 1024 维向量。

## 启动后端

```powershell
Set-Location "path\to\robot-rag-customer-service"
& ".\.venv\Scripts\python.exe" -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

API 文档：<http://127.0.0.1:8000/docs>

## 启动前端

```powershell
Set-Location "path\to\robot-rag-customer-service\frontend"
npm install
npm run dev
```

访问 <http://localhost:5173>。Vite 会将 `/api` 请求代理到本地 FastAPI 服务。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 检查数据库连通性、存储类型及模型配置状态；数据库不可用时返回 503 |
| POST | `/api/chat` | SSE 流式问答，JSON 参数为 `input`、`session_id` |
| POST | `/api/knowledge/upload` | 上传 UTF-8 TXT 原始文件流，文件名放在 `X-Filename` 请求头 |

## 测试

```powershell
Set-Location "path\to\robot-rag-customer-service"
& ".\.venv\Scripts\python.exe" -m pytest
```

## 数据说明

向量、原文片段和元数据存储在 PostgreSQL 的 `rag_chunks` 表，上传去重记录存储在 `rag_documents` 表，嵌入模型和维度记录在 `rag_configuration` 表。聊天历史仍保存到本地 `chat_history/`，由 `RAG_DATA_DIR` 决定其父目录。

更换聊天模型不需要重建知识库；更换嵌入模型或维度需要重新生成知识向量，并使用独立表或数据库迁移。旧 Chroma 数据不会自动读取或删除；若已有数据，应单独备份、导出与核验后迁移。

数据库集成测试必须使用名为 `robot_rag_test` 的独立测试库，先由管理员启用 pgvector，然后设置 `DATABASE_URL` 指向测试库及 `RAG_RUN_DB_TESTS=1` 后运行 `pytest -q`。测试会清空该测试库中的知识表，拒绝在生产库上运行。未设置该标志时跳过数据库集成测试。CI 已配置独立 PostgreSQL + pgvector 服务。

生产部署与备份恢复见 [deploy/README.md](deploy/README.md)。`requirements-deployed.txt` 记录本次 Ubuntu / Python 3.10 部署实际验证的依赖版本。
