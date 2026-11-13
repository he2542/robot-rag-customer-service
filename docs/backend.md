# 后端开发

所有命令均在 `services/backend` 执行，使用该目录的虚拟环境。完整安装流程见 [README](../README.md#快速开始)。

依赖以 `pyproject.toml` 声明，`constraints.txt` 记录已验证版本；版本约束不保证任意 Python 与操作系统组合均兼容。

## 配置

将 `.env.example` 复制为 `.env`。环境变量优先于 `.env`，不要将真实配置提交到版本库。

| 变量 | 默认值或用途 |
|---|---|
| `DATABASE_URL` | PostgreSQL 连接串，必须配置 |
| `DASHSCOPE_API_KEY` | 模型访问密钥，必须配置 |
| `EMBEDDING_MODEL` | `text-embedding-v4` |
| `EMBEDDING_DIMENSIONS` | `1024`，须与已建知识库一致 |
| `CHAT_MODEL` | `qwen-plus`，须在所用账号中可用 |
| `RAG_KNOWLEDGE_DIR` | 默认为仓库的 `knowledge/robot` |
| `RAG_DATA_DIR` | 默认为仓库的 `runtime`，保存会话历史 |
| `RAG_RETRIEVAL_MODE` | `hybrid`；也支持 `vector`、`keyword` |
| `RAG_RETRIEVAL_CANDIDATES` | `10`，每路候选数，范围 4—100 |
| `RAG_RRF_K` | `60`，RRF 正整数平滑常数 |
| `RAG_RERANK_ENABLED` | `false`，设为 `true` 为 hybrid 模式启用精排 |
| `RAG_RERANK_MODEL` | `qwen3-rerank`，已验证的排序模型 |
| `RAG_RERANK_TIMEOUT` | `3` 秒，HTTP 阶段超时，范围大于 0 且不超过 30 |
| `RAG_RERANK_URL` | 默认北京地域 DashScope 原生文本排序接口；须与密钥地域匹配 |
| `RAG_SERVE_FRONTEND` | 设为 `1` 时托管已构建的前端 |

最终上下文为前 4 个片段，配置值位于 `src/config.py`。修改环境配置后重启应用。更换聊天模型不需要重建向量；更换嵌入模型或维度需要独立迁移和验证，不能直接覆盖已有配置记录。

## 启动

```bash
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

开发调试可以增加 `--reload`。IDE 运行配置使用模块 `uvicorn`，工作目录设为 `services/backend`，参数与上述命令一致。

## 管理知识库

由管理员在目标库启用 `vector` 扩展后执行：

```bash
python -m src.cli init-db
python -m src.cli import-knowledge
python -m src.cli import-knowledge --apply
```

- `init-db` 显式初始化业务表，不在应用启动时执行。
- `import-knowledge` 只预览文件和切块数量，不访问数据库或模型。
- `--apply` 才嵌入并写库，产生模型调用用量；相同版本跳过。
- 修改 TXT 后重新导入，新版本生效；旧记录保留但不召回。删除文件会将其移出当前检索范围。

安装项目后也可使用 `robot-rag init-db` 和 `robot-rag import-knowledge`，与模块命令共用同一实现。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 返回数据库、模型配置和知识库状态；数据库不可用时为 503 |
| GET | `/api/knowledge` | 当前资料列表、片段数、就绪状态与资料范围提示 |
| POST | `/api/chat` | 接收 `input` 与可选 `session_id`，返回 SSE |

`input` 长度为 1—4000；`session_id` 长度为 1—100，仅允许字母、数字、下划线和连字符，省略时自动生成。模型未配置或资料未就绪时禁止问答，空白问题会被拒绝。

SSE 先发送 `sources`，再发送 `content`，成功以 `data: [DONE]` 结束。流中出现 `error` 时应将回答标为未完成。来源字段为 `id`、`filename`、`chunk_index`、`excerpt`；不返回数据库 UUID、内部路径或原始异常。

应用不提供公开上传接口。风险关键词会触发固定安全提示；该规则不覆盖全部危险表达。来源编号过滤不等于逐句事实核验。

## 上下文消息结构

`RagService` 按以下顺序组织模型输入：

```text
system：固定的职责、回答约束和引用规则
history：最近 12 条历史消息，保留原生 user/assistant 角色
human：本轮问题和参考资料组成的 JSON
```

最后一条 human 消息的结构如下，这是服务内部的模型输入格式；客户端仍按原 API 发送 `input` 和 `session_id`。

```json
{
  "question": "主刷卡住了怎么办？",
  "references": [
    {
      "id": "S1",
      "filename": "维护保养.txt",
      "chunk_index": 0,
      "excerpt": "请清理主刷。"
    }
  ]
}
```

参考资料通过 `source_items()` 生成，与 SSE 的 `sources` 字段一致；`json.dumps(..., ensure_ascii=False)` 保留中文并转义引号、换行等内容。系统提示词定义这些字段的含义，引用使用资料 `id` 对应的 `[S1]` 等编号。

历史仍保存用户原始问题和模型回答，每轮重新检索并提供本轮资料。当前实现完成指令与资料分离，后续证据筛选、上下文预算和结构化会话状态分别演进。

## 检索模式

`hybrid` 将向量与中文 BM25 的排名通过等权 RRF 融合；`vector` 保留纯向量模式，`keyword` 用于单独比较 BM25。两路均从数据库读取当前有效资料，按 UUID 去重。无关键词匹配时不凑足候选；系统故障沿用错误通道，不静默当作低相关性。

实现见 `src/services/retrieval.py` 和 `src/services/keyword.py`，方法见 [混合检索设计](specs/hybrid-retrieval_design.md)，验证见 [测试](testing.md)。

## 模型精排

在 `.env` 中设置 `RAG_RERANK_ENABLED=true` 后重启应用，即可在 hybrid 模式对 RRF 的全部候选重新排序，再选择最终 4 条。关闭开关可恢复原 RRF 结果；vector、keyword 不调用精排。使用已有 `DASHSCOPE_API_KEY`，请求会将问题和候选正文发送给配置的排序服务，每次非平凡候选查询增加一次 API 调用。

实现不自动重试，网络阶段超时、限流、服务错误、非法结果或输入预算超出时，保留 RRF 顺序并以分类原因记录回退。初始连接超时不超过 1 秒，读写等阶段超时为配置值，不是严格的端到端总时限。

初版按 UTF-8 字节做保守输入预算：单查询/片段不超过 4000 字节，请求总预算不超过 120000 字节（查询按候选数重复计入）。这不是精确 Token 计算，较长中文问题可能跳过精排；不会截断问题或原文。模型分数只用于本请求内排序，不是回答置信度或拒答阈值。更换模型需重新核验接口与输入限制。

设计见 [模型精排](specs/rerank_design.md)，效果与用量见 [精排评测](validation/rerank-20261111.md)。
