# Security Policy

## Reporting a vulnerability

请不要在公开 Issue 中提交 API Key、访问令牌或其他敏感信息。如果发现安全问题，请通过仓库维护者的私下联系方式报告，并提供复现步骤、影响范围和建议修复方式。

## Local data

`.env`、聊天历史及旧版 Chroma 数据默认被 Git 忽略。不要提交模型密钥、真实 `DATABASE_URL`、数据库备份或用户会话记录。生产 PostgreSQL 使用 1Panel Docker 实例，仅将端口发布到 `127.0.0.1:5432`，客服后端使用独立非超级用户角色；密码保存在 root 所有、权限 0600 的环境文件中。集成测试只允许在独立 `robot_rag_test` 数据库上运行。

## Private deployment

生产客服入口和模型调用接口通过 OpenResty HTTPS Basic Authentication 限制访问。页面、静态资源与 API 的认证范围必须一致。模型密钥仅保存在后端环境文件，不出现在浏览器或网站登录密码中。

禁止将后端 8100 端口开放到公网或配置不受认证保护的备用代理入口。网站密码文件和哈希文件不应提交到仓库。网站账号泄露时，用 `deploy/set-access-password.py` 的已安装脚本更改密码；模型密钥泄露时，应另在模型平台撤销并替换密钥。
