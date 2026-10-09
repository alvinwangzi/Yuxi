import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

// 直接执行卡片实际处理函数，隔离网络，不改真实连接器的启用状态。
const source = readFileSync(new URL('../../src/components/extensions/ConnectorCardList.vue', import.meta.url), 'utf8')
const handler = source.slice(source.indexOf('async function toggleConnector('), source.indexOf('async function fetchConnectors('))

test('启停采用当前版本并等待后端确认，再更新卡片状态', async () => {
  let finish
  const pending = new Promise(resolve => { finish = resolve })
  const calls = []
  let refreshed = 0
  const context = vm.createContext({ actionLoadingSlug: { value: '' },
    updateConnector: (slug, payload) => { calls.push({ slug, ...payload }); return pending },
    fetchConnectors: async () => { refreshed++ }, message: { success() {}, error() {} } })
  vm.runInContext(handler, context)
  const conn = { slug: 'test', enabled: true, revision: 4 }
  const saving = context.toggleConnector(conn, false)
  assert.equal(conn.enabled, true)
  assert.equal(context.actionLoadingSlug.value, 'test')
  await context.toggleConnector(conn, false)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].expected_revision, 4)
  finish({ success: true, data: { enabled: false, revision: 5 } })
  await saving
  assert.equal(conn.enabled, false)
  assert.equal(conn.revision, 5)
  assert.equal(refreshed, 1)
  assert.equal(context.actionLoadingSlug.value, '')
})

test('保存失败不把卡片状态当作成功，回读并恢复操作入口', async () => {
  let refreshed = false
  let errorShown = false
  const context = vm.createContext({ actionLoadingSlug: { value: '' },
    updateConnector: async () => { throw new Error('conflict') },
    fetchConnectors: async () => { refreshed = true },
    message: { success() { assert.fail('不得提示成功') }, error() { errorShown = true } } })
  vm.runInContext(handler, context)
  const conn = { slug: 'test', enabled: true, revision: 4 }
  await context.toggleConnector(conn, false)
  assert.equal(conn.enabled, true)
  assert.equal(conn.revision, 4)
  assert.ok(refreshed && errorShown)
  assert.equal(context.actionLoadingSlug.value, '')
})
