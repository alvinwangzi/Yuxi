import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AGENT_FACE_SCENARIOS,
  generateAgentFaceAvatar,
  resolveAgentFaceConfig
} from '../../src/utils/agentFaceAvatar.js'

const DATA_URI_PREFIX = 'data:image/svg+xml;charset=utf-8,'

test('同名同描述恒定生成同一 data URI，不同输入不同结果', () => {
  const first = generateAgentFaceAvatar('写作助手', '撰写报告与总结')
  assert.equal(first, generateAgentFaceAvatar('写作助手', '撰写报告与总结'))
  assert.notEqual(first, generateAgentFaceAvatar('数据分析员', '统计经营指标'))
})

test('企业场景词典逐条命中对应配饰', () => {
  for (const scenario of AGENT_FACE_SCENARIOS) {
    for (const keyword of scenario.keywords) {
      const config = resolveAgentFaceConfig(keyword, '')
      assert.equal(config.accessory, scenario.accessory, `「${keyword}」应命中 ${scenario.label}`)
    }
  }
})

test('标题优先于描述，多词命中按词典固定顺序取首个', () => {
  assert.equal(resolveAgentFaceConfig('写作助手', '数据统计').accessory, 'pen')
  assert.equal(resolveAgentFaceConfig('', '数据统计').accessory, 'chart')
  // 「客服」（globe）与「财务」（chart）同时出现时，按词典固定顺序 globe 先命中。
  assert.equal(resolveAgentFaceConfig('客服财务助手', '').accessory, 'globe')
  assert.equal(resolveAgentFaceConfig('财务分析助手', '').accessory, 'chart')
  assert.equal(resolveAgentFaceConfig('法务合同审核助手', '').accessory, 'check')
  assert.equal(resolveAgentFaceConfig('客服问题解答机器人', '').accessory, 'globe')
})

test('无词典命中时配置纯哈希稳定且取值合法', () => {
  const first = resolveAgentFaceConfig('通用智能助手', '处理日常事务')
  const second = resolveAgentFaceConfig('通用智能助手', '处理日常事务')
  assert.deepEqual(second, first)
  assert.ok(['#f2c9a0', '#e8b98c', '#f7d3b0', '#d9a273'].includes(first.skin))
  assert.ok(['#2f2a26', '#3b2f2a', '#4a3728', '#1f1b18', '#5b4636'].includes(first.hair))
  assert.ok(['short', 'bob', 'long', 'bun', 'curly', 'side'].includes(first.style))
  assert.ok(['#fdfcf9', '#f8f6f2', '#f4f7f5', '#f7f4f8', '#f6f4ee'].includes(first.bg))
  const accessoryPool = [...AGENT_FACE_SCENARIOS.map((scenario) => scenario.accessory), null]
  assert.ok(accessoryPool.includes(first.accessory))
})

test('名称与描述均为空时返回空串，交由首字母兜底', () => {
  assert.equal(generateAgentFaceAvatar('', ''), '')
  assert.equal(generateAgentFaceAvatar('   ', undefined), '')
})

test('输出为可解码的 SVG data URI 且包含配饰特征', () => {
  const uri = generateAgentFaceAvatar('数据分析员', '输出经营报表')
  assert.ok(uri.startsWith(DATA_URI_PREFIX))
  const svg = decodeURIComponent(uri.slice(DATA_URI_PREFIX.length))
  assert.ok(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"'))
  assert.ok(svg.endsWith('</svg>'))
  // 图表配饰由三个 ink 色柱状矩形构成，第三个柱体位于 x=55。
  assert.ok(svg.includes('<rect x="55" y="43"'))
  assert.ok(!svg.toLowerCase().includes('dicebear'))
})
