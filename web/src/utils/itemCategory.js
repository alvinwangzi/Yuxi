/** 分类 key 列表（顺序即标签栏显示顺序） */
export const CATEGORIES = [
  'all',
  'office',
  'dev',
  'data',
  'content',
  'info',
  'business',
  'productivity',
  'other'
]

/** 分类中文标签 */
export const CATEGORY_LABELS = {
  all: '全部',
  office: '办公协同',
  dev: '开发工具',
  data: '数据分析',
  content: '内容创作',
  info: '信息资讯',
  business: '商业运营',
  productivity: '效率工具',
  other: '其他'
}

/**
 * 按分类优先级顺序排列的关键词映射。
 * 匹配时从上到下扫描，命中第一个分类即返回。
 */
const CATEGORY_KEYWORDS = [
  {
    key: 'office',
    words: [
      'excel', 'word', 'docx', 'pdf', 'ppt', 'xlsx', 'email', 'imap', 'smtp',
      'calendar', 'sheet', '表格', '文档', '邮件', '日程', '会议'
    ]
  },
  {
    key: 'dev',
    words: [
      'code', 'git', 'deploy', 'debug', 'terminal', 'shell', 'sql', 'mysql',
      'postgres', 'api', 'docker', 'frontend', 'backend', 'html', 'css',
      'javascript', 'typescript', 'react', 'vue', 'angular', 'database',
      '代码', '部署', '调试', '开发', '前端', '后端'
    ]
  },
  {
    key: 'data',
    words: [
      'data', 'chart', 'analytics', 'query', 'stock', 'finance', 'wind',
      '数据', '分析', '报表', '金融', '股票'
    ]
  },
  {
    key: 'content',
    words: [
      'write', 'translate', 'image', 'video', 'audio', 'blog', 'article',
      'markdown', 'podcast', 'music', 'design', 'draw', 'paint', 'photo',
      'graphic', 'animation', 'render', '写作', '翻译', '设计', '文稿',
      '播客', '音乐', '绘图'
    ]
  },
  {
    key: 'info',
    words: [
      'search', 'news', 'web', 'rss', 'crawl', 'monitor', 'alert', 'browse',
      'summary', '搜索', '新闻', '资讯', '舆情', '监控'
    ]
  },
  {
    key: 'business',
    words: [
      'crm', 'marketing', 'sales', 'ecommerce', 'shop', 'finance', 'invoice',
      'project', 'consult', 'analysis', 'management', 'enterprise', 'report',
      'plan', 'strategy', 'hr', 'erp', 'contract', 'proposal',
      '营销', '销售', '电商', '财务', '项目', '运营', '客户', '咨询',
      '管理', '企业', '报告', '商业'
    ]
  },
  {
    key: 'productivity',
    words: [
      'automate', 'workflow', 'reminder', 'schedule', 'task',
      '自动化', '工作流', '提醒', '任务'
    ]
  }
]

/**
 * 将多个字符串字段拼接后做关键词匹配。
 * @param {string[]} fields - 待匹配的文本字段
 * @returns {string} 分类 key
 */
function matchCategory(fields) {
  const text = fields.filter(Boolean).join(' ').toLowerCase()
  if (!text) return 'other'
  for (const { key, words } of CATEGORY_KEYWORDS) {
    if (words.some((w) => text.includes(w.toLowerCase()))) {
      return key
    }
  }
  return 'other'
}

/**
 * 推断 Skill 的分类。
 * @param {{ slug: string, name: string, tool_dependencies: string[], mcp_dependencies: string[] }} skill
 * @returns {string} 分类 key
 */
export function inferSkillCategory(skill) {
  return matchCategory([
    skill.slug,
    skill.name,
    ...(skill.tool_dependencies || []),
    ...(skill.mcp_dependencies || [])
  ])
}

/**
 * 推断 Tool 的分类（映射已有 category 字段）。
 * @param {{ category?: string }} tool
 * @returns {string} 分类 key
 */
export function inferToolCategory(tool) {
  const mapping = {
    buildin: 'productivity',
    knowledge: 'productivity',
    mysql: 'data',
    debug: 'dev'
  }
  return mapping[tool.category] || 'other'
}

/**
 * 推断 Agent 的分类。
 * @param {{ name: string, description: string }} agent
 * @returns {string} 分类 key
 */
export function inferAgentCategory(agent) {
  return matchCategory([agent.name, agent.description])
}

/**
 * 推断 MCP Server 的分类。
 * @param {{ name: string, description: string, tags?: string[] }} server
 * @returns {string} 分类 key
 */
export function inferMcpCategory(server) {
  return matchCategory([server.name, server.description, ...(server.tags || [])])
}
