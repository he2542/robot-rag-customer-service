# Security Policy

## Reporting a vulnerability

请不要在公开 Issue 中提交 API Key、访问令牌或其他敏感信息。如果发现安全问题，请通过仓库维护者的私下联系方式报告，并提供复现步骤、影响范围和建议修复方式。

## Local data

`.env`、`chroma_db/`、`chat_history/` 和 `md5.text` 默认被 Git 忽略。部署前请确认没有将模型密钥、用户会话记录或其他本地数据加入提交。
