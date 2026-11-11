# 技术分层说明

后端按 `routes / schemas / services / crud / database` 划分技术职责，前端按 `views / components / api / store / assets` 组织。该布局服务于当前单体应用，不引入聚合、领域事件或额外微服务。

RAG 主流程和提示词分别位于 `services/rag.py`、`services/prompts.py`；检索、关键词索引与导入各有明确入口。SQL 集中在 CRUD 层，路由不拼装模型链，公开 Schema 不作为数据库实体。

管理员功能由 `src.cli` 统一实现。安装项目后提供 `robot-rag` 命令；当前版本不保留根目录脚本和多重转发入口。后端依赖在 `pyproject.toml` 声明，前端保持现有 Vue 响应式状态方案。

当前调用图、目录与具体文件见 [架构](../architecture.md)，开发命令见 [后端](../backend.md) 和 [前端](../frontend.md)。
