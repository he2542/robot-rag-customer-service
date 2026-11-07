<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { readChatStream } from './sse.js'

const apiBase = `${import.meta.env.BASE_URL}api`
const modelReady = ref(false)
const serviceStatus = ref('检查服务中…')
const knowledge = ref({ files: [], ready: false, chunk_count: 0 })
const scopeNote = '资料来自课程示例，非品牌官方手册；具体型号参数及保修政策以官方说明为准。'
let controller
onBeforeUnmount(() => controller?.abort())
onMounted(async () => {
  try {
    const [response, knowledgeResponse] = await Promise.all([
      fetch(`${apiBase}/health`), fetch(`${apiBase}/knowledge`),
    ])
    const payload = await response.json()
    if (!knowledgeResponse.ok) throw new Error('knowledge check failed')
    knowledge.value = await knowledgeResponse.json()
    modelReady.value = response.ok && payload.model_configured === true && knowledge.value.ready
    serviceStatus.value = !response.ok ? '服务暂不可用'
      : !knowledge.value.ready ? '知识库待导入'
        : !payload.model_configured ? '模型待配置' : '在线'
  } catch {
    serviceStatus.value = '服务暂不可用'
  }
})

const messages = ref([
  { role: 'assistant', content: '你好，我是扫地机器人知识助手。可以咨询选购、日常维护和常见故障，请尽量说明品牌、型号和具体情况。' },
])
const input = ref('')
const loading = ref(false)
const messagesEl = ref(null)
const chatEl = ref(null)
const sessionId = localStorage.getItem('robot-internal-session-id') || crypto.randomUUID()
localStorage.setItem('robot-internal-session-id', sessionId)

async function scrollToBottom() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

async function sendMessage() {
  const question = input.value.trim()
  if (!question || loading.value || !modelReady.value) return

  messages.value.push({ role: 'user', content: question })
  const answer = { role: 'assistant', content: '', sources: [] }
  messages.value.push(answer)
  const answerIndex = messages.value.length - 1
  input.value = ''
  loading.value = true
  await scrollToBottom()

  try {
    controller = new AbortController()
    const response = await fetch(`${apiBase}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: question, session_id: sessionId }),
      signal: controller.signal,
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(typeof payload.detail === 'string' ? payload.detail : `请求失败（${response.status}）`)
    }
    if (!response.body) throw new Error('回答流不可用')
    await readChatStream(response.body, async (payload) => {
      const current = messages.value[answerIndex]
      if (Array.isArray(payload.sources)) current.sources = payload.sources
      if (typeof payload.content === 'string') current.content += payload.content
      await scrollToBottom()
    })
  } catch (error) {
    messages.value[answerIndex].content += `\n\n本次回答未完成：${error.message}`
  } finally {
    loading.value = false
  }
}

function ask(question) {
  input.value = question
  chatEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <main class="page-shell">
    <section ref="chatEl" class="chat-card">
      <header class="hero">
        <div>
          <p class="eyebrow">RAG CUSTOMER SERVICE</p>
          <h1>扫地机器人知识助手</h1>
          <p class="subtitle">选购 · 维护保养 · 常见故障</p>
        </div>
        <div class="status"><span v-if="modelReady"></span> {{ serviceStatus }}</div>
      </header>

      <div ref="messagesEl" class="messages">
        <div v-for="(message, index) in messages" :key="index" class="message-row" :class="message.role">
          <div class="avatar">{{ message.role === 'assistant' ? 'AI' : '我' }}</div>
          <div class="message-body">
            <div class="bubble">{{ message.content || (loading && index === messages.length - 1 ? '正在查找资料…' : '') }}</div>
            <details v-if="message.sources?.length" class="sources">
              <summary>检索参考资料 · {{ message.sources.length }} 个片段</summary>
              <p class="source-hint">以下为本次召回的候选资料，可展开核对；不代表回答中的每句话已获验证。</p>
              <div v-for="source in message.sources" :key="source.id" class="source-item">
                <strong>[{{ source.id }}] {{ source.filename }} · 片段 {{ source.chunk_index + 1 }}</strong>
                <p>{{ source.excerpt }}</p>
              </div>
            </details>
          </div>
        </div>
      </div>

      <form class="composer" @submit.prevent="sendMessage">
        <input v-model="input" aria-label="咨询问题" maxlength="4000" :disabled="loading || !modelReady" :placeholder="modelReady ? '描述型号和遇到的问题…' : serviceStatus" autocomplete="off" />
        <button type="submit" :disabled="loading || !modelReady || !input.trim()">发送</button>
      </form>
    </section>

    <aside class="knowledge-card">
      <div class="card-heading">
        <div><h2>内置知识库</h2><p>直接提问，无需上传文件</p></div>
      </div>
      <ul class="knowledge-files">
        <li v-for="file in knowledge.files" :key="file.filename">{{ file.filename.replace(/\.txt$/i, '') }}</li>
      </ul>
      <p v-if="knowledge.ready" class="feedback">已收录 {{ knowledge.files.length }} 份资料</p>
      <p v-else class="feedback">知识库暂未就绪，稍后刷新查看。</p>
      <h2 class="example-title">可以这样问</h2>
      <button class="example-question" :disabled="loading || !modelReady" @click="ask('扫地机器人吸力下降，应该先检查什么？')">吸力下降，先检查什么？</button>
      <button class="example-question" :disabled="loading || !modelReady" @click="ask('日常应该如何清理主刷和滤网？')">主刷和滤网怎么保养？</button>
      <p class="scope-note">{{ knowledge.scope_note || scopeNote }}</p>
    </aside>
  </main>
</template>
