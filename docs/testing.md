# 测试与评测

功能测试使用替代模型，不产生付费模型调用；真实检索评测会调用 Embedding 接口，两者分开运行。

## 后端测试

在 `services/backend` 执行：

```bash
python -m pytest -q
```

默认跳过数据库集成测试。其余用例覆盖 API、SSE、来源字段、风险分支、分词、编号、RRF 去重、缓存刷新、并发和依赖方向。

### 数据库集成测试

使用一次性 PostgreSQL + pgvector 数据库，库名必须为 `robot_rag_test`；另兼容测试夹具中列出的历史专用测试库名。管理员需先启用 `vector` 扩展。

设置 `DATABASE_URL` 指向该测试库，并设置 `RAG_RUN_DB_TESTS=1`，再执行 `python -m pytest -q`。

**测试夹具会清空目标库的知识表，禁止使用开发业务库或生产库。** 测试验证事务回滚、并发去重、向量兼容性，以及三种检索模式下的旧上传和旧版本隔离。CI 在独立 PostgreSQL 服务中运行。

## 前端测试

在 `services/frontend` 执行：

```bash
npm test
npm run build
```

用例覆盖中文 UTF-8/SSE 分包、错误和截断，以及消息、来源、会话、中止与重复发送状态。

## 检索评测

在 `services/backend` 配置可用数据库和模型密钥后执行：

```bash
python -m evaluation.evaluate --output evaluation/results/run-01.json
```

程序只查询知识库，不导入资料、不调用聊天模型。24 个问题分别调用一次查询嵌入接口，产生对应 API 用量；输出已存在时拒绝覆盖。

题集位于 `evaluation/questions.json`。每题以文件名和原文锚点定位目标片段；运行前校验目标证据存在，然后比较 `vector`、`keyword`、`hybrid`：

- **Hit@4**：前四条是否含任一标注片段。
- **Recall@4**：前四条覆盖的标注片段比例。
- **MRR@4**：前四条中首个标注片段排名的倒数，未命中记为 0。
- **候选覆盖与时延**：保存完整候选 ID、逐题结果和两路耗时，便于检查退化。

首版每题只标一个片段，所以 Hit@4 与 Recall@4 相同。标签不穷尽其他等价证据，题集只覆盖 3/5 份资料，不能把这些指标视为完整相关性或回答准确率。计时包含网络与首次索引初始化，单轮顺序运行不代表并发性能。

结果见 [混合检索评测](validation/hybrid-retrieval-20261111.md)。后续应补充独立问题、无答案问题与完整相关性标注，再调参或接入 rerank。
