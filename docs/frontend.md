# 前端开发

前端使用 Vue 3 和 Vite，命令在 `services/frontend` 执行。

```bash
npm ci
npm run dev
```

默认访问 [localhost:5173](http://localhost:5173)，`/api` 代理到 `http://127.0.0.1:8000`。后端地址变化时，在 `vite.config.js` 中调整开发代理。

## 代码入口

| 路径 | 职责 |
|---|---|
| `src/App.vue` | 根组件 |
| `src/views/ChatView.vue` | 页面组合与滚动 |
| `src/components/ChatInput.vue` | 输入、发送与停止 |
| `src/components/MessageList.vue` | 消息及回答状态 |
| `src/components/SourceList.vue` | 展开查看检索参考片段 |
| `src/components/KnowledgePanel.vue` | 资料列表与就绪状态 |
| `src/store/chat.js` | 会话 ID、消息、请求状态及中止逻辑 |
| `src/api/client.js` | 健康检查、知识库状态和问答请求 |
| `src/api/sse.js` | UTF-8 和 SSE 跨分包解析 |
| `src/assets/styles.css` | 页面样式 |

## 流式回答

前端先接收来源列表，再追加回答内容。成功结束、请求中止、网络异常和截断流分别处理；未收到正常结束标记时，回答显示为未完成。状态未就绪或已有请求进行中时，不重复发送。

模型回答和资料正文通过 Vue 文本插值显示，不作为 HTML 执行。来源列表展示候选证据，不能显示为已获得官方授权或逐句完成事实核验。

## 测试与构建

```bash
npm test
npm run build
```

构建产物位于 `dist/`。默认部署根路径为 `/`，可通过 `VITE_BASE_PATH` 指定资源和请求前缀；子路径部署时，反向代理也需要匹配该前缀。详见 [部署说明](../deploy/README.md)。
