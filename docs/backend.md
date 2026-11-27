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
| `RAG_CONTEXT_ENTRIES_ENABLED` | `false`；设为 `true` 启用第一阶段上下文构建：完整条目、去重、预算与回答流程 |
| `RAG_RERANK_URL` | 默认北京地域 DashScope 原生文本排序接口；须与密钥地域匹配 |
| `RAG_SERVE_FRONTEND` | 设为 `1` 时托管已构建的前端 |

检索阶段选择前 4 个片段，配置值位于 `src/config.py`。启用条目整理后，每个片段按原文中的完整条目重新组装，最多保留 4 组来源。修改环境配置后重启应用。更换聊天模型不需要重建向量；更换嵌入模型或维度需要独立迁移和验证。

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

SSE 先发送 `sources`，再发送 `content`，成功以 `data: [DONE]` 结束。流中出现 `error` 时应将回答标为未完成。来源基本字段为 `id`、`filename`、`chunk_index`、`excerpt`；完成条目定位的来源还包含 `document_hash` 和 `source_spans`。不返回数据库 UUID、内部路径或原始异常。

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

历史保存用户原始问题和模型回答，每轮重新检索并提供本轮资料。

### 完整条目与审校记录

设置 `RAG_CONTEXT_ENTRIES_ENABLED=true` 后，`src/services/context.py` 在生成前执行以下处理：

1. 用文件名、文档版本和片段正文，在当前 TXT 中确定唯一位置。
2. 恢复与该位置相交的完整问答或故障条目，保留章节标题、适用条件、否定词和数值。
3. 根据 `src/services/evidence_review.py` 的版本化记录排除已确认问题条目。
4. `src/services/prompt_context.py` 对含适用条件的完整条目精确去重，重叠片段中的同一条目只保留一次；条件、否定词或数值不同的内容分别保留。
5. 以问题词项覆盖、局部稀有度与条目问题行匹配优先选择完整条目，按来源与原文顺序重新组装。预算不足时舍弃整条，不截断条件或正文，不增加模型压缩调用。
6. 连续生成 `[S1]` 等编号，为模型和 SSE 提供同一份来源；全部排除或没有完整条目能放入预算时，返回无可用资料提示。

审校记录匹配文件名、文档版本、起始行和条目 SHA-256，覆盖当前版本的 5 条电池、碰撞保护和电机处理建议。更新资料版本时需重新核对记录。无法可靠定位或识别条目的片段保留原文，并记录回退分类；资料读取故障走现有错误通道。

定位信息中的 `document_hash` 是知识库文档版本标识；`source_spans` 为原 TXT 的行号范围列表，起止均包含在内，从 1 开始。范围可能不连续，例如中间的条目已排除。`chunk_index` 仍指向检索到的原片段，`excerpt` 是实际提供给模型的整理后正文。

该开关默认关闭，关闭后沿用原系统提示、片段与最近12条历史。开启后的输入预算如下：

| 项目 | 上限与计量方式 |
|---|---|
| 总输入 | 32 KiB；计入系统、历史、本轮问题、证据和 JSON 转义后的消息序列 |
| 参考证据 | 12 KiB；计入来源字段和正文的 JSON 数组 |
| 历史 | 8 KiB；从近期向前保留完整 user/assistant 对话轮次，原文与角色不变 |
| 派生会话状态 | 暂不支持 |

预算以 UTF-8 字节作为代理，实际 Token 使用模型接口报告值。系统规则、当前问题和已选关键证据优先；总预算不足时先移除较早历史。历史筛选只改变本轮输入，不裁剪磁盘原记录、不生成摘要。缺少完整轮次的孤立消息不进入模型。诊断日志仅记录字节数、去重/舍弃数量、历史消息数和接口用量，不记录问题或正文。

### 回答与引用校验

启用上下文构建后，模型使用 JSON Object 模式返回回答决策、结论和支持结论的原文引句。`src/services/answer_policy.py` 校验生成结果后，再向客户端发送回答。

| 处理 | 行为 |
|---|---|
| 引用定位 | 在本轮 `excerpt` 中定位引句，并据此生成 `[S1]` 等编号；只容许列表、加粗和空白等排版差异 |
| 步骤补全 | 对普通处理方法咨询，检查同一引句的动作及对象是否覆盖；有遗漏时恢复完整原文，保留条件和禁止语句 |
| 限制条目恢复 | 对适用条件咨询，支持逐行唯一匹配的 2～4 条完整编号原文，分别展示各自条件和来源 |
| 维护周期回答 | 涉及明确周期时，使用唯一匹配的完整编号条目或问答，分别保留部件、条件和来源 |
| 操作风险过滤 | 移除禁止的拆装、滴油和电气操作建议；异常发热或电池故障时提示停止使用和充电 |

无法定位、来源歧义或含禁止操作的结论逐条移除，其余有效结论保留。缺字引句和不完整条目不自动恢复；步骤补全只使用已经匹配的引句，不跨条目拼接。内部部件的诊断检查标为“专业售后检查项”。日常功能、选购与参数咨询不直接视为故障。

完整正文引句可以省略起始列表编号，但必须唯一匹配完整原条目；提供了编号时仍核对原编号。维护周期回答支持一次定位 1～4 个完整条目，包括“问题＋答案”的多行内容；其中任一条不完整或出现多处匹配时，该组不输出。相同可见条目去重。该规则保留资料原文的范围，资料本身的冲突仍需审校，见[完整条目测试](validation/maintenance-entries-20261124.md)。

模型应保留原文的适用条件、否定词和数值。缺少必要信息时澄清，证据冲突时分别说明条件。全部结论无效或内部协议错误时返回无法可靠确认的提示；澄清、资料不足和专业售后提示允许无引用。

内部 JSON 不发送给前端。SSE 按 `sources → content → [DONE]` 返回，`content` 在完整校验后发送；历史保存处理后的可见回答。

这些规则主要依据原文匹配和词面检查。部件归属、同一周期下的不同条件以及复杂语义支持度仍需要评测。当前验证模型为支持 JSON Object 模式的非思考 `qwen-plus`，接口要求见[结构化输出说明](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。

### 验证与适用范围

上下文构建默认关闭。300 题对照中，引用支持与风险用例改善，回答自动通过率下降；后续提示词实验也出现最终回答通过数下降，已恢复基线提示。完整方法、结果和复现数据见：

- [300 题上下文评测](validation/phase1-context-300-20261116.md)
- [提示词对照评测](validation/intent-workflow-live-20-20261121.md)与[回退验证](validation/prompt-rollback-20261122.md)
- [维护周期50题独立对照](validation/maintenance-independent-50-20261124.md)：自动通过率39/50→39/50，1题改善、1题退化，完整条目功能保持默认关闭。
- [步骤补全](validation/partial-answer-coverage-20261120.md)、[操作风险](validation/operation-boundaries-20261122.md)、[限制条目恢复](validation/quote-recovery-20261122.md)和[维护周期校验](validation/maintenance-cycles-20261123.md)

当前支持单轮证据整理和近期完整对话筛选；追问改写、结构化会话状态和历史摘要尚未实现。测试命令和离线复现方式见[测试与评测](testing.md)。

## 检索模式

`hybrid` 将向量与中文 BM25 的排名通过等权 RRF 融合；`vector` 保留纯向量模式，`keyword` 用于单独比较 BM25。两路均从数据库读取当前有效资料，按 UUID 去重。无关键词匹配时不凑足候选；系统故障沿用错误通道，不静默当作低相关性。

实现见 `src/services/retrieval.py` 和 `src/services/keyword.py`，方法见 [混合检索设计](specs/hybrid-retrieval_design.md)，验证见 [测试](testing.md)。

## 模型精排

在 `.env` 中设置 `RAG_RERANK_ENABLED=true` 后重启应用，即可在 hybrid 模式对 RRF 的全部候选重新排序，再选择最终 4 条。关闭开关可恢复原 RRF 结果；vector、keyword 不调用精排。使用已有 `DASHSCOPE_API_KEY`，请求会将问题和候选正文发送给配置的排序服务，每次非平凡候选查询增加一次 API 调用。

实现不自动重试，网络阶段超时、限流、服务错误、非法结果或输入预算超出时，保留 RRF 顺序并以分类原因记录回退。初始连接超时不超过 1 秒，读写等阶段超时为配置值，不是严格的端到端总时限。

初版按 UTF-8 字节做保守输入预算：单查询/片段不超过 4000 字节，请求总预算不超过 120000 字节（查询按候选数重复计入）。这不是精确 Token 计算，较长中文问题可能跳过精排；不会截断问题或原文。模型分数只用于本请求内排序，不是回答置信度或拒答阈值。更换模型需重新核验接口与输入限制。

设计见 [模型精排](specs/rerank_design.md)，效果与用量见 [精排评测](validation/rerank-20261111.md)。

缺编号维护条目的修复及离线增量效果见[维护条目恢复验证](validation/maintenance-numberless-20261127.md)。

并列提问支持从唯一完整问答恢复遗漏动作与参数，窄问题保持原回答，见[并列问答补全验证](validation/multipart-qa-20261127.md)。

## 实验条目导航

构造 RagService 时可传入 context_entries_enabled=True、context_navigation_enabled=True，在模型输入中加入来源ID、excerpt行号与条目标题导航；完整参考资料和公开sources保持原样。导航默认关闭，仍使用结构化引句回答；导航、资料与历史共同受输入字节预算约束。验证方法和适用范围见[验证报告](validation/context-guard-navigation-20261127.md)。
