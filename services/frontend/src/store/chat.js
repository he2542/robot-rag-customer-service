import { ref } from 'vue'

const sessionKey = 'robot-internal-session-id'

export function createChatStore({ api, storage = globalThis.localStorage,
  createId = () => crypto.randomUUID() } = {}) {
  const modelReady = ref(false)
  const serviceStatus = ref('检查服务中…')
  const knowledge = ref({ files: [], ready: false, chunk_count: 0 })
  const messages = ref([
    { role: 'assistant', content: '你好，我是扫地机器人知识助手。可以咨询选购、日常维护和常见故障，请尽量说明品牌、型号和具体情况。' },
  ])
  const input = ref('')
  const loading = ref(false)
  const sessionId = storage.getItem(sessionKey) || createId()
  storage.setItem(sessionKey, sessionId)
  let controller

  async function initialize() {
    try {
      const result = await api.status()
      knowledge.value = result.knowledge
      modelReady.value = result.available && result.health.model_configured === true && knowledge.value.ready
      serviceStatus.value = !result.available ? '服务暂不可用'
        : !knowledge.value.ready ? '知识库待导入'
          : !result.health.model_configured ? '模型待配置' : '在线'
    } catch {
      modelReady.value = false
      serviceStatus.value = '服务暂不可用'
    }
  }

  async function sendMessage(onUpdate = async () => {}) {
    const question = input.value.trim()
    if (!question || question.length > 4000 || loading.value || !modelReady.value) return
    messages.value.push({ role: 'user', content: question })
    messages.value.push({ role: 'assistant', content: '', sources: [] })
    const answerIndex = messages.value.length - 1
    input.value = ''
    loading.value = true
    controller = new AbortController()
    try {
      await onUpdate()
      await api.stream(question, sessionId, controller.signal, async (payload) => {
        const current = messages.value[answerIndex]
        if (Array.isArray(payload.sources)) current.sources = payload.sources
        if (typeof payload.content === 'string') current.content += payload.content
        await onUpdate()
      })
    } catch (error) {
      messages.value[answerIndex].content += `\n\n本次回答未完成：${error.message}`
    } finally {
      loading.value = false
      controller = undefined
    }
  }

  function dispose() {
    controller?.abort()
  }

  return { modelReady, serviceStatus, knowledge, messages, input, loading, initialize, sendMessage, dispose }
}
