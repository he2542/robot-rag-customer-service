# PostgreSQL 部署与维护

生产入口为 `/robot/`。OpenResty 提供静态前端，`/robot/api/` 转发到 `127.0.0.1:8100/api/`。前端执行 `VITE_BASE_PATH=/robot/ npm run build`，发布 `frontend/dist`。后端通过 `robot-rag.service` 运行。

部署目录为 `/opt/robot-rag-customer-service`，`current` 指向当前发布目录，`venv-pgvector` 为独立 Python 环境，数据目录为 `/var/lib/robot-rag`。实际部署使用 PostgreSQL 17.11 和 pgvector 0.8.6，数据库名为 `robot_rag`，专用操作系统用户与数据库角色均为 `robot-rag`。

PostgreSQL 使用用户在 1Panel 中安装的 `postgresql` 实例，容器为 `1Panel-postgresql-dUxs`，数据目录为 `/opt/1panel/apps/postgresql/postgresql/data`。端口只发布到 `127.0.0.1:5432`，不允许公网访问。配置 `shared_buffers=64MB`、`max_connections=30`。原 Ubuntu 系统安装的 PostgreSQL 已卸载，项目依赖 Docker 服务。

环境变量存放在 root 所有、权限 `0600` 的 `/etc/robot-rag.env`。后端使用独立 `robot-rag` 数据库角色与密码认证，该角色不是超级用户；连接地址模板为 `postgresql+psycopg://robot-rag:PASSWORD@127.0.0.1:5432/robot_rag`，真实密码只保存在服务器环境文件中。保留 `RAG_DATA_DIR=/var/lib/robot-rag`，模型参数参考 `.env.example`。用 `sudoedit /etc/robot-rag.env` 配置真实 `DASHSCOPE_API_KEY`，然后重启 `robot-rag`。未配置密钥时页面显示“模型待配置”，聊天和上传返回 503。

首次部署由管理员创建数据库角色、数据库，并在目标数据库执行 `CREATE EXTENSION vector`。将环境变量加载到专用用户进程后，在发布目录运行 `python database.py` 初始化表。业务代码不会自动创建扩展或覆盖已有嵌入模型配置。后端依赖用 `pip install -r requirements-deployed.txt` 安装，服务单元参考同目录的 `robot-rag.service`。

## 1Panel 实例的 pgvector 镜像

普通 `postgres:17.11-alpine` 镜像不包含 pgvector。本次在用户安装的镜像基础上编译 pgvector 0.8.6，构建为 `local/1panel-postgres:17.11-alpine-pgvector0.8.6`。原容器名、面板环境文件、端口与数据目录保持不变，面板的 `docker-compose.yml` 使用该扩展镜像。

构建资料保存在 `/opt/1panel/apps/postgresql/postgresql/pgvector-build`，Dockerfile 对基础镜像 digest 和源码 SHA-256 均进行了固定。复现构建：

```bash
curl -fL -o pgvector-v0.8.6.tar.gz https://codeload.github.com/pgvector/pgvector/tar.gz/refs/tags/v0.8.6
docker build -f Dockerfile.pgvector -t local/1panel-postgres:17.11-alpine-pgvector0.8.6 .
```

服务器构建可指定 `--build-arg ALPINE_MIRROR=https://mirrors.aliyun.com/alpine` 加速下载，apk 仍执行包签名验证。编译完成后构建依赖与包缓存均已移除。

在 1Panel 中重启实例会继续使用扩展镜像。通过应用商店升级版本可能改写 Compose 的镜像配置；升级前应为新 PostgreSQL 版本重建包含 pgvector 的镜像，备份数据，并检查 Compose 是否继续使用扩展镜像。不要直接换回缺少 pgvector 的普通镜像。

## 升级与回退

先在新的发布目录和独立虚拟环境准备代码，在 `robot_rag_test` 测试库运行集成测试。生产库不能运行该测试套件。切换前备份服务单元、环境变量、原 `current` 指向和数据库；备份目录应为 root 所有、权限 `0700`。

停止后端，将 `current` 切换到新发布目录，更新服务单元，执行 `systemctl daemon-reload` 与 `systemctl start robot-rag`。核验 `/robot/api/health` 返回 200，且 `database_ready=true`、`storage_backend=postgresql+pgvector`，再检查页面、聊天模型状态和博客入口。

应用版本回退时停止后端，恢复与当前面板数据库兼容的服务单元、环境文件和 `current` 指向，再重新加载并启动服务。原系统 PostgreSQL 的服务配置仅作为历史恢复资料，卸载后不能直接用于回退。更换嵌入模型或维度应使用新数据库完成重建与验证，切勿直接覆盖生产配置记录。

## 备份与恢复

在 root shell 中，将下例路径替换为事先创建的受保护备份目录：

```bash
docker exec 1Panel-postgresql-dUxs sh -c 'exec pg_dump -U "$POSTGRES_USER" -Fc robot_rag' > /protected-backups/robot_rag.dump
chmod 600 /protected-backups/robot_rag.dump
cat /protected-backups/robot_rag.dump | docker exec -i 1Panel-postgresql-dUxs pg_restore --list
```

定期在新建的独立恢复测试库中验证备份。恢复命令如下，数据库名应为本次新建的目标库；不要对运行中的生产库覆盖恢复：

```bash
docker exec 1Panel-postgresql-dUxs sh -c 'createdb -U "$POSTGRES_USER" robot_rag_restore_check'
cat /protected-backups/robot_rag.dump | docker exec -i 1Panel-postgresql-dUxs sh -c 'exec pg_restore -U "$POSTGRES_USER" --exit-on-error -d robot_rag_restore_check'
docker exec 1Panel-postgresql-dUxs sh -c 'psql -U "$POSTGRES_USER" -d robot_rag_restore_check -c "SELECT count(*) FROM rag_documents;"'
```

数据库备份包含知识内容；环境文件可能包含密钥，两者都不应上传 GitHub。聊天历史另行备份 `/var/lib/robot-rag/chat_history`。

## 本次验证范围

API 与数据库集成测试共 12 项，覆盖检索结果、去重、并发上传、嵌入失败、事务失败及模型配置不匹配。数据库测试使用确定性的替代嵌入模型，不发起付费 API 请求。真实 DashScope 问答与知识上传需在配置密钥后验证。
