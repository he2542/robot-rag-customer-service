<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { chatApi } from '../api/client.js'
import { createChatStore } from '../store/chat.js'
import ChatInput from '../components/ChatInput.vue'
import MessageList from '../components/MessageList.vue'
import KnowledgePanel from '../components/KnowledgePanel.vue'

const chat = createChatStore({ api: chatApi })
const { modelReady, serviceStatus, knowledge, messages, input, loading } = chat
const chatEl = ref(null)
const messageList = ref(null)
onMounted(chat.initialize)
onBeforeUnmount(chat.dispose)
function send() {
  return chat.sendMessage(() => messageList.value?.scrollToBottom())
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
      <MessageList ref="messageList" :messages="messages" :loading="loading" />
      <ChatInput v-model="input" :loading="loading" :ready="modelReady" :status="serviceStatus" @send="send" />
    </section>
    <KnowledgePanel :knowledge="knowledge" :disabled="loading || !modelReady" @ask="ask" />
  </main>
</template>
