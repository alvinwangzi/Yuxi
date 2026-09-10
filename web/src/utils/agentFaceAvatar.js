// 智能体默认头像：按名称与描述确定性生成 Notion 风格人像 SVG data URI。
// 词典按企业应用场景组织；词表、六类配饰对应关系与裁决顺序由本文件拥有。

const SVG_INK = '#1f1f1f'
const SVG_BORDER = '#e6e3dc'
const SVG_SHIRT = '#37352f'
const FACE_CX = 32
const FACE_CY = 33
const FACE_R = 15

const SKIN_TONES = ['#f2c9a0', '#e8b98c', '#f7d3b0', '#d9a273']
const HAIR_COLORS = ['#2f2a26', '#3b2f2a', '#4a3728', '#1f1b18', '#5b4636']
const HAIR_STYLES = ['short', 'bob', 'long', 'bun', 'curly', 'side']
const BACKGROUNDS = ['#fdfcf9', '#f8f6f2', '#f4f7f5', '#f7f4f8', '#f6f4ee']
// 含两个 null：无词典命中的智能体约 1/4 概率无配饰，对应「通用助手」型角色。
const ACCESSORY_FALLBACKS = ['glasses', 'clipboard', 'check', 'globe', 'pen', 'chart', null, null]

// 企业场景词典。数组顺序即多词命中时的裁决顺序；标题先于描述参与匹配。
// 维护约束：新增关键词不得是其他更靠前类别关键词的子串，否则逐条断言测试会失败。
export const AGENT_FACE_SCENARIOS = [
  {
    accessory: 'globe',
    label: '外部信息与检索',
    keywords: [
      '搜索', '检索', '网页', '联网', '爬虫', '舆情', '资讯', '竞品', '情报',
      '问答', '客服', '售后', '帮助', '支持', '外贸'
    ]
  },
  {
    accessory: 'pen',
    label: '写作与文档',
    keywords: [
      '写作', '文案', '撰写', '起草', '编辑', '润色', '报告', '公文', '纪要',
      '总结', '新闻', '内容', '邮件', '翻译', '培训', '课程', '文档', '通知',
      '周报', '讲稿'
    ]
  },
  {
    accessory: 'chart',
    label: '数据与量化',
    keywords: [
      '数据', '分析', '统计', '报表', '指标', '监控', '大盘', '预测', '财务',
      '成本', '预算', '营收', '销售', '绩效', '库存', '增长', '经营', '运营', '考核'
    ]
  },
  {
    accessory: 'check',
    label: '审核与合规',
    keywords: [
      '核查', '校验', '审核', '审校', '合规', '审计', '风控', '质检', '测试',
      '验收', '安全', '法务', '合同', '审批', '对账', '巡检', '复核', '运维'
    ]
  },
  {
    accessory: 'clipboard',
    label: '调研与归档',
    keywords: [
      '调研', '访谈', '收集', '采集', '整理', '归档', '盘点', '索引', '知识库',
      '资料', '录入', '清单', '档案', '记录', '登记', '招聘', '人事', '行政'
    ]
  },
  {
    accessory: 'glasses',
    label: '研究与咨询',
    keywords: [
      '研究', '深入', '学术', '论文', '专家', '顾问', '咨询', '评估', '评审',
      '洞察', '策略', '规划', '方案', '决策', '项目管理'
    ]
  }
]

const hashSeed = (value) => {
  let hash = 0
  for (const char of String(value)) {
    hash = (hash * 31 + char.codePointAt(0)) >>> 0
  }
  return hash >>> 0
}

const pick = (list, seed, salt) => list[hashSeed(`${salt}:${seed}`) % list.length]

const matchAccessory = (text) => {
  const normalized = String(text || '')
  if (!normalized) return null
  for (const scenario of AGENT_FACE_SCENARIOS) {
    if (scenario.keywords.some((keyword) => normalized.includes(keyword))) {
      return scenario.accessory
    }
  }
  return null
}

/** 解析智能体默认头像参数：配饰按「标题优先、描述其次」命中企业场景词典，其余特征纯哈希选取。 */
export const resolveAgentFaceConfig = (name, description = '') => {
  const seed = `${String(name || '').trim()}\n${String(description || '').trim()}`
  return {
    skin: pick(SKIN_TONES, seed, 'skin'),
    hair: pick(HAIR_COLORS, seed, 'hair'),
    style: pick(HAIR_STYLES, seed, 'style'),
    bg: pick(BACKGROUNDS, seed, 'bg'),
    accessory: matchAccessory(name) ?? matchAccessory(description) ?? pick(ACCESSORY_FALLBACKS, seed, 'acc')
  }
}

const buildHair = (style, hair) => {
  const cx = FACE_CX
  const cy = FACE_CY
  const r = FACE_R
  const pathAttrs = `fill="${hair}" stroke="${SVG_INK}" stroke-width="2.4" stroke-linejoin="round"`
  if (style === 'short') {
    return `<path d="M ${cx - r} ${cy - 2} Q ${cx - r - 1} ${cy - r - 6} ${cx} ${cy - r - 6} Q ${cx + r + 1} ${cy - r - 6} ${cx + r} ${cy - 2} Q ${cx + r - 4} ${cy - r + 2} ${cx} ${cy - r + 1} Q ${cx - r + 4} ${cy - r + 2} ${cx - r} ${cy - 2} Z" ${pathAttrs}/>`
  }
  if (style === 'bob') {
    return `<path d="M ${cx - r - 3} ${cy + 8} Q ${cx - r - 4} ${cy - r - 7} ${cx} ${cy - r - 7} Q ${cx + r + 4} ${cy - r - 7} ${cx + r + 3} ${cy + 8} Q ${cx + r + 1} ${cy - r + 1} ${cx} ${cy - r + 2} Q ${cx - r - 1} ${cy - r + 1} ${cx - r - 3} ${cy + 8} Z" ${pathAttrs}/>`
  }
  if (style === 'long') {
    return `<path d="M ${cx - r - 4} ${cy + 16} Q ${cx - r - 5} ${cy - r - 7} ${cx} ${cy - r - 7} Q ${cx + r + 5} ${cy - r - 7} ${cx + r + 4} ${cy + 16} L ${cx + r - 1} ${cy + 16} Q ${cx + r + 1} ${cy - r + 2} ${cx} ${cy - r + 1} Q ${cx - r - 1} ${cy - r + 2} ${cx - r + 1} ${cy + 16} Z" ${pathAttrs}/>`
  }
  if (style === 'bun') {
    return `<circle cx="${cx}" cy="${cy - r - 5}" r="5" fill="${hair}" stroke="${SVG_INK}" stroke-width="2.4"/><path d="M ${cx - r} ${cy - 2} Q ${cx - r - 1} ${cy - r - 5} ${cx} ${cy - r - 5} Q ${cx + r + 1} ${cy - r - 5} ${cx + r} ${cy - 2} Q ${cx + r - 4} ${cy - r + 2} ${cx} ${cy - r + 1} Q ${cx - r + 4} ${cy - r + 2} ${cx - r} ${cy - 2} Z" ${pathAttrs}/>`
  }
  if (style === 'curly') {
    return [
      [-11, -8, 6],
      [0, -11, 6.5],
      [11, -8, 6],
      [-14, 0, 5.5],
      [14, 0, 5.5]
    ]
      .map(
        ([dx, dy, radius]) =>
          `<circle cx="${cx + dx}" cy="${cy + dy}" r="${radius}" fill="${hair}" stroke="${SVG_INK}" stroke-width="2.2"/>`
      )
      .join('')
  }
  if (style === 'side') {
    return `<path d="M ${cx - r} ${cy - 3} Q ${cx - r - 1} ${cy - r - 6} ${cx + 2} ${cy - r - 6} Q ${cx + r + 2} ${cy - r - 5} ${cx + r} ${cy - 1} Q ${cx + r - 2} ${cy - r + 3} ${cx + 3} ${cy - r + 1} Q ${cx - r + 2} ${cy - r} ${cx - r} ${cy - 3} Z" ${pathAttrs}/>`
  }
  return ''
}

const buildAccessory = (accessory) => {
  const cx = FACE_CX
  const cy = FACE_CY
  if (accessory === 'glasses') {
    return [
      `<circle cx="${cx - 6.5}" cy="${cy + 1}" r="5" fill="none" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<circle cx="${cx + 6.5}" cy="${cy + 1}" r="5" fill="none" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<line x1="${cx - 1.5}" y1="${cy + 1}" x2="${cx + 1.5}" y2="${cy + 1}" stroke="${SVG_INK}" stroke-width="2"/>`
    ].join('')
  }
  if (accessory === 'clipboard') {
    return [
      `<rect x="45" y="40" width="13" height="16" rx="2" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<line x1="48" y1="45" x2="55" y2="45" stroke="${SVG_INK}" stroke-width="1.6"/>`,
      `<line x1="48" y1="49" x2="55" y2="49" stroke="${SVG_INK}" stroke-width="1.6"/>`
    ].join('')
  }
  if (accessory === 'check') {
    return `<circle cx="52" cy="48" r="8" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/><path d="M 48 48 L 51 51 L 56 45" fill="none" stroke="${SVG_INK}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>`
  }
  if (accessory === 'globe') {
    return `<circle cx="52" cy="48" r="8" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/><ellipse cx="52" cy="48" rx="3.5" ry="8" fill="none" stroke="${SVG_INK}" stroke-width="1.6"/><line x1="44" y1="48" x2="60" y2="48" stroke="${SVG_INK}" stroke-width="1.6"/>`
  }
  if (accessory === 'pen') {
    return `<path d="M 46 62 L 48 54 L 56 46 L 60 50 L 52 58 Z" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2" stroke-linejoin="round"/>`
  }
  if (accessory === 'chart') {
    return `<rect x="45" y="52" width="3.5" height="6" fill="${SVG_INK}"/><rect x="50" y="47" width="3.5" height="11" fill="${SVG_INK}"/><rect x="55" y="43" width="3.5" height="15" fill="${SVG_INK}"/>`
  }
  return ''
}

const buildAgentFaceSvg = (config) => {
  const { skin, hair, style, bg, accessory } = config
  const parts = [
    `<rect x="2" y="2" width="60" height="60" rx="14" fill="${bg}" stroke="${SVG_BORDER}" stroke-width="2"/>`,
    `<rect x="27" y="45" width="10" height="9" rx="3" fill="${skin}"/>`,
    `<path d="M 12 62 Q 14 50 32 50 Q 50 50 52 62 Z" fill="${SVG_SHIRT}"/>`,
    `<circle cx="${FACE_CX}" cy="${FACE_CY}" r="${FACE_R}" fill="${skin}" stroke="${SVG_INK}" stroke-width="2.6"/>`,
    `<circle cx="${FACE_CX - FACE_R + 1}" cy="${FACE_CY + 2}" r="3.2" fill="${skin}" stroke="${SVG_INK}" stroke-width="2.2"/>`,
    `<circle cx="${FACE_CX + FACE_R - 1}" cy="${FACE_CY + 2}" r="3.2" fill="${skin}" stroke="${SVG_INK}" stroke-width="2.2"/>`,
    buildHair(style, hair),
    `<line x1="${FACE_CX - 9}" y1="${FACE_CY - 5}" x2="${FACE_CX - 4}" y2="${FACE_CY - 6}" stroke="${SVG_INK}" stroke-width="2" stroke-linecap="round"/>`,
    `<line x1="${FACE_CX + 4}" y1="${FACE_CY - 6}" x2="${FACE_CX + 9}" y2="${FACE_CY - 5}" stroke="${SVG_INK}" stroke-width="2" stroke-linecap="round"/>`,
    `<circle cx="${FACE_CX - 6.5}" cy="${FACE_CY + 1}" r="2.1" fill="${SVG_INK}"/>`,
    `<circle cx="${FACE_CX + 6.5}" cy="${FACE_CY + 1}" r="2.1" fill="${SVG_INK}"/>`,
    `<path d="M ${FACE_CX} ${FACE_CY + 3} L ${FACE_CX} ${FACE_CY + 6}" stroke="${SVG_INK}" stroke-width="1.8" stroke-linecap="round"/>`,
    `<path d="M ${FACE_CX - 4} ${FACE_CY + 9} Q ${FACE_CX} ${FACE_CY + 12} ${FACE_CX + 4} ${FACE_CY + 9}" fill="none" stroke="${SVG_INK}" stroke-width="2" stroke-linecap="round"/>`,
    buildAccessory(accessory)
  ]
  return `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">\n${parts.filter(Boolean).join('\n')}\n</svg>`
}

/** 生成智能体默认头像 data URI；名称与描述均为空时返回空串，由调用方的首字母兜底接管。 */
export const generateAgentFaceAvatar = (name, description = '') => {
  const normalizedName = String(name || '').trim()
  const normalizedDescription = String(description || '').trim()
  if (!normalizedName && !normalizedDescription) return ''
  const svg = buildAgentFaceSvg(resolveAgentFaceConfig(normalizedName, normalizedDescription))
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}
