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

## 检索模式

`hybrid` 将向量与中文 BM25 的排名通过等权 RRF 融合；`vector` 保留纯向量模式，`keyword` 用于单独比较 BM25。两路均从数据库读取当前有效资料，按 UUID 去重。无关键词匹配时不凑足候选；系统故障沿用错误通道，不静默当作低相关性。

实现见 `src/services/retrieval.py` 和 `src/services/keyword.py`，方法见 [混合检索设计](specs/hybrid-retrieval_design.md)，验证见 [测试](testing.md)。
