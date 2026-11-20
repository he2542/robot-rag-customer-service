# 测试与评测

日常回归优先离线，必要的真实验证使用有预算的小样本。真实生成、模型评分、Embedding和模型精排分别产生接口用量，按需单独运行。

## 低成本测试方法

按改动选择验证方式，先定位具体问题，再决定是否需要真实模型。

| 改动 | 优先验证方式 | 付费调用 |
|---|---|---:|
| API、SSE、历史、预算、来源编号 | 单元测试、替代模型与固定输入 | 0次 |
| 完整条目恢复、去重、证据筛选 | 冻结题集和候选，检查目标证据、适用条件、原文位置与预算 | 0次 |
| 引用处理、回答过滤、专业操作边界 | 重放已有模型原始输出，检查新的可见回答 | 0次 |
| 检索策略或精排接入代码 | 用冻结向量、候选、已存排序结果或测试替身检查算法和接口；真实召回与新排序模型效果另测 | 离线检查0次 |
| 提示词或生成模型 | 先分析已有失败，再对获准的小样本生成新版答案，按固定要点核对 | 另行授权 |

第一阶段证据包已保存600份原始生成、最终回答与模型消息，可用于生成后处理的离线回放，见[第一阶段评测](validation/phase1-context-300-20261116.md)。原始输出重放能验证处理代码；提示词、证据或模型输入改变后，生成质量需要新的真实输出。

### 小样本与答案要点

1. 从已有结果提取具体失败类型，固定“必须回答的要点、证据、适用条件、禁止操作”，先修复可离线确认的问题。
2. 开发集包含目标失败用例；验收集另行冻结，混入正常题、资料不足题和风险题，避免只检查修好的例子。
3. 确需真实生成时，从10～20题的小批量方案起步，实际数量以获准预算为准。输入与配置相同的基线答案直接复用；旧生成与新生成分批取得时记录模型配置与时间，避免将时段差异直接归因于改动。
4. 对照固定要点逐条核对是否答全、事实是否受证据支持、引用是否对应，以及是否出现不当建议。日常回归不调用付费评审模型，也不安排全量交换顺序复评。
5. 报告通过数、遗漏要点和退化案例。小样本用于定位与验收具体改动；扩大样本或估计整体提升时，单独设计并批准评测。

### 缓存与复用

复用前核对模型标识、生成参数、系统提示、完整历史、本轮问题和证据内容；这些输入及配置全部相同时，才可复用原始生成。保存内容哈希与原始响应，不覆盖历史记录。生成后的处理代码改变时，可重用原始生成并重新渲染；答案、来源或评分规则改变时，已有评分需要重新核对。缓存命中与新增调用分别记录，调用结果的缓存复用不等于提供商的Token缓存折扣。

### 付费测试的预算约定

- 允许必要的少量真实调用，在已批准的次数和费用额度内自主安排；尚无明确额度时，先列明用途、模型、小样本数量、含重试的总调用上限、输入/输出上限及预计费用并取得预算。批量脚本未提供预算时不自动发送付费请求。
- 生成、评审、Embedding、rerank统一计数；SDK自动重试和失败请求占用调用额度，取消请求不假定免费。预算按输入上限、输出上限、最大尝试次数及运行时价格估算。
- 调用前核对剩余额度，达到调用、Token或费用上限即停止；不自动扩样、续跑缺项或增加模型复评。成功结果保存为检查点，后续只处理获准的缺项。
- `evaluation.evaluate`和`evaluation.benchmark`的付费阶段已接入请求级预算：必须同时传入`--allow-paid`和`--budget FILE`。缺少任一项时在执行付费阶段前退出；直接调用付费函数也需要有效预算上下文。下文付费命令用于有预算的专项复现，不作为日常回归步骤。

### 请求级预算

预算上下文在独立评测进程内使用，HTTP拦截作用于该进程，不在业务服务进程中开启。运行器在同步`httpx`和`requests`的HTTP发送前预留额度。失败和SDK级重试各算一次请求；底层连接适配器自动重试在运行期间关闭并在结束后恢复。所有线程共享一份加锁计数；耗尽时停止新请求并取消排队任务，已在途请求占用的额度已预留。

| 字段 | 单位及含义 |
|---|---|
| `max_calls` | 总HTTP尝试次数，失败与重试均计入 |
| `max_input_bytes` | 累计序列化请求UTF-8字节，消息请求每条消息另加256字节、其他请求另加256字节；精排还重复计入每个候选的问题 |
| `max_output_tokens` | 累计按请求`max_tokens`预留的输出额度 |
| `max_output_tokens_per_call` | 每次生成的输出上限；请求未指定或超过该值时拒绝发送 |
| `max_estimated_cost_cny` | 按下面的批准价格累计预留的预计人民币金额 |
| `models` | 允许模型，以及每百万输入/输出Token的批准单价 |

输入字节作为保守Token代理参与费用预留，输出按请求上限计费预留，失败不返还额度，也不预扣缓存折扣。该金额是本次请求的估算配额；精确输入Token和真实账单另行核对。当前支持中国内地域名`dashscope.aliyuncs.com`上的同步文本生成、文本Embedding和精排；未知模型、其他地址、富媒体、工具调用及异步请求拒绝执行。它只约束这两个评测入口，不修改正常业务服务。

获得本轮授权后，使用新的预算文件。下面的价格和模型名为待填写字段，未替换会被拒绝；数值仅示范结构：

```json
{
  "max_calls": 10,
  "max_input_bytes": 100000,
  "max_output_tokens": 10240,
  "max_output_tokens_per_call": 1024,
  "max_estimated_cost_cny": "1.00",
  "models": {
    "APPROVED_MODEL_ID": {
      "input_per_million_cny": "APPROVED_INPUT_PRICE",
      "output_per_million_cny": "APPROVED_OUTPUT_PRICE"
    }
  }
}
```

示例运行形式：`python -m evaluation.benchmark answer --root evaluation/results/run-01 --allow-paid --budget approved-run-01.json`。程序独占创建旁边的`approved-run-01.json.usage.json`，每次发送前落盘；同一文件不能重复使用或被两个进程同时开启。后续阶段及恢复缺项使用新批准的预算文件，保留旧账本。账本仅保存模型、请求数、预留量和预算哈希，不保存请求内容、密钥或授权头。归档中的历史runner属于证据快照，新的付费运行使用当前受控入口。

控制回归使用替代HTTP传输并阻断网络：

```bash
python -m pytest tests/test_evaluation_budget.py tests/test_answer_coverage.py -q
```

预算控制与上下文边界的合并验证见[综合离线验收](validation/context-budget-20261120.md)。

## 后端测试

在 `services/backend` 执行：

```bash
python -m pytest -q
```

默认跳过数据库集成测试。其余用例覆盖 API、SSE、来源字段、风险分支、分词、编号、RRF 去重、缓存刷新、并发和依赖方向。

### 上下文消息回归

```bash
python -m pytest tests/test_context.py tests/test_internal_rag.py tests/test_rerank.py tests/test_api.py -q
```

用例检查不同轮次的系统提示词相同、本轮 JSON 资料与 SSE 来源一致，以及引号、花括号、换行和资料中的指令式文本仍作为数据传递。多轮用例还验证历史保留原生消息角色，保存的是用户原始问题，并为新问题提供本轮参考资料。这些检查使用替代模型验证消息契约；回答效果按独立评测比较。

条目整理用例显式启用独立开关，检查边缘条目恢复、条件与否定词保留、章节重复编号、版本绑定的排除、全排除拒答、无法定位时的原文回退、行号溯源及关闭开关后的兼容行为。

### 冻结证据保留审计

```bash
python -m evaluation.audit_context --repo ../.. --output evaluation/results/context-fidelity-01.json
```

程序读取现有 300 题证据包和当前 TXT，检查全部 63 个片段的条目定位、审校排除、原文行号与引用编号，并核对原前四中已经存在的正常目标证据是否保留。运行不访问数据库和模型，输出已存在时拒绝覆盖。该审计验证证据处理，结果见[证据整理验证](validation/evidence-context-20261115.md)；同候选真实模型对照见[20题回答与用量报告](validation/evidence-context-20-20261115.md)，证据包可离线复算。

### 第一阶段完整上下文构建

```bash
python -m pytest tests/test_context.py tests/test_prompt_context.py tests/test_internal_rag.py -q
python -m evaluation.audit_phase1 --repo ../.. --output evaluation/results/phase1-fidelity-01.json
```

审计使用同一300题和冻结的精排前四，不调用模型或数据库。检查条目去重、完整条件、问题相关性优先选择、证据与总输入预算、原文行号以及审校排除。测试另外覆盖 JSON 转义及多字节字符、完整历史轮次、会话隔离、禁止操作与后续免责声明、引用组规范和无有效引用处理。历史与原TXT不改写。

完整实现和真实回答对比见[第一阶段300题评测](validation/phase1-context-300-20261116.md)。证据包包含600份原始生成与最终回答、两轮全量评分和离线汇总脚本；同候选比较将生成完整性、回答质量、引用支持、风险子集、Token与延迟分别统计。

### 原始回答的离线回放

```bash
python -m pytest tests/test_answer_coverage.py -q
python -m evaluation.replay_answers --archive ../../docs/validation/phase1-context-300-20261116-v1.tar.gz --output evaluation/results/answer-coverage-01.json
```

回放从证据包读取300份新版原始生成，通过当前实际`RagService`处理；Embedding、召回和生成使用冻结资料与测试替身，并在执行期间阻断socket连接。程序校验所读成员的SHA-256、全部模型消息与来源一致性，以及保存历史等于可见回答；输出逐题前后文本、改动题号与风险题变化，既有输出不覆盖。

结果用于验证生成后处理，没有重新生成或沿用旧评分给新答案打分。[步骤覆盖回归报告](validation/answer-coverage-20261120.md)记录已确认恢复的要点和保持不变的风险用例。

增量修改还覆盖部分动作遗漏、重复动作的不同对象、跨结论动作已齐全、条件已满足或存在禁止语句，以及相邻动作词的空对象误判。对比上一阶段的逐题可见回答，而非沿用旧评分；[部分步骤增量回归](validation/partial-answer-coverage-20261120.md)保留父报告哈希及全部前后文本。

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

本节会产生查询嵌入用量，按上述预算约定授权后，在 `services/backend` 配置可用数据库和模型密钥并执行：

```bash
python -m evaluation.evaluate --output evaluation/results/run-01.json --allow-paid --budget approved-retrieval.json
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

本节会产生查询嵌入和精排用量，须单独纳入获准预算。

```bash
python -m evaluation.evaluate --rerank --output evaluation/results/rerank-01.json --allow-paid --budget approved-rerank.json
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

全量流程用于专项复现；日常改动优先采用上述离线回归和获准的小样本，不默认执行本节。

新建结果目录，先绑定本机数据库的 UUID。绑定只查询数据库，不导入、不修改题目或参考答案；要求当前资料和切块内容与发布快照相同，内容有变化时拒绝将其当成同语料复现。

```bash
python -m evaluation.benchmark bind --template evaluation/results/reference-300 --root evaluation/results/run-300
python -m evaluation.benchmark retrieve --root evaluation/results/run-300 --allow-paid --budget approved-retrieve.json
python -m evaluation.benchmark answer --root evaluation/results/run-300 --workers 4 --allow-paid --budget approved-answer.json
python -m evaluation.benchmark judge --root evaluation/results/run-300 --workers 4 --allow-paid --budget approved-judge.json
python -m evaluation.benchmark audit --audit-limit 300 --root evaluation/results/run-300 --workers 4 --allow-paid --budget approved-audit.json
python -m evaluation.summarize_benchmark --root evaluation/results/run-300 --output evaluation/results/run-300-summary.json
```

完整流程包含 300 次查询嵌入、最多 300 次排序、600 份回答和两轮各 300 次成对评分，失败重试可能增加调用。需要账户能调用 `qwen-plus`、`qwen-max` 与配置中的嵌入和排序模型；生成与评审固定 temperature=0、seed=20261111。模型别名、服务版本和网络状态可变，重跑不承诺相同生成文本。

程序按条目保存成功结果，同一个结果目录可续跑，既有题目、回答和分数不会被替换。中断写入造成的损坏文件需要先保留原件并核对，不应当作已完成结果；不要在同一目录并行运行两个相同阶段。

`prepare / generate / validate / freeze` 用于创建新题集，不属于复现既有分数的必要步骤。它们会生成新问题与参考答案，需要先检查标签并冻结，再运行系统；禁止看过结果后调整标签以提升报告数值。原始模型检查说明也可能不准确，不能当作人工审校记录。
