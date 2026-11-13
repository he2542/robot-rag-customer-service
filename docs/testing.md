# 测试与评测

功能测试使用替代模型，不产生付费模型调用；真实检索评测会调用 Embedding 接口，两者分开运行。

## 后端测试

在 `services/backend` 执行：

```bash
python -m pytest -q
```

默认跳过数据库集成测试。其余用例覆盖 API、SSE、来源字段、风险分支、分词、编号、RRF 去重、缓存刷新、并发和依赖方向。

### 上下文消息回归

```bash
python -m pytest tests/test_internal_rag.py tests/test_rerank.py tests/test_api.py -q
```

用例检查不同轮次的系统提示词相同、本轮 JSON 资料与 SSE 来源一致，以及引号、花括号、换行和资料中的指令式文本仍作为数据传递。多轮用例还验证历史保留原生消息角色，保存的是用户原始问题，并为新问题提供本轮参考资料。这些检查使用替代模型验证消息契约；回答效果按独立评测比较。

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

结果见 [混合检索评测](validation/hybrid-retrieval-20261111.md)。后续应补充独立问题、无答案问题与完整相关性标注，再调整检索与精排参数。

### 模型精排对比

```bash
python -m evaluation.evaluate --rerank --output evaluation/results/rerank-01.json
```

显式传入 `--rerank` 后，在同一批 RRF 候选上额外比较 `hybrid_rerank`，不需要打开应用开关。除 24 次查询嵌入外，会增加最多 24 次排序调用；不调用聊天生成模型。

逐题记录精排状态、回退原因、分数、排序模型报告的 Token 用量和耗时。回退的基线结果仍计入总体指标，同时单独报告状态；不能把回退算作精排成功。已有原始评测不覆盖，比较时保留原有题集和参数。验证结果见 [模型精排评测](validation/rerank-20261111.md)。

## 300 题配对检索与回答评测

[扩样报告](validation/paired-300-20261111.md) 覆盖全部五份资料，比较同一批 RRF 候选的前四与模型精排前四。回答通过要求同时“答对问题”和“事实由自己的上下文支持”；模型评分尚未替代人工金标准。两轮评分、参考答案与判分分歧均保留，不能只挑其中较好的一轮报告。

### 离线复算（不调用 API）

在 `services/backend` 执行，先将证据包解压到新的本地结果目录：

```bash
python -m tarfile -e ../../docs/validation/paired-300-20261111-v1.tar.gz evaluation/results/reference-300
python -m evaluation.summarize_benchmark --root evaluation/results/reference-300 --output evaluation/results/recomputed-300.json
python -m pytest tests/test_paired_statistics.py tests/test_benchmark_binding.py -q
```

汇总程序检查每条回答、排序与评分的题集哈希，按预设片段组生成配对区间。输出文件已存在时拒绝覆盖；统计用例覆盖百分点、配对计数、分层权重、重采样复现、Wilson 边界与 UUID 重绑定。

### 重跑已冻结的题集（产生 API 用量）

新建结果目录，先绑定本机数据库的 UUID。绑定只查询数据库，不导入、不修改题目或参考答案；要求当前资料和切块内容与发布快照相同，内容有变化时拒绝将其当成同语料复现。

```bash
python -m evaluation.benchmark bind --template evaluation/results/reference-300 --root evaluation/results/run-300
python -m evaluation.benchmark retrieve --root evaluation/results/run-300
python -m evaluation.benchmark answer --root evaluation/results/run-300 --workers 4
python -m evaluation.benchmark judge --root evaluation/results/run-300 --workers 4
python -m evaluation.benchmark audit --audit-limit 300 --root evaluation/results/run-300 --workers 4
python -m evaluation.summarize_benchmark --root evaluation/results/run-300 --output evaluation/results/run-300-summary.json
```

完整流程包含 300 次查询嵌入、最多 300 次排序、600 份回答和两轮各 300 次成对评分，失败重试可能增加调用。需要账户能调用 `qwen-plus`、`qwen-max` 与配置中的嵌入和排序模型；生成与评审固定 temperature=0、seed=20261111。模型别名、服务版本和网络状态可变，重跑不承诺相同生成文本。

程序按条目保存成功结果，同一个结果目录可续跑，既有题目、回答和分数不会被替换。中断写入造成的损坏文件需要先保留原件并核对，不应当作已完成结果；不要在同一目录并行运行两个相同阶段。

`prepare / generate / validate / freeze` 用于创建新题集，不属于复现既有分数的必要步骤。它们会生成新问题与参考答案，需要先检查标签并冻结，再运行系统；禁止看过结果后调整标签以提升报告数值。原始模型检查说明也可能不准确，不能当作人工审校记录。
