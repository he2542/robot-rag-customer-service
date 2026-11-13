# 项目架构

项目采用单体应用的技术职责分层。后端位于 `services/backend`，前端位于 `services/frontend`；HTTP、业务编排和持久化分别实现，便于定位和替换检索策略。

## 后端

以下路径相对于 `services/backend/`：

| 路径 | 职责 |
|---|---|
| `src/main.py` | 组装 FastAPI、CORS、路由和可选静态资源 |
| `src/config.py` | 环境变量、模型、资料目录和检索参数 |
| `src/dependencies.py` | 服务创建与可替换依赖 |
| `src/routes/` | HTTP 契约、状态码和 SSE 输出 |
| `src/schemas/` | Pydantic 请求和公开响应模型 |
| `src/services/rag.py` | 问答前置条件、上下文、生成、历史与引用编号 |
| `src/services/retrieval.py` | 双路召回、片段去重和 RRF 融合 |
| `src/services/keyword.py` | 中文分词和 BM25 索引 |
| `src/services/rerank.py` | 可选排序 API、结果校验和失败回退 |
| `src/services/ingestion.py` | 切块、批量嵌入和入库编排 |
| `src/services/corpus.py` | TXT 读取、知识库命名空间和版本身份 |
| `src/services/prompts.py` | 回答约束与系统提示词 |
| `src/crud/knowledge.py` | 参数化 SQL、事务、去重和受限检索 |
| `src/database/` | 数据库连接、嵌入空间检查和显式建表 |
| `src/history.py` | 文件会话历史 |
| `src/cli.py` | 管理员命令 |

问答调用关系：

```text
routes/chat → services/rag → services/retrieval
                                  ├─ services/keyword
                                  ├─ services/rerank（可选）
                                  └─ crud/knowledge → database/connection
```

路由不写 SQL，业务和持久化层不依赖 HTTP；简单功能可以直接调用所需层，不要求每个请求经过所有目录。当前直接使用 psycopg 和 pgvector，不使用 ORM。

## 前端

`App.vue` 挂载 `views/ChatView.vue`。页面组合输入、消息、参考资料与知识库状态组件；`store/chat.js` 使用 Vue 响应式管理会话和流状态；`api/client.js` 发起请求，`api/sse.js` 解析流，样式位于 `assets/styles.css`。

## 数据与检索

- `rag_documents` 保存文档身份和片段数量，`rag_chunks` 保存片段 UUID、正文、向量和元数据。
- `rag_configuration` 保存嵌入模型和维度，阻止不兼容的向量空间混用。
- 文档身份由命名空间、文件名和内容计算；检索同时限定命名空间和当前文档版本。
- 默认按 1000 字符切块、重叠 100 字符；混合检索两路各取 10 条，RRF 后保留 4 条。
- 开启模型精排后，先对完整 RRF 候选重排，再截取 4 条；vector 和 keyword 模式保持原排序。
- 会话历史保存在 `runtime/chat_history/robot_internal_v1/`，提示词最多使用最近 12 条历史消息。

模型消息按“固定系统规则 → 原生角色历史 → 本轮 JSON 数据”组织。本轮数据包含 `question` 和 `references`，后者复用 SSE 来源结构，检索正文不再插入系统消息。历史记录保存原始问答，本轮参考资料在生成时单独组装；字段示例见 [后端开发](backend.md#上下文消息结构)。

BM25 为进程内索引，每次检索读取有效片段快照，仅在 UUID 或内容变化时重建。此实现面向小型资料库；规模增大时需评估全量读取、索引持久化与资源开销。

## 相关文档

- [后端开发](backend.md)
- [前端开发](frontend.md)
- [知识库设计](specs/internal-knowledge_design.md)
- [混合检索设计](specs/hybrid-retrieval_design.md)
- [当前限制与路线图](backlog.md)
