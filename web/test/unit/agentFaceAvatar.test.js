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
  // 「客服」（globe）与「财务」（coins）同时出现时，按词典固定顺序 globe 先命中；
  // 「财务分析助手」命中 chart，因为「分析」在 chart 且 chart 置于 coins 前。
  assert.equal(resolveAgentFaceConfig('客服财务助手', '').accessory, 'globe')
  assert.equal(resolveAgentFaceConfig('财务分析助手', '').accessory, 'chart')
  assert.equal(resolveAgentFaceConfig('法务合同审核助手', '').accessory, 'check')
  assert.equal(resolveAgentFaceConfig('客服问题解答机器人', '').accessory, 'globe')
})

test('工程、设计、营销类角色命中新增配饰，质检词优先于工程师', () => {
  assert.equal(resolveAgentFaceConfig('前端开发工程师', '负责 React 界面开发').accessory, 'terminal')
  assert.equal(resolveAgentFaceConfig('算法工程师', '').accessory, 'terminal')
  // check 置于 terminal 前：含质检词的「工程师」仍归审核合规。
  assert.equal(resolveAgentFaceConfig('测试工程师', '').accessory, 'check')
  assert.equal(resolveAgentFaceConfig('UI 设计师', '').accessory, 'palette')
  assert.equal(resolveAgentFaceConfig('产品经理', '').accessory, 'glasses')
  assert.equal(resolveAgentFaceConfig('新媒体营销助手', '').accessory, 'megaphone')
})

test('管理身份命中公文包，业务词优先于管理词', () => {
  assert.equal(resolveAgentFaceConfig('CEO 战略助手', '').accessory, 'briefcase')
  assert.equal(resolveAgentFaceConfig('技术总监', '').accessory, 'briefcase')
  assert.equal(resolveAgentFaceConfig('部门主管', '负责日常管理').accessory, 'briefcase')
  // briefcase 置于最后：含业务词的管理者先归业务域。
  assert.equal(resolveAgentFaceConfig('销售总监', '').accessory, 'target')
  assert.equal(resolveAgentFaceConfig('首席财务官', '').accessory, 'coins')
  // glasses 的「项目管理」在 briefcase 前命中。
  assert.equal(resolveAgentFaceConfig('项目管理办公室', '').accessory, 'glasses')
})

test('销售、财务、人事岗位命中独立配饰，与数据量化区分', () => {
  assert.equal(resolveAgentFaceConfig('销售总监', '').accessory, 'target')
  assert.equal(resolveAgentFaceConfig('电商运营助手', '').accessory, 'target')
  assert.equal(resolveAgentFaceConfig('财务总监', '').accessory, 'coins')
  assert.equal(resolveAgentFaceConfig('会计助手', '').accessory, 'coins')
  assert.equal(resolveAgentFaceConfig('税务助手', '').accessory, 'coins')
  assert.equal(resolveAgentFaceConfig('人事专员', '').accessory, 'users')
  assert.equal(resolveAgentFaceConfig('招聘助手', '').accessory, 'users')
  // 数据分析仍归柱状图，与财务、销售岗位区分。
  assert.equal(resolveAgentFaceConfig('数据分析', '').accessory, 'chart')
  // 交叉词裁决：财务报表归量化（chart 在 coins 前）；薪酬核算归财务（coins 在 users 前）；电商客服归销售（target 在 globe 前）。
  assert.equal(resolveAgentFaceConfig('财务报表', '').accessory, 'chart')
  assert.equal(resolveAgentFaceConfig('薪酬核算', '').accessory, 'coins')
  assert.equal(resolveAgentFaceConfig('电商客服', '').accessory, 'target')
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

test('新增配饰渲染对应 SVG 特征', () => {
  const svgOf = (name) => decodeURIComponent(
    generateAgentFaceAvatar(name, '').slice(DATA_URI_PREFIX.length)
  )
  // 终端窗口：提示符括号与光标线。
  assert.ok(svgOf('前端开发工程师').includes('<path d="M 47.5 44.5 L 50 47 L 47.5 49.5"'))
  assert.ok(svgOf('前端开发工程师').includes('<line x1="51.5" y1="49.5"'))
  // 调色盘：圆盘与拇指洞圈。
  assert.ok(svgOf('UI 设计师').includes('<circle cx="52" cy="47.5" r="8"'))
  assert.ok(svgOf('UI 设计师').includes('<circle cx="55.5" cy="50.5" r="2.4"'))
  // 扩音喇叭：锥体与声波弧。
  assert.ok(svgOf('新媒体营销助手').includes('<path d="M 47.5 45 L 58 40.5 L 58 51.5 L 45.5 52 Z"'))
  assert.ok(svgOf('新媒体营销助手').includes('M 60.5 43.5 Q 61 46 60.5 48.5'))
  // 公文包：包体、提手与扣带线。
  assert.ok(svgOf('CEO 战略助手').includes('<rect x="45" y="45" width="14" height="10" rx="2"'))
  assert.ok(svgOf('CEO 战略助手').includes('M 49.5 45 L 49.5 42.5 Q 49.5 41.5 50.5 41.5 L 53.5 41.5 Q 54.5 41.5 54.5 42.5 L 54.5 45'))
  assert.ok(svgOf('CEO 战略助手').includes('<line x1="45" y1="49.5" x2="59" y2="49.5"'))
  // 靶心：外环与内环同心。
  assert.ok(svgOf('销售总监').includes('<circle cx="52" cy="48" r="4.5"'))
  // 硬币叠：三枚扁椭圆。
  assert.ok(svgOf('财务总监').includes('<ellipse cx="52" cy="46" rx="7" ry="2.6"'))
  // 双人形：前后两个头。
  assert.ok(svgOf('人事专员').includes('<circle cx="48.5" cy="45.5" r="3"'))
  assert.ok(svgOf('人事专员').includes('<circle cx="56.5" cy="44.5" r="2.6"'))
})
