<script setup>
import { nextTick, ref } from 'vue'
import SourceList from './SourceList.vue'

defineProps({ messages: { type: Array, required: true }, loading: Boolean })
const container = ref(null)
async function scrollToBottom() {
  await nextTick()
  if (container.value) container.value.scrollTop = container.value.scrollHeight
}
defineExpose({ scrollToBottom })
</script>

<template>
  <div ref="container" class="messages">
    <div v-for="(message, index) in messages" :key="index" class="message-row" :class="message.role">
      <div class="avatar">{{ message.role === 'assistant' ? 'AI' : '我' }}</div>
      <div class="message-body">
        <div class="bubble">{{ message.content || (loading && index === messages.length - 1 ? '正在查找资料…' : '') }}</div>
        <SourceList :sources="message.sources" />
      </div>
    </div>
  </div>
</template>
