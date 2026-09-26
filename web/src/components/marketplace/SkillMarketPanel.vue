<template>
  <div class="skill-market-panel">
    <!-- 搜索 + 分类筛选 -->
    <div class="panel-toolbar">
      <a-input-search
        v-if="activeSourceType !== 'suite'"
        v-model:value="searchQuery"
        placeholder="搜索技能..."
        style="width: 250px"
        @search="handleSearch"
      />
      <div v-else class="panel-toolbar-search-spacer" />
      <a-tabs v-model:activeKey="activeSourceType" @change="handleSourceTypeChange" size="small">
        <a-tab-pane key="all" tab="全部" />
        <a-tab-pane key="suite" tab="套件" />
        <a-tab-pane key="builtin" tab="系统内置" />
        <a-tab-pane key="company" tab="公司精选" />
      </a-tabs>
    </div>

    <!-- 套件列表 -->
    <div v-if="activeSourceType === 'suite'" class="recommended-section">
      <div v-if="recommendedSuites.length > 0" class="suite-grid">
        <SkillSuiteCard
          v-for="suite in recommendedSuites"
          :key="suite.id"
          :suite="suite"
          :installed-slugs="installedSkillSlugs"
          @open="openSuiteInstall"
        />
      </div>
      <a-empty v-else description="暂无套件" />
    </div>

    <!-- 分类标签栏 -->
    <div v-if="activeSourceType !== 'suite'" class="category-tab-bar">
      <button
        v-for="cat in categoryTabs"
        :key="cat.key"
        type="button"
        class="tab-item"
        :class="{ active: selectedCategory === cat.key }"
        @click="selectedCategory = cat.key"
      >
        {{ cat.label }}
        <span v-if="categoryCounts[cat.key]" class="tab-count">{{ categoryCounts[cat.key] }}</span>
      </button>
    </div>

    <!-- 技能列表 -->
    <a-spin v-if="activeSourceType !== 'suite'" :spinning="loading">
      <div class="skill-grid" v-if="filteredEntries.length > 0">
        <div
          v-for="entry in filteredEntries"
          :key="entry.id"
          class="skill-card"
          @click="showDetail(entry)"
        >
          <div class="card-header">
            <div class="card-title">
              <span class="skill-icon">🔧</span>
              <span class="skill-name">{{ entry.title }}</span>
            </div>
            <a-tag v-if="entry.source_type === 'builtin'" color="blue">内置</a-tag>
            <a-tag v-else color="green">公司</a-tag>
          </div>
          <div class="card-body">
            <p class="skill-description">{{ entry.description }}</p>
          </div>
          <div class="card-footer">
            <div class="skill-meta">
              <span class="meta-item">
                <UserOutlined />
                {{ entry.author_nickname || entry.author_uid || '未知' }}
              </span>
              <span class="meta-item">
                <DownloadOutlined />
                {{ entry.install_count }}
              </span>
            </div>
            <a-button
              type="primary"
              size="small"
              :loading="installingSlug === entry.slug"
              @click.stop="handleInstall(entry)"
            >
              安装
            </a-button>
          </div>
        </div>
      </div>
      <a-empty v-else description="暂无技能" />
    </a-spin>

    <!-- 详情抽屉 -->
    <a-drawer
      v-model:open="detailVisible"
      :title="selectedEntry?.title"
      width="600"
      :body-style="{ paddingBottom: '80px' }"
    >
      <template v-if="selectedEntry">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="描述">{{ selectedEntry.description }}</a-descriptions-item>
          <a-descriptions-item label="来源">
            <a-tag v-if="selectedEntry.source_type === 'builtin'" color="blue">系统内置</a-tag>
            <a-tag v-else color="green">公司精选</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="贡献者">{{ selectedEntry.author_nickname || selectedEntry.author_uid || '未知' }}</a-descriptions-item>
          <a-descriptions-item label="安装次数">{{ selectedEntry.install_count }}</a-descriptions-item>
        </a-descriptions>

        <div class="detail-actions" style="margin-top: 24px">
          <a-button
            type="primary"
            :loading="installingSlug === selectedEntry.slug"
            @click="handleInstall(selectedEntry)"
          >
            安装到个人技能
          </a-button>
        </div>

        <a-divider>版本历史</a-divider>
        <a-timeline>
          <a-timeline-item
            v-for="version in selectedEntry.versions"
            :key="version.id"
            :color="version.is_latest ? 'green' : 'gray'"
          >
            <div class="version-item">
              <div class="version-header">
                <strong>v{{ version.version }}</strong>
                <a-tag v-if="version.is_latest" color="green">最新</a-tag>
                <a-tag>{{ version.change_type }}</a-tag>
              </div>
              <p class="version-notes">{{ version.release_notes || '无说明' }}</p>
              <div class="version-meta">
                <span>{{ version.submitted_by }}</span>
                <span>{{ formatDate(version.submitted_at) }}</span>
              </div>
            </div>
          </a-timeline-item>
        </a-timeline>
      </template>
    </a-drawer>

    <!-- 套件安装流程弹窗 -->
    <SkillInstallFlowModal
      :open="installFlowOpen"
      :flow="installFlow"
      @close="closeInstallFlow"
      @completed="handleInstallFlowCompleted"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { UserOutlined, DownloadOutlined } from '@ant-design/icons-vue'
import { marketplaceApi } from '@/apis/marketplace_api'
import { skillApi } from '@/apis/skill_api'
import { useCategories } from '@/composables/useCategories'
import SkillSuiteCard from '@/components/extensions/SkillSuiteCard.vue'
import SkillInstallFlowModal from '@/components/extensions/SkillInstallFlowModal.vue'

// ── 推荐套件 ──
const RECOMMENDED_SUITES = [
  {
    id: 'minimax-office-skills',
    name: 'MiniMax 办公文档套件',
    provider: 'MiniMax-AI',
    description:
      'MiniMax 开源的办公文档 Skills 合集，覆盖 DOCX、PDF、XLSX 与 PPTX 演示文稿的创建与格式化。',
    source: 'https://modelscope.cn/collections/MiniMax/MiniMax-Office-skills',
    skills: [
      { slug: 'pptx-generator', name: 'pptx-generator', description: '生成、编辑和阅读 PowerPoint 演示文稿。使用 PptxGenJS 从头开始创建，通过 XML 工作流编辑现有的 PPTX，或使用 markitdown 提取文本。' },
      { slug: 'minimax-docx', name: 'minimax-docx', description: '使用 OpenXML SDK（.NET）进行专业的 DOCX 文档创建、编辑和格式化，支持模板应用与 XSD 验证门控检查。' },
      { slug: 'minimax-xlsx', name: 'minimax-xlsx', description: '创建、读取、分析、编辑或验证 Excel/电子表格文件，支持公式重算校验与专业财务格式标准。' },
      { slug: 'minimax-pdf', name: 'minimax-pdf', description: '高视觉质量与设计感的 PDF 生成、表单字段填写、样式转换与专业打印级文档排版。' }
    ]
  },
  {
    id: 'skill-builder-suite',
    name: 'Skill 能力与进化套件',
    provider: 'Community',
    description: '用于 Agent 技能发现、创建、评测调优与自主进化的核心工具合集。',
    skills: [
      { slug: 'skill-creator', name: 'skill-creator', source: 'https://modelscope.cn/skills/@anthropics/skill-creator', description: '创建新技能、修改与优化现有技能，并通过方差基准分析评测技能表现与调优描述。' },
      { slug: 'find-skills', name: 'find-skills', source: 'https://modelscope.cn/skills/@vercel-labs/find-skills', description: '协助智能体根据用户需求检索并发现可安装的开源 Agent Skills，动态扩展自身能力。' },
      { slug: 'self-improving-agent', name: 'self-improving-agent', source: 'https://github.com/zhaono1/agent-playbook', description: '通用自我进化技能，基于多重记忆架构从经验与错误中持续学习并自我迭代。' }
    ]
  }
]

const recommendedSuites = computed(() =>
  RECOMMENDED_SUITES.map((suite) => ({ ...suite, isSuite: true }))
)

// ── 已安装技能 ──
const installedSkillSlugs = ref([])

const loadInstalledSkills = async () => {
  try {
    const res = await skillApi.listSkillCards()
    if (res?.success && Array.isArray(res.data)) {
      installedSkillSlugs.value = res.data
        .filter((s) => s.sourceScope === 'personal')
        .map((s) => s.slug)
    }
  } catch {
    // 静默失败，不影响市场列表加载
  }
}

// ── 套件安装流程 ──
const installFlowOpen = ref(false)
const installFlow = ref(null)

const openSuiteInstall = (suite) => {
  installFlow.value = {
    kind: 'suite',
    suite,
    installedSlugs: [...installedSkillSlugs.value]
  }
  installFlowOpen.value = true
}

const closeInstallFlow = () => {
  installFlowOpen.value = false
  installFlow.value = null
}

const handleInstallFlowCompleted = async ({ success, failed }) => {
  if (failed === 0) message.success(`已添加 ${success} 个 Skill`)
  else message.warning(`安装完成：成功 ${success} 个，失败 ${failed} 个`)
  closeInstallFlow()
  await loadInstalledSkills()
}

const loading = ref(false)
const entries = ref([])
const searchQuery = ref('')
const activeSourceType = ref('all')
const selectedCategory = ref('all')
const detailVisible = ref(false)
const selectedEntry = ref(null)
const installingSlug = ref(null)

// ── 分类标签 ──
const { categories: apiCategories, loadCategories } = useCategories('skill')

const categoryTabs = computed(() => [
  { key: 'all', label: '全部' },
  ...apiCategories.value.map((cat) => ({ key: cat.id, label: cat.label }))
])

const categoryCounts = computed(() => {
  const counts = { all: entries.value.length }
  for (const cat of apiCategories.value) {
    counts[cat.id] = entries.value.filter((e) => e.category_id === cat.id).length
  }
  return counts
})

const filteredEntries = computed(() => {
  if (activeSourceType.value === 'suite') return []
  let result = entries.value
  if (activeSourceType.value !== 'all') {
    result = result.filter(e => e.source_type === activeSourceType.value)
  }
  if (selectedCategory.value !== 'all') {
    result = result.filter(e => e.category_id === selectedCategory.value)
  }
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(e =>
      e.title.toLowerCase().includes(query) ||
      e.description.toLowerCase().includes(query)
    )
  }
  return result
})

const loadEntries = async () => {
  loading.value = true
  try {
    const res = await marketplaceApi.listEntries({ page_size: 100 })
    if (res.success) {
      entries.value = res.items
    }
  } catch (err) {
    message.error('加载技能列表失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  // 搜索通过 computed 自动过滤
}

const handleSourceTypeChange = () => {
  // 切换通过 computed 自动过滤
}

const showDetail = async (entry) => {
  try {
    const res = await marketplaceApi.getEntryDetail(entry.slug)
    if (res.success) {
      selectedEntry.value = res.data
      detailVisible.value = true
    }
  } catch (err) {
    message.error('加载详情失败')
  }
}

const handleInstall = async (entry) => {
  installingSlug.value = entry.slug
  try {
    const res = await marketplaceApi.installSkill(entry.slug)
    if (res.success) {
      const statusMap = {
        installed: '安装成功',
        already_installed: '已安装最新版本',
        updated: '更新成功',
      }
      message.success(statusMap[res.data.status] || '操作成功')
      // 刷新列表以更新安装次数
      await loadEntries()
    }
  } catch (err) {
    message.error(err.response?.data?.detail || '安装失败')
  } finally {
    installingSlug.value = null
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN')
}

onMounted(() => {
  loadEntries()
  loadInstalledSkills()
  loadCategories()
})
</script>

<style scoped>
.skill-market-panel {
  padding: 0;
}

.recommended-section {
  margin-bottom: 24px;
  padding: 0 var(--page-padding);
}

.section-header {
  margin-bottom: 12px;
}

.section-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #333;
}

.suite-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.panel-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px var(--page-padding) 0;
  gap: 16px;
}

/* 搜索栏占位，隐藏时保持 tab 右对齐 */
.panel-toolbar-search-spacer {
  width: 250px;
  flex-shrink: 0;
}

/* 分类标签栏 — 与技能列表页保持一致 */
:deep(.category-tab-bar) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 12px var(--page-padding) 0;
  flex-shrink: 0;
}

:deep(.category-tab-bar .tab-item) {
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
}

:deep(.category-tab-bar .tab-item:hover) {
  color: var(--gray-900);
  background-color: color-mix(in srgb, var(--gray-800) 4%, var(--gray-0));
}

:deep(.category-tab-bar .tab-item.active) {
  color: var(--gray-2000);
  background-color: color-mix(in srgb, var(--gray-800) 6%, var(--gray-0));
}

:deep(.category-tab-bar .tab-count) {
  margin-left: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--gray-400);
}

.skill-grid {
  padding: 0 var(--page-padding) 16px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.skill-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.3s;
  background: #fff;
}

.skill-card:hover {
  border-color: #1890ff;
  box-shadow: 0 2px 8px rgba(24, 144, 255, 0.15);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skill-icon {
  font-size: 20px;
}

.skill-name {
  font-weight: 600;
  font-size: 16px;
}

.card-body {
  margin-bottom: 12px;
}

.skill-description {
  margin: 0;
  color: #666;
  font-size: 14px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.skill-meta {
  display: flex;
  gap: 16px;
  color: #999;
  font-size: 12px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.version-item {
  padding: 8px 0;
}

.version-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.version-notes {
  margin: 8px 0;
  color: #666;
  font-size: 14px;
}

.version-meta {
  display: flex;
  justify-content: space-between;
  color: #999;
  font-size: 12px;
}

/* 空状态 padding */
:deep(.ant-empty) {
  padding: 40px var(--page-padding);
}
</style>
