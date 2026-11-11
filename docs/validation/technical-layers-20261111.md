# 技术分层迁移验收（2026-11-11）

已完成 services/backend 与 services/frontend 迁移，后端按 routes/schemas/services/crud/database 分层；前端拆分 views/components/api/store/assets。统一 CLI，依赖声明归入 pyproject.toml，旧配置和资料归档。RAG 参数和协议保持基线。

31 项后端测试在独立 PostgreSQL 库通过；9 项前端测试通过，构建通过；本地 editable 包和 robot-rag import-knowledge 入口通过。实际模型问题、订单边界、风险提示 SSE 完成；浏览器实际发送得到回答及四个来源。五份/63 片段不变，重复导入全部跳过。原始资料、提示词、样式和既有历史未改变。旧生产服务与博客未更新。

证据见同目录 technical-layers-checks-20261111.json 和 technical-layers-live-20261111.json。未完成整体质量、性能或成本评估；原有内容、认证、会话归属、限速与引用语义问题仍待后续处理。IDE 父项目的旧 SDK 关联已备份修正，重开后的 Agent 与 robot-rag 软件包列表均实际显示，当前启动日志未再出现远程凭据丢失异常。

运行命令及解释器见 ../backend.md，当前整体目录见 ../architecture.md。
