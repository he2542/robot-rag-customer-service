# Security Policy

## Reporting a vulnerability

请不要在公开 Issue 中提交 API Key、访问令牌或其他敏感信息。如果发现安全问题，请通过仓库维护者的私下联系方式报告，并提供复现步骤、影响范围和建议修复方式。

## Local data

`.env`、聊天历史及旧版 Chroma 数据默认被 Git 忽略。不要提交模型密钥、真实 `DATABASE_URL`、数据库备份或用户会话记录。生产 PostgreSQL 使用 1Panel Docker 实例，仅将端口发布到 `127.0.0.1:5432`，客服后端使用独立非超级用户角色；密码保存在 root 所有、权限 0600 的环境文件中。集成测试只允许在独立 `robot_rag_test` 数据库上运行。
