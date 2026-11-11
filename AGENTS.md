# RAG 项目约定

- 用户选择“笔记本管理”式技术分层。前后端分别在 services/backend 与 services/frontend；不要重新改为每个功能一套 modules 结构或引入完整 DDD。
- routes 处理 HTTP，schemas 定义契约，services 处理 RAG/导入/检索业务，crud 写参数化知识 SQL，database 负责连接和显式建表。业务和数据层不依赖 routes/FastAPI，路由不写 SQL。
- RAG 策略由用户逐步优化；目录重构不能顺带改变模型、向量空间、切块、top-k、提示词或数据身份。不要创建空层、空模型或仅为转发的兼容入口。
- 依赖在 services/backend/pyproject.toml 声明，constraints.txt 记录已验证版本；前端依赖在 package.json，使用现有锁文件。未经任务需要不增加框架或工具链。
- .env、runtime、私钥与凭据不得提交或输出；必要诊断只读取最小范围并脱敏。不修改原始资料、业务库、现有历史或生产服务，除非用户当前任务授权。
- 唯一活动台账为 docs/backlog.md；历史证据放 docs/validation，旧部署等放 docs/archive，不并行维护第二份台账。
- 运行测试见 docs/testing.md。数据库测试只用受保护名称的一次性测试库；不要对开发业务库或生产库运行清理 fixture。
- 保留用户编辑，重要迁移先备份。用户自行学习 Git，未明确要求时不替用户提交、推送、切换分支或重置历史。
