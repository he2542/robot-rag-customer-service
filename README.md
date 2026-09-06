# Robot RAG Customer Service

基于 Vue 3、FastAPI、LangChain 和 Chroma 的扫地机器人智能客服示例。

项目将前端展示与 RAG 服务解耦：Vue 负责聊天和知识库上传，FastAPI 负责会话管理、向量检索、模型调用和 SSE 流式输出。

## 功能

- 基于 Chroma 的本地向量知识库检索
- 基于文件的多轮会话历史
- Vue 3 聊天界面和 SSE 流式回答
- TXT 知识库上传、文本切分和 MD5 去重
- FastAPI 健康检查接口
- Vite 开发代理和基础 CI 检查

## 项目结构

```text
RAG项目实例/
├── api.py                    # FastAPI 接口入口
├── rag.py                    # RAG 检索和问答链
├── knowledge_base.py         # 知识库写入服务
├── vector_stores.py          # Chroma 检索器
├── file_history_store.py     # 文件会话历史
├── config_data.py            # 配置和本地数据路径
├── frontend/                 # Vue 3 + Vite 前端
├── tests/                    # API 冒烟测试
├── .env.example              # 环境变量模板
├── requirements.txt          # 运行依赖
└── .github/workflows/ci.yml  # GitHub Actions
```

## 环境准备

需要 Python 3.10+、Node.js 18+，以及 DashScope API Key。

```powershell
Set-Location "path\to\robot-rag-customer-service"

& "C:\Users\32119\miniconda3\python.exe" -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
Copy-Item .env.example .env
```

将 `.env` 中的 `DASHSCOPE_API_KEY` 替换为真实密钥。`.env` 已被 Git 忽略，不会上传。

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
| GET | `/api/health` | 检查服务状态 |
| POST | `/api/chat` | SSE 流式问答，JSON 参数为 `input`、`session_id` |
| POST | `/api/knowledge/upload` | 上传 UTF-8 TXT 原始文件流，文件名放在 `X-Filename` 请求头 |

## 测试

```powershell
Set-Location "path\to\robot-rag-customer-service"
& ".\.venv\Scripts\python.exe" -m pytest
```

## 数据说明

`chroma_db/`、`chat_history/` 和 `md5.text` 是本地运行时数据，默认不会上传到 GitHub。首次运行或部署到新环境时，向量库需要重新导入知识内容。

原有的 `app_qa.py` 和 `app_file_uploader.py` 是旧版 Streamlit 入口，新前端使用 `api.py` 和 `frontend/`。
