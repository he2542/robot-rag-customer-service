# 历史设计：按功能模块分层

本文件说明早期 `src/robot_rag/modules` 布局，保留用于理解架构演进，不适用于当前目录和启动命令。

早期后端按 chat、rag、knowledge、health 组织功能模块，模块内区分 Router、Schema、Service 和 Repository，并保留根脚本兼容入口。该方案把业务流程与 HTTP 分离，但对当前规模增加了文件跳转和重复入口。

当前版本改为技术职责分层，统一管理员 CLI，清理兼容转发。当前规范见 [技术分层说明](technical-layers_design.md) 与 [项目架构](../architecture.md)。功能模块化和技术分层并无普遍优劣，实际边界由依赖关系与职责决定。
