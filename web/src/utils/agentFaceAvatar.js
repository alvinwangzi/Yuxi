// 智能体默认头像：按名称与描述确定性生成 Notion 风格人像 SVG data URI。
// 词典按企业应用场景组织；词表、十三类配饰对应关系与裁决顺序由本文件拥有。

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
// 含两个 null：无词典命中的智能体约 2/15 概率无配饰，对应「通用助手」型角色。
const ACCESSORY_FALLBACKS = [
  'glasses', 'clipboard', 'check', 'globe', 'pen', 'chart',
  'terminal', 'palette', 'megaphone', 'target', 'coins', 'users',
  'briefcase', null, null
]

// 企业场景词典，参考 The Agency 智能体角色清单（engineering/design/marketing 等部门）初始化。
// 数组顺序即多词命中时的裁决顺序；标题先于描述参与匹配。
// 维护约束：新增关键词不得是其他更靠前类别关键词的子串，否则逐条断言测试会失败。
export const AGENT_FACE_SCENARIOS = [
  {
    // check 置于 terminal 前：使「测试工程师」「安全工程师」仍归质检，而
    // 「前端工程师」「算法工程师」等无质检词的工程师角色落入开发工程。
    accessory: 'check',
    label: '审核与合规',
    keywords: [
      '核查', '校验', '审核', '审校', '合规', '审计', '风控', '质检', '测试',
      '验收', '安全', '法务', '合同', '审批', '对账', '巡检', '复核', '运维',
      '认证', '漏洞', '渗透', '用例', '回归', '缺陷', '诉讼', '法规'
    ]
  },
  {
    accessory: 'terminal',
    label: '开发工程',
    keywords: [
      '前端', '后端', '开发', '工程师', '架构', '代码', '程序', '编程', '算法',
      '接口', '数据库', '部署', '集成', '插件', '脚本', '小程序', '游戏', '云计算',
      '大模型', '机器学习', '人工智能', '自动化', 'DevOps', '持续集成'
    ]
  },
  {
    accessory: 'palette',
    label: '设计创意',
    keywords: [
      '设计', '视觉', '界面', '插画', '原型', '配色', '图标', '海报', '美工',
      '品牌', 'logo', 'UI', 'UX'
    ]
  },
  {
    accessory: 'megaphone',
    label: '营销传播',
    keywords: [
      '营销', '推广', '投放', '广告', '社媒', '直播', '带货', '种草', '涨粉',
      '拉新', '留存', '转化', '公关', '口碑', '爆款', '私域', '短视频', 'SEO'
    ]
  },
  {
    // target 置于 globe 前：电商客服等销售与客服交叉词优先归销售域。
    accessory: 'target',
    label: '销售与增长',
    keywords: [
      '销售', '营收', '增长', '电商', '零售', '商机', '业绩', '签单',
      '客户', '渠道', '经销', '拓客', '获客', '成单'
    ]
  },
  {
    accessory: 'globe',
    label: '外部信息与检索',
    keywords: [
      '搜索', '检索', '网页', '联网', '爬虫', '舆情', '资讯', '竞品', '情报',
      '问答', '客服', '售后', '帮助', '支持', '外贸', '工单', '答疑'
    ]
  },
  {
    accessory: 'pen',
    label: '写作与文档',
    keywords: [
      '写作', '文案', '撰写', '起草', '编辑', '润色', '报告', '公文', '纪要',
      '总结', '新闻', '内容', '邮件', '翻译', '培训', '课程', '文档', '通知',
      '周报', '讲稿', '教程', '手册', '摘要', '简报', '博客', '故事', '剧本',
      '小说', '软文', '推文'
    ]
  },
  {
    // chart 只收数据与量化职能；财务、销售岗位各有独立配饰。
    accessory: 'chart',
    label: '数据与量化',
    keywords: [
      '数据', '分析', '统计', '报表', '指标', '监控', '大盘', '预测', '绩效',
      '库存', '经营', '运营', '考核', 'KPI'
    ]
  },
  {
    // coins 置于 chart 后：财务报表、财务分析等量化词仍归柱状图，纯财务词归硬币。
    accessory: 'coins',
    label: '财务与会计',
    keywords: [
      '财务', '会计', '税务', '发票', '报销', '记账', '核算', '成本',
      '预算', '现金流', '资产', '估值', '投资', '资金', '账单'
    ]
  },
  {
    accessory: 'clipboard',
    label: '调研与归档',
    keywords: [
      '调研', '访谈', '收集', '采集', '整理', '归档', '盘点', '索引', '知识库',
      '资料', '录入', '清单', '档案', '记录', '登记', '调查', '问卷', '回访'
    ]
  },
  {
    // users 置于 clipboard 后：调研归档优先，纯人事词归双人形。
    accessory: 'users',
    label: '人事与行政',
    keywords: [
      '招聘', '人事', '行政', '入职', '薪酬', '考勤', '简历', '人力',
      '员工', '团队', '组织', 'HR'
    ]
  },
  {
    accessory: 'glasses',
    label: '研究与咨询',
    keywords: [
      '研究', '深入', '学术', '论文', '专家', '顾问', '咨询', '评估', '评审',
      '洞察', '策略', '规划', '方案', '决策', '项目管理', '产品', '需求', '趋势',
      '心理'
    ]
  },
  {
    // briefcase 置于最后：含业务领域词的管理者（销售总监、首席财务官）先归业务域，
    // 纯管理身份词（CEO、总监、经理）才落到领导管理。
    accessory: 'briefcase',
    label: '领导与管理',
    keywords: [
      'CEO', 'CTO', 'CFO', 'COO', 'CMO', '首席', '总裁', '总经理', '总监',
      '主管', '经理', '管理', '领导', '负责人', '合伙人', '董事'
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
  if (accessory === 'terminal') {
    return [
      `<rect x="44.5" y="41" width="14" height="12" rx="2" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<path d="M 47.5 44.5 L 50 47 L 47.5 49.5" fill="none" stroke="${SVG_INK}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>`,
      `<line x1="51.5" y1="49.5" x2="55.5" y2="49.5" stroke="${SVG_INK}" stroke-width="1.6" stroke-linecap="round"/>`
    ].join('')
  }
  if (accessory === 'palette') {
    return [
      `<circle cx="52" cy="47.5" r="8" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<circle cx="55.5" cy="50.5" r="2.4" fill="none" stroke="${SVG_INK}" stroke-width="1.6"/>`,
      `<circle cx="49" cy="44.5" r="1.5" fill="${SVG_INK}"/>`,
      `<circle cx="55" cy="43.5" r="1.5" fill="${SVG_INK}"/>`
    ].join('')
  }
  if (accessory === 'megaphone') {
    return [
      `<path d="M 47.5 45 L 58 40.5 L 58 51.5 L 45.5 52 Z" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2" stroke-linejoin="round"/>`,
      `<path d="M 47 52.5 L 46 56 L 49.5 55.5" fill="none" stroke="${SVG_INK}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`,
      `<path d="M 60.5 43.5 Q 61 46 60.5 48.5" fill="none" stroke="${SVG_INK}" stroke-width="1.6" stroke-linecap="round"/>`
    ].join('')
  }
  if (accessory === 'target') {
    return [
      `<circle cx="52" cy="48" r="8" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<circle cx="52" cy="48" r="4.5" fill="none" stroke="${SVG_INK}" stroke-width="1.6"/>`,
      `<circle cx="52" cy="48" r="1.6" fill="${SVG_INK}"/>`
    ].join('')
  }
  if (accessory === 'coins') {
    return [
      `<ellipse cx="52" cy="54" rx="7" ry="2.6" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<ellipse cx="52" cy="50" rx="7" ry="2.6" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<ellipse cx="52" cy="46" rx="7" ry="2.6" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/>`
    ].join('')
  }
  if (accessory === 'users') {
    return [
      `<circle cx="48.5" cy="45.5" r="3" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="1.8"/>`,
      `<path d="M 43.5 56.5 Q 43.5 50.5 48.5 50.5 Q 53.5 50.5 53.5 56.5" fill="none" stroke="${SVG_INK}" stroke-width="1.8" stroke-linecap="round"/>`,
      `<circle cx="56.5" cy="44.5" r="2.6" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="1.8"/>`,
      `<path d="M 55.5 49.8 Q 60.5 50.2 60.5 55.5" fill="none" stroke="${SVG_INK}" stroke-width="1.8" stroke-linecap="round"/>`
    ].join('')
  }
  if (accessory === 'briefcase') {
    return [
      `<rect x="45" y="45" width="14" height="10" rx="2" fill="#fdfcf9" stroke="${SVG_INK}" stroke-width="2"/>`,
      `<path d="M 49.5 45 L 49.5 42.5 Q 49.5 41.5 50.5 41.5 L 53.5 41.5 Q 54.5 41.5 54.5 42.5 L 54.5 45" fill="none" stroke="${SVG_INK}" stroke-width="1.8"/>`,
      `<line x1="45" y1="49.5" x2="59" y2="49.5" stroke="${SVG_INK}" stroke-width="1.6"/>`
    ].join('')
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
