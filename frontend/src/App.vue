<script setup>
import { nextTick, ref } from 'vue'

const messages = ref([
  { role: 'assistant', content: '你好，我是智能客服，有什么问题可以咨询我吗？' },
])
const input = ref('')
const loading = ref(false)
const uploadMessage = ref('')
const uploadError = ref('')
const messagesEl = ref(null)
const sessionId = localStorage.getItem('rag-session-id') || `user_${Date.now()}`
localStorage.setItem('rag-session-id', sessionId)

async function scrollToBottom() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

async function sendMessage() {
  const question = input.value.trim()
  if (!question || loading.value) return

  messages.value.push({ role: 'user', content: question })
  messages.value.push({ role: 'assistant', content: '' })
  input.value = ''
  loading.value = true
  await scrollToBottom()

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: question, session_id: sessionId }),
    })
    if (!response.ok || !response.body) throw new Error(`请求失败（${response.status}）`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const event of events) {
        const line = event.split('\n').find((item) => item.startsWith('data: '))
        if (!line) continue
        const data = line.slice(6)
        if (data === '[DONE]') continue
        const payload = JSON.parse(data)
        if (payload.error) throw new Error(payload.error)
        messages.value[messages.value.length - 1].content += payload.content || ''
        await scrollToBottom()
      }
    }
  } catch (error) {
    messages.value[messages.value.length - 1].content = `抱歉，服务暂时不可用：${error.message}`
  } finally {
    loading.value = false
  }
}

async function uploadFile(event) {
  const file = event.target.files[0]
  event.target.value = ''
  if (!file) return
  uploadMessage.value = ''
  uploadError.value = ''
  try {
    const response = await fetch('/api/knowledge/upload', {
      method: 'POST',
      headers: { 'X-Filename': encodeURIComponent(file.name) },
      body: file,
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.detail || '上传失败')
    uploadMessage.value = payload.message
  } catch (error) {
    uploadError.value = error.message
  }
}
</script>

<template>
  <main class="page-shell">
    <section class="chat-card">
      <header class="hero">
        <div>
          <p class="eyebrow">RAG CUSTOMER SERVICE</p>
          <h1>智能客服</h1>
          <p class="subtitle">基于知识库的专业问答助手</p>
        </div>
        <div class="status"><span></span> 在线</div>
      </header>

      <div ref="messagesEl" class="messages">
        <div v-for="(message, index) in messages" :key="index" class="message-row" :class="message.role">
          <div class="avatar">{{ message.role === 'assistant' ? 'AI' : '我' }}</div>
          <div class="bubble">{{ message.content || (loading && index === messages.length - 1 ? '正在思考…' : '') }}</div>
        </div>
      </div>

      <form class="composer" @submit.prevent="sendMessage">
        <input v-model="input" :disabled="loading" placeholder="请输入你的问题…" autocomplete="off" />
        <button type="submit" :disabled="loading || !input.trim()">发送</button>
      </form>
    </section>

    <aside class="knowledge-card">
      <div class="card-heading">
        <div class="upload-icon">↑</div>
        <div>
          <h2>更新知识库</h2>
          <p>上传 UTF-8 编码的 TXT 文件</p>
        </div>
      </div>
      <label class="upload-box">
        <input type="file" accept=".txt,text/plain" @change="uploadFile" />
        <span>点击选择文件</span>
        <small>文件内容会自动切分并写入向量库</small>
      </label>
      <p v-if="uploadMessage" class="feedback success">{{ uploadMessage }}</p>
      <p v-if="uploadError" class="feedback error">{{ uploadError }}</p>
    </aside>
  </main>
</template>
