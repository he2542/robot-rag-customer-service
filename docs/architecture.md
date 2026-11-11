# 项目架构

采用与“笔记本管理”一致的技术职责分层，不采用完整 DDD。前后端位于 services/backend 和 services/frontend。

## 后端

- src/main.py：应用组装、路由注册、CORS 和可选静态资源。
- src/config.py：读取 services/backend/.env，资料默认在仓库 knowledge/robot，运行数据默认在 runtime，可由环境变量覆盖。
- src/dependencies.py：集中创建服务和可替换依赖。
- src/routes：只处理 HTTP、状态码与 SSE。
- src/schemas：Pydantic 请求和公开响应契约。
- src/services/rag.py：前置条件、检索→上下文→模型生成、历史和来源处理。
- src/services/prompts.py：提示词；retrieval.py：检索与就绪状态；ingestion.py：切块、嵌入与导入；corpus.py：原文读取与版本身份。
- src/crud/knowledge.py：知识表参数化 SQL、事务、去重、统计与向量检索。
- src/database：连接、嵌入空间检查和显式建表。
- src/history.py：文件会话历史；src/cli.py：唯一管理员命令实现。

调用方向：routes/chat.py → services/rag.py → services/retrieval.py → crud/knowledge.py → database/connection.py。业务和数据层不依赖 HTTP；API 不写 SQL。简单功能无需穿过所有层。

当前直接使用 psycopg/pgvector，不创建空 ORM models.py。旧根 API、scripts 转发及 legacy_vector_store 已退出当前实现；旧适配器的检索/去重覆盖已迁移到当前检索器。

## 前端

App.vue → views/ChatView.vue 组合页面；components 负责输入、消息、来源、资料列表；store/chat.js 用 Vue ref 管理会话和流状态；api/client.js 负责请求，api/sse.js 处理分包；assets/styles.css 保留整体外观。没有新增 Vuex、Pinia 或页面路由依赖。

接口保持 GET /api/health、GET /api/knowledge、POST /api/chat。SSE 事件为 sources/content/error，成功以 [DONE] 结束。POST /api/knowledge/upload 继续返回 404。

## 保留的基线和限制

切块 1000 字符、重叠 100、召回 top-4、历史最近 12 条消息及资料版本哈希未调整。来源是检索候选，不代表逐句验真。教程原文非厂商官方资料，专业审校、公开服务认证、会话归属、限速和弃用依赖迁移仍需后续处理。文档归位不构成这些能力已完成。

旧设计、验收和部署资料分别保存在 specs、validation、archive，历史路径只用于追溯；当前命令以 backend.md、frontend.md 和 ../deploy/README.md 为准。唯一工作台账为 backlog.md。
