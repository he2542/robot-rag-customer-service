import test from 'node:test'
import assert from 'node:assert/strict'
import { createChatStore } from '../src/store/chat.js'

function createStore(api, existingId) {
  const data = new Map(existingId ? [['robot-internal-session-id', existingId]] : [])
  return createChatStore({ api, storage: {
    getItem: (key) => data.get(key), setItem: (key, value) => data.set(key, value),
  }, createId: () => 'test-session' })
}
const ready = async () => ({ available: true, health: { model_configured: true },
  knowledge: { ready: true, files: [], chunk_count: 0 } })

test('streamed answer and sources update state with the existing session', async () => {
  const calls = []
  const store = createStore({ status: ready, async stream(question, session, signal, update) {
    calls.push({ question, session, aborted: signal.aborted })
    await update({ sources: [{ id: 'S1', filename: '资料.txt' }] })
    await update({ content: '清理' })
    await update({ content: '主刷。' })
  } }, 'existing-session')
  await store.initialize()
  store.input.value = '  如何维护？  '
  await store.sendMessage()
  assert.deepEqual(calls, [{ question: '如何维护？', session: 'existing-session', aborted: false }])
  assert.equal(store.messages.value.at(-1).content, '清理主刷。')
  assert.equal(store.messages.value.at(-1).sources[0].id, 'S1')
  assert.equal(store.input.value, '')
  assert.equal(store.loading.value, false)
})

test('unready knowledge prevents sending', async () => {
  const store = createStore({ status: async () => ({ ...(await ready()), knowledge: { ready: false, files: [] } }),
    stream() { assert.fail('must not send') } })
  await store.initialize()
  store.input.value = '问题'
  await store.sendMessage()
  assert.equal(store.serviceStatus.value, '知识库待导入')
  assert.equal(store.messages.value.length, 1)
})

test('health check failure disables sending', async () => {
  const store = createStore({ status: async () => { throw new Error('offline') } })
  await store.initialize()
  assert.equal(store.modelReady.value, false)
  assert.equal(store.serviceStatus.value, '服务暂不可用')
})

test('partial failures preserve the answer and show incomplete status', async () => {
  const store = createStore({ status: ready, async stream(q, s, signal, update) {
    await update({ content: '已收到部分回答' })
    throw new Error('连接中断')
  } })
  await store.initialize()
  store.input.value = '问题'
  await store.sendMessage()
  assert.match(store.messages.value.at(-1).content, /已收到部分回答[\s\S]*本次回答未完成：连接中断/)
  assert.equal(store.loading.value, false)
})

test('dispose aborts an in-flight request and repeated sends are ignored', async () => {
  let started
  const start = new Promise((resolve) => { started = resolve })
  let calls = 0
  const store = createStore({ status: ready, stream(q, s, signal) {
    calls++
    started()
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted'))))
  } })
  await store.initialize()
  store.input.value = '问题'
  const pending = store.sendMessage()
  await start
  store.input.value = '重复问题'
  await store.sendMessage()
  assert.equal(calls, 1)
  store.dispose()
  await pending
  assert.equal(store.loading.value, false)
})

test('blank and oversized questions are rejected before requests', async () => {
  const store = createStore({ status: ready, stream() { assert.fail('must not send') } })
  await store.initialize()
  for (const input of ['  ', '长'.repeat(4001)]) {
    store.input.value = input
    await store.sendMessage()
  }
  assert.equal(store.messages.value.length, 1)
})
