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
- `evaluation.evaluate`、`evaluation.benchmark`和`evaluation.intent_workflow answer`已接入请求级预算：必须同时传入`--allow-paid`和`--budget FILE`。缺少任一项时在执行付费阶段前退出；直接调用付费函数也需要有效预算上下文。下文付费命令用于有预算的专项复现，不作为日常回归步骤。

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

输入字节作为保守Token代理参与费用预留，输出按请求上限计费预留，失败不返还额度，也不预扣缓存折扣。该金额是本次请求的估算配额；精确输入Token和真实账单另行核对。当前支持中国内地域名`dashscope.aliyuncs.com`上的同步文本生成、文本Embedding和精排；未知模型、其他地址、富媒体、工具调用及异步请求拒绝执行。它只约束上述评测入口，不修改正常业务服务。

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

维护周期条目使用 `python -m pytest tests/test_maintenance_cycles.py -q` 验证，覆盖部件与条件混用、完整问答、来源歧义、重复条目及危险操作过滤。回放结果见[维护周期完整条目测试](validation/maintenance-entries-20261124.md)；缺编号正文恢复及70份离线增量复核见[维护条目恢复验证](validation/maintenance-numberless-20261127.md)。

后处理的正确率验证以最近有效评分版本为起点，查找累计受影响答案，对新旧可见回答按同一标准复核后汇总。仅在答案和评分标准均未改变时复用原标签；评分来源有变化时明确标记。完整示例与离线复算包见[维护周期效果对照](validation/maintenance-quality-20261124.md)。

### Codex订阅离线评测

`evaluation.codex_validation` 提供 `generate`、`judge`、`summarize`，通过本机原生Codex CLI复用ChatGPT登录。该入口独立于线上服务和LangChain集成，不安装Python SDK，不调用阿里云接口。[CLI非交互调用](https://learn.chatgpt.com/docs/non-interactive-mode)支持标准输入、JSONL事件和JSON Schema输出。

安装官方CLI并执行 `codex login`；Windows的 `--codex-bin` 必须指向原生 `codex.exe`，不能指向 `.cmd`、`.bat` 或 `.ps1` 启动器。官方独立CLI `0.172.0` 已通过工具隔离、真实生成与评分验收，配置和结果见[接入验证](validation/codex-offline-integration-20261125.md)。自动测试使用替代进程，不需要CLI或登录。

在 `services/backend` 执行，`evidence/independent50` 为已解压的[50题证据包](validation/maintenance-independent-50-20261124.md)：

```bash
python -m evaluation.codex_validation generate --source evidence/independent50 --output evaluation/results/codex20 --prepare-only
python -m pytest tests/test_codex_evaluation.py -q
```

准备操作验证源文件哈希，按类别和题号各取4题，冻结20题。生成器只收到原问题消息与资料，不包含答案要点或旧答案。判分默认评审已有Qwen基线回答，可按需用 `--judge-target generated` 评审生成结果；后者属于同模型自评，汇总单独计数。

订阅任务预算文件示例（需为本次运行明确批准额度）：

```json
{
  "max_tasks": 10,
  "max_input_bytes": 163840,
  "max_input_bytes_per_task": 16384,
  "timeout_seconds": 120,
  "stages": {"generate": 5, "judge": 5}
}
```

```bash
python -m evaluation.codex_validation generate --source evidence/independent50 --output evaluation/results/codex20 --ids n001,n011,n021,n031,n041 --allow-subscription --budget evaluation/results/subscription-budget.json --codex-bin /path/to/codex
python -m evaluation.codex_validation judge --source evidence/independent50 --output evaluation/results/codex20 --ids n001,n011,n021,n031,n041 --allow-subscription --budget evaluation/results/subscription-budget.json --codex-bin /path/to/codex
python -m evaluation.codex_validation summarize --output evaluation/results/codex20
```

真实任务前检查订阅登录、管理配置要求的实际提供方、模型可见输入与可用模型。固定本地模型目录中的工具元数据，逐个禁用已配置MCP，并关闭交互提问等工具；预检发现额外工具时停止。保留用户全局规则，核验其内容与哈希，拒绝来源不明的继承指令。预检不生成回答、不预留任务；真实执行后发生的失败仍消耗一次额度。模型取账户目录中优先级最高的可用项，或使用显式 `--model` 固定型号；low推理强度与模型目录、规则、CLI二进制及适配器哈希绑定，任务失败后不自动更换。

每个任务使用临时工作目录和独立临时会话，评测脚本串行执行，默认不重试。任务在启动前预留额度；失败、超时或中断不退还，随后停止。预算旁生成 `.usage.json` 和运行期间的排他 `.lock`；完整成功检查点可在同配置下继续使用，未完成预留按失败处理。异常退出遗留锁时先确认旧进程已结束，再人工处理，程序不会自动抢锁。

缓存绑定完整任务输入、输出Schema、任务类型、模型、推理配置和版本；汇总校验原始CLI事件与最终结果。`summarize` 完全离线，分别报告生成数量、旧答案评分一致性与同模型自评数量。不同评审对同一答案的通过率差异属于评分差异，回答质量提升需要独立评审。

输入字节限额覆盖任务正文、用户全局规则及固定评测基础指令；CLI消息封装另有开销。最终输出超过16 KiB、事件输出超过2 MiB时拒绝作为有效结果，这些是验收边界，不是底层Token硬限额。账本记录可取得的Token、缓存Token、时长和结果字节；订阅任务可能含多次底层请求或CLI内部重试。评测层不重试、不切换API Key、不购买额度、不回退Qwen。阿里云费用和Codex订阅用量分别记账。

### 独立回答质量比较

`evaluation.codex_quality`以同后处理策略的已有Qwen回答为基线，用Qwen-Max独立评分Codex生成；Codex对旧答案的评分一致性单列。准备时核验基线资料、策略及原评分输入哈希；评分与汇总要求完整20题，缺题、输入变化、截断和非法判分会停止。单次失败保存记录，禁止自动重试。

```bash
python -m evaluation.codex_quality prepare --source evaluation/results/codex20 --baseline-source evidence/independent50 --root evaluation/results/codex20-quality
python -m evaluation.codex_quality judge --root evaluation/results/codex20-quality --allow-paid --budget evaluation/results/qwen-judge-budget.json
python -m evaluation.codex_quality summarize --root evaluation/results/codex20-quality
```

评分沿用Qwen-Max、固定seed、每次512输出Token及16 KiB输入，付费阶段使用已有`evaluation.budget`，需单独批准额度。生成模型变化的比较复用原基线评分，报告注明评分时段；完整结果见[20题独立质量比较](validation/codex-quality-20-20261127.md)：13/20→16/20，评分一致性13/20；维护类退化与评分争议单列。

新问题的统一模型验收使用 `evaluation.postprocess_validation`：固定问题、必要要点、完整证据和两版后处理，Qwen-Plus每题生成一次，Qwen-Max隐藏版本逐份评分；本轮完全相同评分输入按请求哈希共享，旧标签不参与。50题结果为39/50→39/50，调用与逐题证据见[独立对照报告](validation/maintenance-independent-50-20261124.md)。

```bash
python -m evaluation.postprocess_validation --help
python -m pytest tests/test_postprocess_validation.py -q
```

入口分为 `prepare`、`validate`、`run`、`summarize`。准备阶段冻结数据、消息、代码与评分标准；付费运行需要显式 `--allow-paid --budget`，有效检查点按哈希复用，预算耗尽即停止。证据包内的 `recompute.py` 使用标准库离线重算，不产生模型用量。

```bash
python -m pytest tests/test_answer_coverage.py -q
python -m evaluation.replay_answers --archive ../../docs/validation/phase1-context-300-20261116-v1.tar.gz --output evaluation/results/answer-coverage-01.json --archived-prompt
```

回放从证据包读取300份新版原始生成，通过当前实际`RagService`处理；Embedding、召回和生成使用冻结资料与测试替身，并在执行期间阻断socket连接。程序校验所读成员的SHA-256、全部模型消息与来源一致性，以及保存历史等于可见回答；输出逐题前后文本、改动题号与风险题变化，既有输出不覆盖。

提示版本改变后，`--archived-prompt`明确使用原始生成对应的系统规则，只验证当前后处理。未传该参数时检查当前提示与原生成消息完全相同；不同就拒绝将旧输出用于新提示的验证。

结果用于验证生成后处理，没有重新生成或沿用旧评分给新答案打分。[步骤覆盖回归报告](validation/answer-coverage-20261120.md)记录已确认恢复的要点和保持不变的风险用例。

增量修改还覆盖部分动作遗漏、重复动作的不同对象、跨结论动作已齐全、条件已满足或存在禁止语句，以及相邻动作词的空对象误判。对比上一阶段的逐题可见回答，而非沿用旧评分；[部分步骤增量回归](validation/partial-answer-coverage-20261120.md)保留父报告哈希及全部前后文本。

### 20题生成流程对照

此实验只改变第一阶段系统提示的回答流程；候选、来源构建、后处理、模型参数和空历史一致。每文件4题，覆盖遗漏、条件、风险、参数与长度问题；基线与优化版交替先生成，避免固定先后顺序。

该实验提示已撤回，当前默认提示与`3897dd4`相同。以下准备命令用于存在不同候选提示时的新对照；当前执行会以`Prompts are identical`退出并保留输入目录未创建。复现历史实验使用其冻结证据包中的源码与输入，避免改写现有工作区。历史结果仍保留；回退只做离线验证，不追加真实调用。

先离线冻结40份消息及来源、20题审读要点、协议和源码哈希：

```bash
python -m evaluation.intent_workflow prepare --archive ../../docs/validation/phase1-context-300-20261116-v1.tar.gz --root evaluation/results/intent-20 --baseline-ref 3897dd4
python -m evaluation.intent_workflow validate --root evaluation/results/intent-20
```

准备阶段需本地Git中存在指定基线提交，历史提示通过AST提取，不执行历史代码。基线20份消息还须匹配原证据包，两个版本来源逐题相同。改动源码或冻结输入后，验证会拒绝继续。

取得本轮预算后才运行真实生成：

```bash
python -m evaluation.intent_workflow answer --root evaluation/results/intent-20 --allow-paid --budget approved-intent-20.json
```

预案为20题×两版，最多40次尝试；Qwen-Plus非思考，输出上限1024。保持每份结果独立空历史，记录原始JSON、可见回答、用量、结束原因、耗时和消息/协议哈希。已完成的有效检查点复用，失败记录保留，不追加付费评审、Embedding或精排。原始结论的要点覆盖与最终可见回答分别按冻结要点核对，超长截断计入未完成。准备及效果记录见[生成流程验证](validation/intent-workflow-20261120.md)。

### 离线汇总20题结果

限制类引句恢复使用`python -m pytest tests/test_quote_recovery.py -q`，覆盖完整原文、否定/数字/部件改变、来源歧义、原有连续引句、故障题拒绝和危险动作。再回放原40份与300份输出，检查消息、来源及保存历史，逐份比较所有改变。[当前恢复结果](validation/quote-recovery-20261122.md)记录适用范围。

操作边界修改优先运行`python -m pytest tests/test_operation_boundaries.py -q`，再用原40份和300份输出回放。比较完整消息、来源、可见回答及保存历史，逐项审读所有变化；只更新本次实际验证的行为，不沿用旧质量分数。[操作边界回归](validation/operation-boundaries-20261122.md)记录当前结果。

20题真实生成的固定要点评审可完全离线汇总：

```bash
python -m evaluation.summarize_intent --root evaluation/results/intent-20 --review review.json --output evaluation/results/intent-summary.json
```

`review.json`须逐题记录原始结论和最终回答的要点布尔值、证据支持、操作边界及未通过原因，并绑定答案SHA-256。汇总前核对冻结输入和源码、完整20题、结束原因及Token字段，拒绝篡改后的检查点；截断计为未通过。[真实配对报告](validation/intent-workflow-live-20-20261121.md)提供可独立解压复算的证据包。

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

并列提问补全使用 `python -m pytest tests/test_answer_coverage.py -q` 验证，70份真实输出的离线效果见[并列问答补全验证](validation/multipart-qa-20261127.md)。


上下文提示词的定向筛查、双轮配对评分及人工敏感性复核见[20题提示词筛查](validation/context-prompt-screen-20-20261127.md)。候选仅用于评测，完整证据包支持离线复算。

电池操作边界与原文条目导航的完整回放、预算和被否定方案对照见[电池边界与导航验证](validation/context-guard-navigation-20261127.md)。导航默认关闭，新的模型输入须完成真实生成效果验证。


### 成功任务的Token费用核算

纯文本评测预算可显式设置 `settle_successful_usage: true`。发送前仍预留整次请求；驱动校验成功输出后调用 `budget.settle_successful_result(result)`，以API返回的input/output Token和预算约定单价核算，释放未使用的金额预留。失败或未完成任务保留完整预留，调用数、输入字节及输出Token上限始终累计。

收据绑定请求尝试编号和完整请求哈希，拒绝重复收据、异常用量和不匹配的输入。账本分别保存当前金额占用、历次预留总和及已核算金额；缓存折扣不扣减，结果按原价估算，与实际账单分别记录。未启用此选项时保持原预算行为。

价格依据：[Qwen-Plus模型信息](https://help.aliyun.com/zh/model-studio/qwen-plus)、[Qwen-Max模型信息](https://help.aliyun.com/zh/model-studio/qwen-max)。


### 上下文候选300题验收

[最新验收记录](validation/context-phase1-acceptance-20261128.md)比较原主分支真实回答与条目导航、完整原句展示候选：首轮261→257/300，引用支持177→281/300。交换顺序复评返回237份、有效236份，随后HTTP 500按无重试约定停止。原始标签、无效格式、风险审读、费用收据和标准库复算均随证据保存；该候选未达到合并条件。
