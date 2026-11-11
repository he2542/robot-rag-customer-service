# 架构归档：功能模块布局

旧版将 chat、rag、knowledge、health 放在 `src/robot_rag/modules` 下，并保留根脚本和 scripts 兼容入口。该布局已退出当前实现，此文仅说明历史结构。

当前前后端位于 `services/`，管理员入口统一为 `src.cli`，不要依据旧版包路径启动应用。参见 [当前架构](../architecture.md) 和 [后端开发](../backend.md)。
