# 前端开发

在 services/frontend 执行 npm ci、npm run dev。Vite 默认端口 5173，将 /api 代理到 localhost:8000；SSH 开发时要确保代理能连接实际后端。

- App.vue：根组件。
- views/ChatView.vue：页面组装和滚动。
- components：ChatInput、MessageList、SourceList、KnowledgePanel。
- store/chat.js：会话 ID、消息、输入、加载状态、错误及中止；使用 Vue 自带响应式。
- api/client.js：健康/知识库状态和聊天请求；api/sse.js：SSE 帧解析。
- assets/styles.css：样式。

npm test 验证 SSE 和聊天状态流，npm run build 生成 dist。BASE_URL 继续由 Vite 设置，支持原有部署前缀。文本通过 Vue 插值显示，不使用 v-html 渲染来源内容。

页面显示的是候选检索资料；保留课程资料范围提示和回答未完成状态，不把模型输出标为官方承诺或逐句已核验。
