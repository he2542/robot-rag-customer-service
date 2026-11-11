import { readChatStream } from './sse.js'

const apiBase = `${import.meta.env.BASE_URL}api`

export const chatApi = {
  async status() {
    const [response, knowledgeResponse] = await Promise.all([
      fetch(`${apiBase}/health`), fetch(`${apiBase}/knowledge`),
    ])
    const health = await response.json()
    if (!knowledgeResponse.ok) throw new Error('knowledge check failed')
    return { available: response.ok, health, knowledge: await knowledgeResponse.json() }
  },

  async stream(question, sessionId, signal, onPayload) {
    const response = await fetch(`${apiBase}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: question, session_id: sessionId }),
      signal,
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(typeof payload.detail === 'string' ? payload.detail : `请求失败（${response.status}）`)
    }
    if (!response.body) throw new Error('回答流不可用')
    await readChatStream(response.body, onPayload)
  },
}
