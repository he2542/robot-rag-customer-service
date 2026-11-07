# 后端代码导航

这是按功能组织的模块化单体。Router / Schemas / Service / Repository 表示职责分层，不是完整 DDD，也没有为每张表创建无实际用途的实体与仓储接口。

```text
backend/
├── src/robot_rag/
│   ├── main.py                   # FastAPI 组装与路由注册
│   ├── config.py                 # 配置；仍读取 backend/.env
│   ├── dependencies.py           # 服务创建与 FastAPI 依赖注入
│   ├── modules/
│   │   ├── chat/
│   │   │   ├── router.py         # POST /api/chat，HTTP 和 SSE
│   │   │   ├── schemas.py        # ChatRequest：输入与会话 ID 校验
│   │   │   └── service.py        # 问答前置条件、调用 RAG
│   │   ├── rag/
│   │   │   ├── service.py        # RAG 主流程：检索→上下文→生成→来源
│   │   │   └── prompts.py        # 系统提示词
│   │   ├── knowledge/
│   │   │   ├── router.py         # GET /api/knowledge，关闭上传入口
│   │   │   ├── schemas.py        # 公开知识库状态
│   │   │   ├── service.py        # 切块、批量嵌入、导入与就绪状态
│   │   │   ├── retriever.py      # 查询嵌入、调用仓储、转换 Document
│   │   │   ├── repository.py     # 知识表 SQL：去重、入库、统计、检索
│   │   │   ├── corpus.py         # TXT 读取与版本身份
│   │   │   └── legacy_vector_store.py # 旧检索适配器，仅兼容测试使用
│   │   └── health/
│   │       ├── router.py         # GET /api/health
│   │       └── schemas.py        # 公开健康状态
│   ├── shared/
│   │   ├── database.py           # 连接、嵌入配置兼容性
│   │   ├── schema.py             # 显式建表，不在启动时运行
│   │   ├── history.py            # 文件会话历史
│   │   └── sse.py                # SSE 编码
│   └── cli/                      # 管理员命令实现
├── scripts/
│   ├── import_knowledge.py       # 导入入口；默认仅预览
│   └── init_database.py          # 显式初始化数据库
├── tests/
├── pyproject.toml
├── api.py                        # 旧启动命令的薄兼容入口
├── database.py                   # 旧初始化命令的薄兼容入口
└── import_knowledge.py           # 旧导入命令的薄兼容入口
```

## 调用关系

前端 → chat/router → chat/service → rag/service → knowledge/retriever → knowledge/repository → PostgreSQL。

RAG 主流程再把召回结果与历史交给模型，按原协议流式返回。Router 不写 SQL、不拼接提示词；Repository 不处理 HTTP、不调用生成模型；Schemas 只定义接口契约。现在直接使用 psycopg 和 pgvector，因此没有 ORM models.py；将来确实引入 ORM 时再添加数据库模型。

## 你后续优化 RAG 时从哪里改

| 要修改的内容 | 主要文件 |
|---|---|
| RAG 整体流程、历史上下文、来源编号 | `src/robot_rag/modules/rag/service.py` |
| 提示词 | `src/robot_rag/modules/rag/prompts.py` |
| 检索编排、查询向量 | `src/robot_rag/modules/knowledge/retriever.py` |
| SQL 检索与持久化 | `src/robot_rag/modules/knowledge/repository.py` |
| 导入切块与嵌入 | `src/robot_rag/modules/knowledge/service.py` |
| 现有参数及模型选择 | `src/robot_rag/config.py` |

## 运行与验证

在 `backend` 目录执行：

```bash
python -m uvicorn robot_rag.main:app --app-dir src --host 127.0.0.1 --port 8000
python scripts/import_knowledge.py
python -m pytest -q
```

PyCharm 的 module 填 `uvicorn`；参数填 `robot_rag.main:app --app-dir src --host 127.0.0.1 --port 8000`；工作目录填本地 `backend`，SSH 映射到服务器 `backend`。若使用本次私有预览服务，端口是 8120，避免重复占用。

旧的 `uvicorn api:app`、`python import_knowledge.py`、`python database.py` 仍通过薄入口转到新包。正式编辑请进入 `src/robot_rag`，不要把业务代码写回兼容入口。

可选：安装完依赖后执行 `python -m pip install -e . --no-deps`，便可不依赖工作目录导入包，并使用 `robot-rag-import` 和 `robot-rag-init-db` 命令。此项不是上述启动方式的前置条件。

管理员确认目标数据库后，才执行 `python scripts/init_database.py` 或给导入命令加 `--apply`。数据库集成测试会清理独立测试库，必须先按 README 设置测试专用连接，不能指向开发业务库或生产库。

## 范围

这次整理目录与依赖关系，保留原有检索参数、资料哈希、63 个向量片段、历史目录和前端接口。混合检索、精排、问题改写、评估调优尚未实施。公开上线前仍需内容审校、身份认证、会话归属和限速，不能因代码已分层就直接视为具备上线条件。
