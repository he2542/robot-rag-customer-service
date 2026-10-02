# PostgreSQL 部署与维护

生产入口为 `/robot/`。OpenResty 提供静态前端，`/robot/api/` 转发到 `127.0.0.1:8100/api/`。前端执行 `VITE_BASE_PATH=/robot/ npm run build`，发布 `frontend/dist`。后端通过 `robot-rag.service` 运行。

## 私有访问

生产 `/robot/` 已启用 HTTPS Basic 登录验证。页面、静态资源和所有 `/robot/api/` 接口均要求独立的网站账号密码，未登录或密码错误返回 401。博客首页继续公开。后端只监听 `127.0.0.1:8100`，不能开放该端口，否则可绕过代理层的认证。

登录用户名为 `robot-admin`。初始密码为随机生成的高强度密码，只存储在服务器 `/etc/robot-rag-access.json`（root 所有，权限 0600）。用户可在自己的私有终端读取该文件；不要截图、分享或上传文件内容。OpenResty 使用 `/opt/1panel/www/sites/www.mzrc.online/robot/private/htpasswd` 的 SHA-512 crypt 密码哈希，权限 0600，目录权限 0700；该目录独立于前端 public 目录，URL 访问显式返回 404。

用户自行修改网站登录密码：

```bash
sudo python3 /opt/robot-rag-customer-service/set-access-password.py
```

脚本会隐藏输入、确认两次并要求至少 16 个字符，不把密码传到命令行或日志。已安装脚本源码在本目录 `set-access-password.py`。网站登录密码与模型 API Key、数据库密码独立。

认证路由参考 `robot-locations.conf`，API 限流定义参考 `robot-api-limit.conf`。后者须加载在 OpenResty 的 http 上下文（本次为 `/opt/1panel/apps/openresty/openresty/conf/http.d/robot-rag-limit.conf`），前者由网站 server 块 include。创建密码文件后执行 `nginx -t` 并 reload；未经验证不得删掉认证配置或另建不受保护的 API 代理入口。

公网健康检查同样需要登录。维护时可从服务器运行 `curl http://127.0.0.1:8100/api/health`；或在自己的终端执行 `curl --user robot-admin https://www.mzrc.online/robot/api/health` 并在提示中输入登录密码，不将密码直接写进命令历史。

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

停止后端，将 `current` 切换到新发布目录，更新服务单元，执行 `systemctl daemon-reload` 与 `systemctl start robot-rag`。从本机或带登录验证访问健康接口，核验返回 200，且 `database_ready=true`、`storage_backend=postgresql+pgvector`，再检查页面、聊天模型状态和博客入口。公网未登录访问客服和 API 应返回 401。

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

API 与数据库集成测试共 12 项，覆盖检索结果、去重、并发上传、嵌入失败、事务失败及模型配置不匹配。数据库测试使用确定性的替代嵌入模型，不发起付费 API 请求。模型密钥配置后，已用一条简短消息验证真实 DashScope 问答成功。

私有访问另行验证：www 与裸域名下的页面、静态资源、健康接口、聊天 POST 和上传 POST 未登录均返回 401；错误密码返回 401；正确登录后页面与数据库健康检查返回 200；认证文件 URL 返回 404；博客首页返回 200。拒绝的模型请求不会到达后端或触发模型 API。
