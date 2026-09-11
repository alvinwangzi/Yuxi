import assert from 'node:assert/strict'
import test from 'node:test'
import {
  CATEGORIES,
  CATEGORY_LABELS,
  inferSkillCategory,
  inferToolCategory,
  inferAgentCategory,
  inferMcpCategory
} from '../../src/utils/itemCategory.js'

test('CATEGORIES 包含全部 9 个分类 key', () => {
  assert.deepEqual(CATEGORIES, [
    'all', 'office', 'dev', 'data', 'content',
    'info', 'business', 'productivity', 'other'
  ])
})

test('CATEGORY_LABELS 提供中文标签', () => {
  assert.equal(CATEGORY_LABELS.office, '办公协同')
  assert.equal(CATEGORY_LABELS.dev, '开发工具')
  assert.equal(CATEGORY_LABELS.data, '数据分析')
  assert.equal(CATEGORY_LABELS.content, '内容创作')
  assert.equal(CATEGORY_LABELS.info, '信息资讯')
  assert.equal(CATEGORY_LABELS.business, '商业运营')
  assert.equal(CATEGORY_LABELS.productivity, '效率工具')
  assert.equal(CATEGORY_LABELS.other, '其他')
  assert.equal(CATEGORY_LABELS.all, '全部')
})

test('inferSkillCategory 按 slug 匹配办公协同', () => {
  assert.equal(inferSkillCategory({ slug: 'excel-helper', name: '', tool_dependencies: [], mcp_dependencies: [] }), 'office')
  assert.equal(inferSkillCategory({ slug: 'pdf-processor', name: '', tool_dependencies: [], mcp_dependencies: [] }), 'office')
  assert.equal(inferSkillCategory({ slug: 'email-sender', name: '', tool_dependencies: [], mcp_dependencies: [] }), 'office')
})

test('inferSkillCategory 按 name 匹配开发工具', () => {
  assert.equal(inferSkillCategory({ slug: 'x', name: 'Code Reviewer', tool_dependencies: [], mcp_dependencies: [] }), 'dev')
  assert.equal(inferSkillCategory({ slug: 'x', name: 'Git Helper', tool_dependencies: [], mcp_dependencies: [] }), 'dev')
  assert.equal(inferSkillCategory({ slug: 'frontend-design', name: 'Frontend Design', tool_dependencies: [], mcp_dependencies: [] }), 'dev')
  assert.equal(inferSkillCategory({ slug: 'html-preview', name: 'Html Preview', tool_dependencies: [], mcp_dependencies: [] }), 'dev')
})

test('inferSkillCategory 按 tool_dependencies 匹配数据分析', () => {
  assert.equal(inferSkillCategory({ slug: 'x', name: 'y', tool_dependencies: ['analytics'], mcp_dependencies: [] }), 'data')
})

test('inferSkillCategory 按 mcp_dependencies 匹配信息资讯', () => {
  assert.equal(inferSkillCategory({ slug: 'x', name: 'y', tool_dependencies: [], mcp_dependencies: ['web-search'] }), 'info')
})

test('inferSkillCategory 匹配内容创作', () => {
  assert.equal(inferSkillCategory({ slug: 'podcast-generation', name: 'Podcast Generation', tool_dependencies: [], mcp_dependencies: [] }), 'content')
  assert.equal(inferSkillCategory({ slug: 'music-generation', name: 'Music Generation', tool_dependencies: [], mcp_dependencies: [] }), 'content')
})

test('inferSkillCategory 匹配商业运营', () => {
  assert.equal(inferSkillCategory({ slug: 'consulting-analysis', name: 'Consulting Analysis', tool_dependencies: [], mcp_dependencies: [] }), 'business')
})

test('inferSkillCategory 未匹配归入 other', () => {
  assert.equal(inferSkillCategory({ slug: 'random-thing', name: 'Random', tool_dependencies: [], mcp_dependencies: [] }), 'other')
})

test('inferSkillCategory 优先级：先命中先返回', () => {
  // slug 含 excel → office，即使 name 含 data
  assert.equal(inferSkillCategory({ slug: 'excel-data', name: 'Data Tool', tool_dependencies: [], mcp_dependencies: [] }), 'office')
})

test('inferToolCategory 映射已有 category 字段', () => {
  assert.equal(inferToolCategory({ category: 'buildin' }), 'productivity')
  assert.equal(inferToolCategory({ category: 'knowledge' }), 'productivity')
  assert.equal(inferToolCategory({ category: 'mysql' }), 'data')
  assert.equal(inferToolCategory({ category: 'debug' }), 'dev')
  assert.equal(inferToolCategory({ category: 'unknown' }), 'other')
  assert.equal(inferToolCategory({}), 'other')
})

test('inferAgentCategory 按 name + description 匹配', () => {
  assert.equal(inferAgentCategory({ name: '营销助手', description: '负责电商营销和客户管理' }), 'business')
  assert.equal(inferAgentCategory({ name: '数据分析师', description: '' }), 'data')
  assert.equal(inferAgentCategory({ name: '前端开发助手', description: '辅助前端界面开发' }), 'dev')
  assert.equal(inferAgentCategory({ name: 'Random Agent', description: 'Does random things' }), 'other')
})

test('inferMcpCategory 按 name + description + tags 匹配', () => {
  assert.equal(inferMcpCategory({ name: 'Web Search', description: '', tags: [] }), 'info')
  assert.equal(inferMcpCategory({ name: 'DB Connector', description: '', tags: ['analytics'] }), 'data')
  assert.equal(inferMcpCategory({ name: 'Random MCP', description: '', tags: [] }), 'other')
})
