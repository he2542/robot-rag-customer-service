# 测试

后端：在 services/backend 执行 python -m pytest -q。未设置 RAG_RUN_DB_TESTS 时跳过数据库集成测试，其余测试使用替身，不调用付费模型。

数据库集成测试必须指向一次性独立数据库 robot_rag_test 或已有兼容测试库名 robot_rag_test_internal_20261107，设置 DATABASE_URL 和 RAG_RUN_DB_TESTS=1，先启用 vector 扩展。测试会清空测试知识表，禁止连接业务库或生产库。CI 使用独立 PostgreSQL 服务。

前端：在 services/frontend 执行 npm test、npm run build。测试覆盖 UTF-8 与 SSE 跨分包、截断、错误，以及会话沿用、来源与回答更新、未就绪阻止发送、中止和重复发送。

tests/test_architecture.py 检查 routes 不直接导入 SQL/提供方，业务/数据层不依赖 HTTP，数据层不反向依赖业务。不以文件行数或目录数作为架构验收标准。

真实模型抽查只用于运行连通性，不替代召回/引用质量评估或完整性能、成本测试。历史验证记录与新验证记录分开保存于 validation。
