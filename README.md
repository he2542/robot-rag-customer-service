# Robot RAG Customer Service

基于 Vue 3、FastAPI、LangChain 和 PostgreSQL + pgvector 的扫地机器人智能客服示例。

Vue 提供聊天和检索参考资料展示，FastAPI 负责会话、内置知识库检索和 SSE 回答。普通用户无需上传文件；资料由管理员通过命令行维护。

## 功能

- 基于 PostgreSQL + pgvector 的向量知识库检索和 HNSW 余弦索引
- 基于文件的多轮会话历史
- Vue 3 聊天界面和 SSE 流式回答
- 内置五份扫地机器人 TXT，命令行预览/导入、版本去重和事务写入
- 只召回当前内置文件版本，排除旧上传和旧版本；回答附可展开的检索候选片段
- 未导入资料时禁止问答；空召回不调用生成模型；风险问题引导专业售后
- FastAPI 健康检查接口
- Vite 开发代理和基础 CI 检查

## 项目结构

后端按 Router / Schemas / Service / Repository 分层，完整目录与调用关系见 [backend/架构导航.md](backend/架构导航.md)。这是模块化单体，不是完整 DDD。

```text
robot-rag-dev/
├── backend/
│   ├── src/robot_rag/
│   │   ├── main.py、config.py、dependencies.py
│   │   ├── modules/chat/          # HTTP、请求契约、问答业务
│   │   ├── modules/rag/           # RAG 流程与提示词
│   │   ├── modules/knowledge/     # 导入、检索、知识仓储
│   │   ├── modules/health/        # 健康状态
│   │   ├── shared/                # 连接、建表、历史、SSE
│   │   └── cli/                   # 管理员命令
│   ├── scripts/                   # 导入与初始化入口
│   ├── tests/
│   ├── pyproject.toml
│   └── requirements.txt
├── knowledge/robot/               # 管理员维护 TXT
├── frontend/                      # Vue 3 + Vite
├── deploy/                        # 历史生产部署参考
└── specs/                         # 设计说明
```

## 环境准备

需要 Python 3.10+、Node.js 18+、PostgreSQL + pgvector，以及 DashScope API Key。

```powershell
Set-Location "path\to\robot-rag-dev\backend"

python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt -c requirements-internal-20261107.txt
Copy-Item .env.example .env
```

将 `.env` 中的 `DASHSCOPE_API_KEY` 替换为真实密钥。`.env` 已被 Git 忽略，不会上传。

在数据库中由管理员执行 `CREATE EXTENSION vector`，然后配置 `DATABASE_URL`。
开发环境可使用 `postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/robot_rag`；不要提交真实连接凭据。
开发版使用独立数据库和专用角色，不要直接指向旧生产库；配置模板见 `backend/.env.example`。
数据库可创建后执行 `python scripts/init_database.py` 初始化业务表；`EMBEDDING_MODEL` 和 `EMBEDDING_DIMENSIONS` 必须与数据库记录一致，默认使用 `text-embedding-v4` 的 1024 维向量。

## 预览和导入内置资料

在 `backend` 中执行 `python scripts/import_knowledge.py`，只输出文件和预计切块数，不连接数据库或调用模型。
确认后执行 `python scripts/import_knowledge.py --apply`，才会调用 DashScope 嵌入模型并产生用量、写入数据库。
已有相同文件版本会跳过；中断后可重跑。修改 TXT 后重新导入即可，新版本生效，旧记录保留但不再召回。
文件位于 `knowledge/robot`；也可通过 `RAG_KNOWLEDGE_DIR` 指定管理员目录。普通用户的上传接口已移除。

## 启动后端

```powershell
Set-Location "path\to\robot-rag-dev\backend"
& ".\.venv\Scripts\python.exe" -m uvicorn robot_rag.main:app --app-dir src --reload --host 127.0.0.1 --port 8000
```

API 文档：<http://127.0.0.1:8000/docs>

## 启动前端

```powershell
Set-Location "path\to\robot-rag-dev\frontend"
npm install
npm run dev
```

访问 <http://localhost:5173>。Vite 会将 `/api` 请求代理到本地 FastAPI 服务。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 检查数据库连通性、存储类型及模型配置状态；数据库不可用时返回 503 |
| POST | `/api/chat` | SSE 流式问答，JSON 参数为 `input`、`session_id` |
| GET | `/api/knowledge` | 当前内置资料名、切块数和导入就绪状态 |

`/api/chat` 先返回 `sources` 事件（编号、文件名、片段序号、原文），再返回 `content` 事件，成功以 `[DONE]` 结束。
流异常返回通用 `error`，前端标记本次回答未完成。参考列表展示召回候选，不等于每句话均已事实核验。

## 测试

```powershell
Set-Location "path\to\robot-rag-dev\backend"
& ".\.venv\Scripts\python.exe" -m pytest
```

## 数据说明

向量、原文和元数据存储在 `rag_chunks`；去重记录在 `rag_documents`；嵌入模型与维度在 `rag_configuration`。本版聊天历史另存 `chat_history/robot_internal_v1/`，不读取旧服装客服的会话，父目录由 `RAG_DATA_DIR` 决定。

本版资料来自课程示例，非品牌官方手册，未经完整专业审校。数值、品牌结论和维修步骤不应当作官方承诺；危险问题建议停止使用并联系售后。提示词和关键词规则不能保证识别所有风险，公开上线前仍需资料审校、身份认证、会话归属控制和请求限速。默认仅 localhost 开发，随机会话 ID 不构成身份认证。

更换聊天模型不需要重建知识库；更换嵌入模型或维度需要重新生成知识向量，并使用独立表或数据库迁移。旧 Chroma 数据不会自动读取或删除；若已有数据，应单独备份、导出与核验后迁移。

数据库集成测试必须使用名为 `robot_rag_test` 的独立测试库，先由管理员启用 pgvector，然后设置 `DATABASE_URL` 指向测试库及 `RAG_RUN_DB_TESTS=1` 后运行 `pytest -q`。测试会清空该测试库中的知识表，拒绝在生产库上运行。未设置该标志时跳过数据库集成测试。CI 已配置独立 PostgreSQL + pgvector 服务。

前端验证：在 `frontend` 执行 `node --test src/sse.test.js` 和 `npm run build`。

## 当前服务器开发预览（2026-11-07）

服务器开发副本为 `/home/ubuntu/robot-rag-dev`，解释器为 `backend/.venv/bin/python`；独立开发数据库为 `robot_rag_internal_dev`。
临时服务 `robot-rag-internal-dev.service` 在 `127.0.0.1:8120` 运行，启用 `RAG_SERVE_FRONTEND=1` 时同时托管已构建的 `frontend/dist`。
Windows 通过 SSH 转发到 `http://127.0.0.1:18080`，只有建立转发的这台电脑可以这样访问。旧网站没有恢复或更新。

开发服务由 systemd 读取原有模型环境文件和开发库配置；不把已有模型密钥复制到代码或文档中。导入命令须在有模型凭据的管理员运行环境执行。
旧 `qwen3-max` 在实测中返回“模型不存在”，开发配置现使用已实测可用的 `qwen-plus`，嵌入仍为 `text-embedding-v4` / 1024 维。

旧部署与备份恢复说明仍见 [deploy/README.md](deploy/README.md)，不代表本版已经部署。`backend/requirements-deployed.txt` 是旧部署依赖记录；本版实测记录另存，勿混同。
