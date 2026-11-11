# Robot RAG Customer Service

基于 **Vue 3、FastAPI、LangChain、PostgreSQL + pgvector** 的扫地机器人知识问答示例，支持中文混合检索、来源展示和 SSE 流式回答。

用户直接提问，管理员通过命令行维护内置 TXT 资料。项目适合学习 RAG 的知识入库、检索、生成与评测流程。

## 功能

- **混合检索**：向量召回与中文 BM25 各取 10 个片段，按片段 ID 去重，经 RRF 融合后取前 4 个作为上下文。
- **可切换检索模式**：支持 `hybrid`、`vector`、`keyword`，便于比较和回归。
- **资料版本管理**：相同版本重复导入会跳过，只检索当前文件版本，排除历史上传和旧版本。
- **流式问答与来源展示**：先返回参考片段，再流式返回回答；支持多轮会话、请求中止和异常状态。
- **可复现测试与初步评测**：包含 API、检索、数据库隔离测试和固定问题集。

参考片段是检索候选，不能据此认定回答中的每句话都已获得证据支持。当前未接入模型 rerank。

## 快速开始

需要 Python 3.10+、Node.js 20+、PostgreSQL（启用 pgvector）和可用的 DashScope API Key。

### 1. 安装后端

在仓库根目录执行：

```bash
cd services/backend
python -m venv .venv
```

激活虚拟环境：Linux/macOS 使用 `source .venv/bin/activate`；Windows PowerShell 使用 `.\.venv\Scripts\Activate.ps1`。

```bash
python -m pip install -e . -c constraints.txt
```

将 `.env.example` 复制为 `.env`，配置 `DATABASE_URL` 和 `DASHSCOPE_API_KEY`。默认嵌入模型为 `text-embedding-v4`、1024 维，聊天模型为 `qwen-plus`；模型需在所用账号中可用。

### 2. 初始化并导入资料

先创建专用数据库和业务角色，由数据库管理员在目标库执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

在 `services/backend` 执行：

```bash
python -m src.cli init-db
python -m src.cli import-knowledge
python -m src.cli import-knowledge --apply
```

导入命令默认只预览；`--apply` 才会调用嵌入模型并写库，产生相应 API 用量。资料默认从 `knowledge/robot/` 读取。

### 3. 启动应用

后端，在已激活环境的 `services/backend` 终端执行：

```bash
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

前端，另开终端，在仓库根目录执行：

```bash
cd services/frontend
npm ci
npm run dev
```

打开 [聊天页面](http://localhost:5173) 或 [API 文档](http://127.0.0.1:8000/docs)。Vite 默认将 `/api` 代理到后端的 8000 端口。

## 项目结构

```text
services/
├── backend/
│   ├── src/          # routes / schemas / services / crud / database
│   ├── tests/        # 单元、API 与数据库集成测试
│   └── evaluation/   # 固定问题集与检索对比程序
└── frontend/
    └── src/          # views / components / api / store / assets
knowledge/robot/      # 示例 TXT 资料
docs/                 # 架构、开发、设计与评测说明
deploy/               # 部署说明与服务配置样例
runtime/              # 本地会话数据，不纳入版本控制
```

## 评测概览

在 24 道项目自建题中，指定证据片段进入前 4 条的命中数为：纯向量 **10/24**、BM25 **13/24**、混合检索 **14/24**。该题集仅覆盖 3/5 份资料，相关性标注不穷尽；这些结果不是最终回答准确率，也不代表生产性能。

评测方法、逐题结果与限制见 [混合检索评测](docs/validation/hybrid-retrieval-20261111.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [架构](docs/architecture.md) | 目录、调用关系与代码入口 |
| [后端开发](docs/backend.md) | 配置、管理员命令、API 与检索模式 |
| [前端开发](docs/frontend.md) | 组件、状态和 SSE |
| [测试与评测](docs/testing.md) | 测试环境、固定题集与复现方式 |
| [混合检索设计](docs/specs/hybrid-retrieval_design.md) | 分词、BM25、缓存与 RRF |
| [资料说明](knowledge/README.md) | 示例资料的来源和适用范围 |
| [部署](deploy/README.md) | 构建、运行与公开部署条件 |
| [路线图](docs/backlog.md) | 已实现能力与后续工作 |

## 适用范围

内置资料来自课程示例，非品牌官方手册，未完成专业审校。涉及参数、保修、型号及维修建议时，应核对对应品牌官方资料。风险关键词规则和提示词不能保证识别所有危险问题。

当前应用面向本地开发与受控演示，尚未实现应用级身份认证、会话归属校验和请求限速。随机会话 ID 不构成身份认证。公开部署前请阅读 [安全说明](SECURITY.md)。

贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，许可证见 [LICENSE](LICENSE)。
