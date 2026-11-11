# 内置知识库改版工作记录

## 当前阶段：2026-11-11 技术分层迁移验收

- RAG-001｜已解决：用户上传入口关闭，旧上传 POST 返回 404；增加内置导入、限定检索和可展开来源。Ubuntu / Python 3.10 的 24 项后端测试通过，前端 3 项 SSE 测试通过，Vite 构建通过；隔离数据库验证旧版本、旧上传不会混入回答。
- RAG-002｜已解决：独立开发环境 backend/.venv 与独立数据库/角色 robot_rag_internal_dev 已建立，导入 5 份 TXT、63 个片段；使用已有凭据进行实际嵌入和少量问答，没有复制凭据文件。真实验证见 validation-live-20261107.json，问答、订单能力边界及风险提示三例完成。旧配置 qwen3-max 返回 404 Model not exist，查询账号模型列表后，开发版显式改为可用的 qwen-plus，旧线上配置未改。
- RAG-003｜待核验：教程 TXT 含泛化产品规格、维修建议和可能重复的条目。保留原件，第一版显示资料范围，加入安全提示；上线前需品牌型号和专业内容审校。
- RAG-004｜待后续处理：公开服务的身份认证、会话归属及限速。本版开发服务仅 localhost，不恢复旧网站入口。
- RAG-005｜待后续处理：现有 langchain-community 和 RunnableWithMessageHistory 在当前版本发出弃用警告；本版保留可运行依赖并冻结 requirements-internal-20261107.txt，未来迁移到独立集成/持久化方案时单独回归。
- RAG-006｜待优化：参考资料列表已经可核对，但模型会把原文条目号混入引用。已增加 S 前缀及流式编号过滤，移除不属于本次召回的编号（含 S3-7 等组合形式），并用跨分包测试覆盖。编号过滤不等于语义证据校验，有些回答过滤后没有行内编号；不宣称逐句引用已验真。下一阶段建立固定问答集，评估召回、拒答和引用支持度，再决定混合检索/精排。

## 阶段复查结论

- RAG-008｜已解决（2026-11-11）：按用户选定的技术分层迁入 services/backend、services/frontend，统一 src.cli 与 pyproject 入口，清理转发和旧检索适配器，归档旧部署/依赖/文档。后端隔离数据库 31 项测试通过，前端 9 项测试和构建通过，editable 包及 CLI 验证通过。真实问答、订单边界、风险提示和浏览器发送均正常，旧生产服务仍停用。原始 TXT、提示词、CSS、私有环境及已有 9 个历史文件未改变。代码未提交、未推送。

- RAG-007｜已解决（2026-11-07）：平铺后端已迁入 src/robot_rag，按 Router / Schemas / Service / Repository 分层；RAG 流程和提示词集中于 modules/rag，管理员命令进入 scripts 与 cli，原 api/database/import_knowledge 三入口仅做兼容转发。Ubuntu 隔离测试库 28 项后端测试、Windows 20 项无数据库测试、3 项前端 SSE 测试通过。实际开发预览健康正常，5 份/63 片段保留，重复导入五份均跳过；普通问题、订单边界、风险提示三例 SSE 完成。导航见 backend/架构导航.md，实测见 outputs/validation-framework-20261107.json。本阶段未实施新检索策略。

2026-11-07 分层整理复查：达到本次框架整理目标；前端协议、资料身份、切块/检索参数和历史目录保持基线。RAG-003—006 仍未关闭；结构调整不代表完成资料审校、公开上线安全、弃用依赖迁移或检索质量优化。下一阶段由用户修改策略，建议用固定问答集对比基线，不自动启动策略优化。单次实际普通问答约 1.78 秒，订单边界约 2.87 秒，仅为连通性样例，不据此判断总体性能或成本。临时测试容器已停止并自动删除；博客 200，旧 /robot/ 404，旧生产服务仍停用。

分层前可回退备份：D:/host/outputs/robot-rag-framework-20261107/backup-before；服务器 /home/ubuntu/robot-rag-framework-before-20261107.tar.gz（gzip 完整性已核验，包含私有环境配置，按私密备份保管）。部署前测试在独立 stage 目录和一次性 robot_rag_test 数据库执行，未清空业务库。首次测试容器启动碰到初始化期间 socket 短暂不可用，待实际 TCP SQL 可用后全套通过；与应用故障无关。

2026-11-07：第一版“无需上传，直接使用内部资料回答”达到目标；开发服务已真实调用模型，界面已检查桌面与窄窗口。速度仅测少量问题约 1.7—3 秒，不能代表整体性能；真实模型调用量未取得账单，不填报估算费用为实测。内容专业审校、公开上线条件和系统性质量评估仍未完成。

开发预览：robot-rag-internal-dev.service（临时 systemd 单元，重启电脑/服务器后需重新建立连接或启动服务），服务器仅监听 127.0.0.1:8120；Windows 经 SSH 转发至 http://127.0.0.1:18080。旧 robot-rag.service 仍停用。实际截图和验证材料：D:/host/outputs/robot-rag-internal-20261107/。UI fixture 截图仅用于界面验收，不当作真实模型测试证据；真实测试另存 JSON。

环境问题记录：直连 PyPI 下载超时；Windows 使用已核验的本机代理 7897、Ubuntu 使用阿里云镜像完成独立环境安装。早期本地 SSH 测试隧道断开导致数据库测试不可用，随后在 Ubuntu 直接连接临时测试容器，24 项完整通过。桌面工具默认会话权限文件报错，改用独立 agent-desktop 会话可正常检查，未切换内置工具。

备份：D:/host/outputs/robot-rag-internal-20261107/backup-before。未启动线上部署。
服务器开发副本备份：/home/ubuntu/robot-rag-dev-before-internal-20261107-143007.tar.gz。原始 TXT 的一致性见 source-integrity.json；旧模型失败和引用修正前结果另保留，不覆盖为成功。


## 2026-11-11 迁移阶段复查

本次目录和代码职责整理达到预期，RAG 策略优化未启动。RAG-003—006 保持未关闭，不将连通性、目录整理或来源编号过滤当成语义质量提升。少量真实问题约 1.65—2.55 秒，仅作烟测，不是性能基准；未核算账单，不填报实测成本。

当前后端服务仍是私有 robot-rag-internal-dev.service，工作目录 services/backend，解释器 services/backend/.venv/bin/python，入口 src.main:app，监听 127.0.0.1:8120；Windows 转发 18080。旧 robot-rag.service inactive，博客 200、旧 /robot/ 404。一次性测试容器已停止并自动删除。

源码和配置备份：D:/host/outputs/robot-rag-tech-layers-20261111/before-local.tar.gz；IDE 设置备份在同目录 ide-before。服务器 /home/ubuntu/robot-rag-before-tech-layers-20261111.tar.gz，原代码保留在 /home/ubuntu/robot-rag-tech-layers-retired-20261111；服务器备份包含私有配置，按私密资料保管。虚拟环境迁移后修正 29 个文本入口绝对路径，python、pip、依赖一致性与实际服务均通过。

IDE 解释器路径、模块根和源根已在用户退出 PyCharm 后备份修正，SFTP 仓库根映射不变，全局和项目模型缓存改名保留。尚未在重开的 PyCharm UI 中核验软件包列表；需要下次打开确认新解释器可用。实际浏览器问答和来源数量已验证，来源折叠控件的自动化展开未独立验证；CSS 与来源 HTML 语义保留，不扩大成手机或全部交互已验收。

原 Git 提交 f0853d3（用户删除 README 的服务器专属段落）保留，本次没有把该段加回根 README。服务器原有额外 validation-live-20261107.json 从旧 outputs 保留到 docs/validation。本台账是唯一活动入口，历史原件保留在备份中。

验证文件：validation/technical-layers-live-20261111.json、validation/technical-layers-checks-20261111.json。截图在 D:/host/outputs/robot-rag-tech-layers-20261111/ui-live-desktop.png，构建与测试输出见本次聊天工具记录。迁移脚本第一次在目标目录创建前指定工作目录导致命令未启动，后在已有根目录执行成功；前端迁移中一次默认 GBK 读取失败，改为显式 UTF-8 后完成，最终源码与构建均正常。


- RAG-009｜已解决（2026-11-11）：父项目 Agent 的 misc.xml 与 Agent.iml 原先仍指向旧 RAG SDK，该 SDK 关联已不存在的部署编号。用户手动退出后，日志已完成 IDE SHUTDOWN，但无窗口残留进程未释放；核验后结束该残留进程，再备份并修正父级 SDK，保留其他项目与全局旧 SDK。重建模型缓存、重开后，Agent 与 robot-rag 两个条目的远程软件包列表均实际显示，当前启动日志中 Cannot find remote credentials 为零。正确解释器为 /home/ubuntu/robot-rag-dev/services/backend/.venv/bin/python。PyCharm 根据 pyproject.toml 自动重新生成模块文件，未依赖手工模块文件名稳定。备份在 D:/host/outputs/robot-rag-tech-layers-20261111/ide-parent-before-20261111-111728，截图 ide-settings-final.png 与 ide-backend-packages-verified.png 同目录。此前“软件包 UI 未验证”的阶段记录已由本次核验更新；未切换内置 Computer Use。

2026-11-11 IDE 收尾复查：达到父级解释器关联修复与软件包 UI 核验目标。代码、数据及服务未因本次 IDE 修复改动，未提交或推送 Git。RAG-003—006 仍保持原状态；本次不扩大为检索效果、公开上线或手机交互验收。
