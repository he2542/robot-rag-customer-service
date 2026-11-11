import test from 'node:test'
import assert from 'node:assert/strict'
import { readChatStream } from '../src/api/sse.js'

function stream(text, byteSize = 1) {
  const bytes = new TextEncoder().encode(text)
  return new ReadableStream({ start(controller) {
    for (let start = 0; start < bytes.length; start += byteSize) {
      controller.enqueue(bytes.slice(start, start + byteSize))
    }
    controller.close()
  } })
}

test('Chinese bytes, sources and CRLF frames can span network packets', async () => {
  const received = []
  await readChatStream(stream('data: {"sources":[{"filename":"维护.txt"}]}\r\n\r\ndata: {"content":"中文回答"}\n\ndata: [DONE]\n\n'), (payload) => received.push(payload))
  assert.equal(received[0].sources[0].filename, '维护.txt')
  assert.equal(received[1].content, '中文回答')
})

test('truncated stream is not treated as a successful answer', async () => {
  await assert.rejects(readChatStream(stream('data: {"content":"部分回答"}\n\n'), () => {}), /中断/)
})

test('backend error events surface instead of looking complete', async () => {
  await assert.rejects(readChatStream(stream('data: {"error":"服务暂不可用"}\n\n'), () => {}), /服务暂不可用/)
})
