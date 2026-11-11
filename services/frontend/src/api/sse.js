// Read complete SSE frames even when UTF-8 characters or frames span network chunks.
export async function readChatStream(body, onPayload) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false
  try {
    while (!completed) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let boundary
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index)
        buffer = buffer.slice(boundary.index + boundary[0].length)
        const data = frame.split(/\r?\n/)
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).replace(/^ /, '')).join('\n')
        if (!data) continue
        if (data === '[DONE]') {
          completed = true
          break
        }
        const payload = JSON.parse(data)
        if (payload.error) throw new Error(payload.error)
        await onPayload(payload)
      }
      if (done) break
    }
    if (!completed) throw new Error('回答连接中断，请稍后重试')
  } finally {
    try { await reader.cancel() } finally { reader.releaseLock() }
  }
}
