import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRouter, createMemoryHistory } from 'vue-router'

const source = (path) => readFileSync(new URL('../../src/' + path, import.meta.url), 'utf8').replace(/\r\n/g, '\n')
const loadLegacy = async () => (await import('../../src/router/legacy_extensions.js')).redirectLegacyExtensions

test('旧扩展入口在 Vue Router 中收敛到唯一资源页面并保留非 tab 查询与 hash', async () => {
  const redirect = await loadLegacy()
  const router = createRouter({history:createMemoryHistory(), routes:[
    {path:'/extensions',redirect}, {path:'/knowledge',component:{}}, {path:'/skills',component:{}}
  ]})
  for (const [tab, path] of [['knowledge','/knowledge'], ['mcp','/skills?tab=mcp'], ['tools','/skills?tab=tools'], ['connectors','/skills?tab=connectors'], ['skills','/skills']]) {
    await router.push('/extensions?tab=' + tab + '&action=edit#resource')
    assert.equal(router.currentRoute.value.path, path.split('?')[0])
    assert.equal(router.currentRoute.value.query.action, 'edit')
    assert.equal(router.currentRoute.value.hash, '#resource')
    assert.equal(router.currentRoute.value.query.tab, path.includes('?') ? tab : undefined)
  }
})

test('知识菜单和 Agent 资源跳转不再生产旧聚合 URL', () => {
  assert.match(source('layouts/AppLayout.vue'), /path: '\/knowledge'/)
  assert.doesNotMatch(source('components/model-management/AgentEditModal.vue'), /path: '\/extensions'/)
  assert.match(source('components/model-management/AgentEditModal.vue'), /path: '\/skills', query: \{ tab: 'mcp' \}/)
})

test('连接器在技能连接器页直接挂载，旧聚合组件不再装配', () => {
  assert.match(source('views/SkillsConnectorsView.vue'), /<ConnectorCardList/)
  assert.doesNotMatch(source('router/index.js'), /import\([^)]*ExtensionsView/)
})

test('实际路由注册保留旧知识详情参数、编辑查询、评估深链接与管理员边界', async () => {
  const text = source('router/index.js')
  const start = text.indexOf('routes: [') + 'routes: '.length
  const end = text.indexOf('\n  ]\n})', start) + '\n  ]'.length
  const definitions = new Function('AppLayout', 'BlankLayout', 'redirectLegacyExtensions', 'return ' + text.slice(start, end))({}, {}, await loadLegacy())
  const stub = (record) => ({...record, ...(record.component ? {component:{}} : {}), ...(record.children ? {children:record.children.map(stub)} : {})})
  const router = createRouter({history:createMemoryHistory(),routes:definitions.map(stub)})
  const expression = source('views/KnowledgeView.vue').match(/const isDetailPage = computed\(([^\n]+)\)/)[1]
  const isDetail = () => new Function('route', 'return (' + expression + ')()')(router.currentRoute.value)
  await router.push('/knowledge/')
  assert.equal(isDetail(), false, '列表尾斜线不能被当成没有内容的详情页')
  await router.push('/extensions/knowledgebase/nav-kb?action=edit#section')
  assert.equal(isDetail(), true)
  assert.equal(router.currentRoute.value.path, '/knowledge/nav-kb')
  assert.equal(router.currentRoute.value.params.kbId, 'nav-kb')
  assert.equal(router.currentRoute.value.query.action, 'edit')
  assert.equal(router.currentRoute.value.hash, '#section')
  assert.ok(router.currentRoute.value.matched.some(record => record.meta.requiresAdmin))
  await router.push('/extensions/knowledgebase/nav-kb/evaluation/nav-dataset?section=evaluation')
  assert.equal(router.currentRoute.value.path, '/knowledge/nav-kb/evaluation/nav-dataset')
  assert.equal(router.currentRoute.value.params.datasetId, 'nav-dataset')
})
