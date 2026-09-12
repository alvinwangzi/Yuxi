# 扩展页面二级分类标签栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在技能、工具、MCP、智能体四个扩展管理页面新增水平可滚动的二级分类标签栏，基于关键词自动推断分类，帮助用户按业务场景快速筛选内容。

**Architecture:** 新增一个纯函数工具模块 `itemCategory.js` 提供分类定义和推断逻辑，四个页面组件各自引入该模块，在 `PageShoulder` 下方渲染分类标签栏，通过 `computed` 联动搜索与分类过滤。

**Tech Stack:** Vue 3 `<script setup>`, Ant Design Vue, LESS, node:test

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `web/src/utils/itemCategory.js` | Create | 分类定义 + 推断函数（纯逻辑，无 Vue 依赖） |
| `web/test/unit/itemCategory.test.js` | Create | itemCategory 推断逻辑单元测试 |
| `web/src/components/extensions/SkillCardList.vue` | Modify | 新增分类标签栏，过滤逻辑接入 |
| `web/src/components/extensions/ToolsCardList.vue` | Modify | 下拉替换为标签栏，分类映射接入 |
| `web/src/components/extensions/McpCardList.vue` | Modify | 新增分类标签栏 |
| `web/src/components/model-management/AgentManagePanel.vue` | Modify | 新增分类标签栏 |

---

### Task 1: 创建分类推断工具模块

**Files:**
- Create: `web/src/utils/itemCategory.js`
- Create: `web/test/unit/itemCategory.test.js`

- [ ] **Step 1: 编写单元测试**

```js
// web/test/unit/itemCategory.test.js
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
})

test('inferSkillCategory 按 tool_dependencies 匹配数据分析', () => {
  assert.equal(inferSkillCategory({ slug: 'x', name: 'y', tool_dependencies: ['mysql'], mcp_dependencies: [] }), 'data')
})

test('inferSkillCategory 按 mcp_dependencies 匹配信息资讯', () => {
  assert.equal(inferSkillCategory({ slug: 'x', name: 'y', tool_dependencies: [], mcp_dependencies: ['web-search'] }), 'info')
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
  assert.equal(inferAgentCategory({ name: 'Random Agent', description: 'Does random things' }), 'other')
})

test('inferMcpCategory 按 name + description + tags 匹配', () => {
  assert.equal(inferMcpCategory({ name: 'Web Search', description: '', tags: [] }), 'info')
  assert.equal(inferMcpCategory({ name: 'DB Connector', description: '', tags: ['mysql'] }), 'data')
  assert.equal(inferMcpCategory({ name: 'Random MCP', description: '', tags: [] }), 'other')
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd d:\AIProjects\Yuxi\web && node --test test/unit/itemCategory.test.js
```
Expected: FAIL — module not found

- [ ] **Step 3: 实现 itemCategory.js**

```js
// web/src/utils/itemCategory.js

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
      'postgres', 'api', 'docker', '代码', '部署', '调试'
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
      'markdown', '写作', '翻译', '设计', '文稿'
    ]
  },
  {
    key: 'info',
    words: [
      'search', 'news', 'web', 'rss', 'crawl', 'monitor', 'alert',
      '搜索', '新闻', '资讯', '舆情', '监控'
    ]
  },
  {
    key: 'business',
    words: [
      'crm', 'marketing', 'sales', 'ecommerce', 'shop', 'finance', 'invoice',
      'project', '营销', '销售', '电商', '财务', '项目', '运营', '客户'
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd d:\AIProjects\Yuxi\web && node --test test/unit/itemCategory.test.js
```
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/utils/itemCategory.js web/test/unit/itemCategory.test.js
git commit -m "feat: add itemCategory utility for extension page classification"
```

---

### Task 2: 技能页面接入分类标签栏

**Files:**
- Modify: `web/src/components/extensions/SkillCardList.vue`

- [ ] **Step 1: 在 `<script setup>` 中引入分类模块并添加状态**

在 `import` 区域（约 line 516）后添加：
```js
import { CATEGORIES, CATEGORY_LABELS, inferSkillCategory } from '@/utils/itemCategory'
```

在 `const searchQuery = ref('')` 后添加：
```js
const selectedCategory = ref('all')
```

- [ ] **Step 2: 为每个 skill 附加分类，修改 `installedSkillCards`**

将 line 656-662 的 `installedSkillCards` 改为：
```js
const installedSkillCards = computed(() =>
  (skills.value || []).map((skill) => ({
    ...skill,
    sourceType: skill.source_type || 'upload',
    sourceScope: skill.source_scope,
    category: inferSkillCategory({
      slug: skill.slug || '',
      name: skill.name || '',
      tool_dependencies: skill.tool_dependencies || [],
      mcp_dependencies: skill.mcp_dependencies || []
    })
  }))
)
```

- [ ] **Step 3: 修改过滤逻辑，接入分类过滤**

将 line 680 的 `filteredInstalledSkills` 改为：
```js
const filteredInstalledSkills = computed(() => {
  let result = installedSkillCards.value
  if (selectedCategory.value !== 'all') {
    result = result.filter((skill) => skill.category === selectedCategory.value)
  }
  return result.filter(matchesSearch)
})
```

- [ ] **Step 4: 添加分类统计 computed**

在 `filteredInstalledSkills` 之后添加：
```js
const categoryCounts = computed(() => {
  const counts = { all: installedSkillCards.value.length }
  for (const key of CATEGORIES) {
    if (key === 'all') continue
    counts[key] = installedSkillCards.value.filter((s) => s.category === key).length
  }
  return counts
})
```

- [ ] **Step 5: 在模板中 PageShoulder 之后添加分类标签栏**

在 line 58（`</PageShoulder>` 之后）和 line 60（`<div` 之前）之间插入：
```html
    <div class="category-tab-bar">
      <button
        v-for="key in CATEGORIES"
        :key="key"
        type="button"
        class="tab-item"
        :class="{ active: selectedCategory === key }"
        @click="selectedCategory = key"
      >
        {{ CATEGORY_LABELS[key] }}
        <span v-if="categoryCounts[key]" class="tab-count">{{ categoryCounts[key] }}</span>
      </button>
    </div>
```

- [ ] **Step 6: 添加分类标签栏样式**

在 `<style scoped lang="less">` 区域末尾（line 135 之前）添加：
```less
.category-tab-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px var(--page-padding) 0;
  overflow-x: auto;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }

  .tab-item {
    display: inline-flex;
    align-items: center;
    height: 28px;
    padding: 0 10px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--gray-600);
    font-size: 14px;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    transition: background-color 0.2s ease, color 0.2s ease;
    white-space: nowrap;
    flex-shrink: 0;

    &:hover {
      color: var(--gray-900);
      background-color: color-mix(in srgb, var(--gray-800) 4%, var(--gray-0));
    }

    &.active {
      color: var(--gray-2000);
      background-color: color-mix(in srgb, var(--gray-800) 6%, var(--gray-0));
    }
  }

  .tab-count {
    margin-left: 4px;
    font-size: 11px;
    font-weight: 600;
    color: var(--gray-400);
  }
}
```

- [ ] **Step 7: 验证前端无编译错误**

```bash
cd d:\AIProjects\Yuxi\web && npx vite build --mode development 2>&1 | Select-String -Pattern "error"
```
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add web/src/components/extensions/SkillCardList.vue
git commit -m "feat: add category tab bar to skills page"
```

---

### Task 3: 工具页面 — 下拉替换为标签栏

**Files:**
- Modify: `web/src/components/extensions/ToolsCardList.vue`

- [ ] **Step 1: 替换 import 和添加分类模块引用**

将 line 114-122 的 import 块改为：
```js
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { Wrench, RefreshCw, FileText, Tag, Tags, List } from '@lucide/vue'
import { toolApi } from '@/apis/tool_api'
import { getToolIcon } from '@/components/ToolCallingResult/toolRegistry'
import ExtensionCardGrid from './ExtensionCardGrid.vue'
import InfoCard from '@/components/shared/InfoCard.vue'
import PageShoulder from '@/components/shared/PageShoulder.vue'
import { formatExtensionCardTitle } from '@/utils/extensionDisplayName'
import { CATEGORIES, CATEGORY_LABELS, inferToolCategory } from '@/utils/itemCategory'
```

- [ ] **Step 2: 替换分类相关变量**

将 line 128-135 的 `selectedCategory`、`categories`、`categoryLabels`、`categoryColors` 替换为：
```js
const selectedCategory = ref('all')
```

删除 `categories`、`categoryLabels`、`categoryColors` 三行（line 133-135）。

- [ ] **Step 3: 修改 toolTags 函数使用新分类体系**

将 line 139-149 的 `toolTags` 改为：
```js
const toolTags = (tool) => {
  const tags = []
  const cat = inferToolCategory(tool)
  if (cat !== 'other') {
    tags.push({ name: CATEGORY_LABELS[cat], color: 'blue' })
  }
  ;(tool.tags || []).slice(0, 2).forEach((t) => tags.push(t))
  return tags
}
```

- [ ] **Step 4: 修改 filteredTools 使用新分类**

将 line 157-173 的 `filteredTools` 改为：
```js
const filteredTools = computed(() => {
  let result = tools.value.map((t) => ({
    ...t,
    category: inferToolCategory(t)
  }))
  if (selectedCategory.value !== 'all') {
    result = result.filter((t) => t.category === selectedCategory.value)
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    result = result.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        getToolSlug(t).toLowerCase().includes(q) ||
        t.description?.toLowerCase().includes(q) ||
        t.config_guide?.toLowerCase().includes(q)
    )
  }
  return result
})
```

- [ ] **Step 5: 添加分类统计**

在 `filteredTools` 之后添加：
```js
const categoryCounts = computed(() => {
  const allTools = tools.value.map((t) => ({ ...t, category: inferToolCategory(t) }))
  const counts = { all: allTools.length }
  for (const key of CATEGORIES) {
    if (key === 'all') continue
    counts[key] = allTools.filter((t) => t.category === key).length
  }
  return counts
})
```

- [ ] **Step 6: 模板 — 替换下拉为标签栏**

将 line 4-16 的 `<template #filters>` 块（含 `a-select`）替换为：
```html
    <div class="category-tab-bar">
      <button
        v-for="key in CATEGORIES"
        :key="key"
        type="button"
        class="tab-item"
        :class="{ active: selectedCategory === key }"
        @click="selectedCategory = key"
      >
        {{ CATEGORY_LABELS[key] }}
        <span v-if="categoryCounts[key]" class="tab-count">{{ categoryCounts[key] }}</span>
      </button>
    </div>
```

注意：这个标签栏放在 `PageShoulder` 的 `#filters` slot 内，因为 `PageShoulder` 的 `#filters` slot 渲染在搜索框右侧同一行。但为了与截图一致（标签栏在搜索栏下方独占一行），更好的做法是将标签栏放在 `PageShoulder` 组件之后。

改为：删除 `<template #filters>` 整个块（line 4-16），在 `</PageShoulder>` 之后（line 24 之后）添加标签栏：
```html
    <div class="category-tab-bar">
      <button
        v-for="key in CATEGORIES"
        :key="key"
        type="button"
        class="tab-item"
        :class="{ active: selectedCategory === key }"
        @click="selectedCategory = key"
      >
        {{ CATEGORY_LABELS[key] }}
        <span v-if="categoryCounts[key]" class="tab-count">{{ categoryCounts[key] }}</span>
      </button>
    </div>
```

- [ ] **Step 7: 更新详情弹窗中的分类显示**

将 line 74 的 `categoryColors[currentTool.category]` 和 line 75 的 `categoryLabels[currentTool.category]` 改为使用新分类：
```html
<a-tag color="blue">
  {{ CATEGORY_LABELS[inferToolCategory(currentTool)] || '其他' }}
</a-tag>
```

- [ ] **Step 8: 添加样式**

在 `<style>` 区域末尾添加与 Task 2 Step 6 相同的 `.category-tab-bar` 样式块。

- [ ] **Step 9: Commit**

```bash
git add web/src/components/extensions/ToolsCardList.vue
git commit -m "feat: replace tool category dropdown with tab bar"
```

---

### Task 4: MCP 页面接入分类标签栏

**Files:**
- Modify: `web/src/components/extensions/McpCardList.vue`

- [ ] **Step 1: 引入分类模块**

在 import 区域（line 162-172）后添加：
```js
import { CATEGORIES, CATEGORY_LABELS, inferMcpCategory } from '@/utils/itemCategory'
```

- [ ] **Step 2: 添加状态**

在 `const searchQuery = ref('')` 后添加：
```js
const selectedCategory = ref('all')
```

- [ ] **Step 3: 修改 filteredServers 附加分类并接入过滤**

将 line 184-196 的 `filteredServers` 改为：
```js
const filteredServers = computed(() => {
  const sorted = [...servers.value]
    .map((s) => ({
      ...s,
      category: inferMcpCategory({ name: s.name || '', description: s.description || '', tags: s.tags || [] })
    }))
    .sort((a, b) =>
      String(a.name || '').localeCompare(String(b.name || ''), 'zh-Hans-CN', {
        sensitivity: 'base',
        numeric: true
      })
    )
  let result = sorted
  if (selectedCategory.value !== 'all') {
    result = result.filter((s) => s.category === selectedCategory.value)
  }
  if (!searchQuery.value) return result
  const q = searchQuery.value.toLowerCase()
  return result.filter(
    (s) => s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
  )
})
```

- [ ] **Step 4: 添加分类统计**

在 `filteredServers` 之后添加：
```js
const categoryCounts = computed(() => {
  const allServers = servers.value.map((s) => ({
    ...s,
    category: inferMcpCategory({ name: s.name || '', description: s.description || '', tags: s.tags || [] })
  }))
  const counts = { all: allServers.length }
  for (const key of CATEGORIES) {
    if (key === 'all') continue
    counts[key] = allServers.filter((s) => s.category === key).length
  }
  return counts
})
```

- [ ] **Step 5: 模板 — 在 PageShoulder 后添加标签栏**

在 line 15（`</PageShoulder>`）之后插入：
```html
    <div class="category-tab-bar">
      <button
        v-for="key in CATEGORIES"
        :key="key"
        type="button"
        class="tab-item"
        :class="{ active: selectedCategory === key }"
        @click="selectedCategory = key"
      >
        {{ CATEGORY_LABELS[key] }}
        <span v-if="categoryCounts[key]" class="tab-count">{{ categoryCounts[key] }}</span>
      </button>
    </div>
```

- [ ] **Step 6: 添加样式**

在 `<style>` 区域末尾添加与 Task 2 Step 6 相同的 `.category-tab-bar` 样式块。

- [ ] **Step 7: Commit**

```bash
git add web/src/components/extensions/McpCardList.vue
git commit -m "feat: add category tab bar to MCP page"
```

---

### Task 5: 智能体页面接入分类标签栏

**Files:**
- Modify: `web/src/components/model-management/AgentManagePanel.vue`

- [ ] **Step 1: 引入分类模块**

在 import 区域（line 1-16）后添加：
```js
import { CATEGORIES, CATEGORY_LABELS, inferAgentCategory } from '@/utils/itemCategory'
```

- [ ] **Step 2: 添加状态**

在 `const searchQuery = ref('')` 后添加：
```js
const selectedCategory = ref('all')
```

- [ ] **Step 3: 修改 filteredAgents 附加分类并接入过滤**

将 line 27-48 的 `filteredAgents` 改为：
```js
const filteredAgents = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  const list = (managedAgents.value || []).map((agent) => ({
    ...agent,
    category: inferAgentCategory({ name: agent.name || '', description: agent.description || '' })
  }))
  const filtered = keyword
    ? list.filter(
        (agent) =>
          String(agent.name || '')
            .toLowerCase()
            .includes(keyword) ||
          String(agent.id || '')
            .toLowerCase()
            .includes(keyword) ||
          String(agent.backend_id || '')
            .toLowerCase()
            .includes(keyword)
      )
    : list
  let categoryFiltered = filtered
  if (selectedCategory.value !== 'all') {
    categoryFiltered = filtered.filter((agent) => agent.category === selectedCategory.value)
  }
  return [...categoryFiltered].sort((a, b) => {
    if (isBuiltinAgent(a) !== isBuiltinAgent(b)) return isBuiltinAgent(a) ? -1 : 1
    return String(a.name || a.id).localeCompare(String(b.name || b.id), 'zh-CN')
  })
})
```

- [ ] **Step 4: 添加分类统计**

在 `filteredAgents` 之后添加：
```js
const categoryCounts = computed(() => {
  const allAgents = (managedAgents.value || []).map((agent) => ({
    ...agent,
    category: inferAgentCategory({ name: agent.name || '', description: agent.description || '' })
  }))
  const counts = { all: allAgents.length }
  for (const key of CATEGORIES) {
    if (key === 'all') continue
    counts[key] = allAgents.filter((a) => a.category === key).length
  }
  return counts
})
```

- [ ] **Step 5: 模板 — 在 PageShoulder 后添加标签栏**

在 line 159（`</PageShoulder>`）之后插入：
```html
    <div class="category-tab-bar">
      <button
        v-for="key in CATEGORIES"
        :key="key"
        type="button"
        class="tab-item"
        :class="{ active: selectedCategory === key }"
        @click="selectedCategory = key"
      >
        {{ CATEGORY_LABELS[key] }}
        <span v-if="categoryCounts[key]" class="tab-count">{{ categoryCounts[key] }}</span>
      </button>
    </div>
```

- [ ] **Step 6: 添加样式**

在 `<style>` 区域末尾添加与 Task 2 Step 6 相同的 `.category-tab-bar` 样式块。

- [ ] **Step 7: Commit**

```bash
git add web/src/components/model-management/AgentManagePanel.vue
git commit -m "feat: add category tab bar to agent manage page"
```

---

### Task 6: 提取共用样式到 extensions.less

**Files:**
- Modify: `web/src/assets/css/extensions.less`

- [ ] **Step 1: 将 `.category-tab-bar` 样式提取到 extensions.less**

在文件末尾（line 839 之后）添加：
```less
/* Category Tab Bar — shared across extension pages */
.category-tab-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px var(--page-padding) 0;
  overflow-x: auto;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }

  .tab-item {
    display: inline-flex;
    align-items: center;
    height: 28px;
    padding: 0 10px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--gray-600);
    font-size: 14px;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    transition: background-color 0.2s ease, color 0.2s ease;
    white-space: nowrap;
    flex-shrink: 0;

    &:hover {
      color: var(--gray-900);
      background-color: color-mix(in srgb, var(--gray-800) 4%, var(--gray-0));
    }

    &.active {
      color: var(--gray-2000);
      background-color: color-mix(in srgb, var(--gray-800) 6%, var(--gray-0));
    }
  }

  .tab-count {
    margin-left: 4px;
    font-size: 11px;
    font-weight: 600;
    color: var(--gray-400);
  }
}
```

- [ ] **Step 2: 从四个组件中删除重复的 `.category-tab-bar` 样式块**

从以下文件的 `<style>` 中删除 `.category-tab-bar` 块（保留 `@import '@/assets/css/extensions.less';` 即可自动继承）：
- `SkillCardList.vue`
- `ToolsCardList.vue`
- `McpCardList.vue`
- `AgentManagePanel.vue`

- [ ] **Step 3: Commit**

```bash
git add web/src/assets/css/extensions.less web/src/components/extensions/SkillCardList.vue web/src/components/extensions/ToolsCardList.vue web/src/components/extensions/McpCardList.vue web/src/components/model-management/AgentManagePanel.vue
git commit -m "refactor: extract category tab bar styles to extensions.less"
```

---

### Task 7: 运行全部单元测试

- [ ] **Step 1: 运行前端单元测试**

```bash
cd d:\AIProjects\Yuxi\web && pnpm test:unit
```
Expected: All tests PASS (including new `itemCategory.test.js`)

- [ ] **Step 2: 验证开发服务器无编译错误**

```bash
cd d:\AIProjects\Yuxi\web && npx vite build --mode development
```
Expected: Build succeeds with no errors
