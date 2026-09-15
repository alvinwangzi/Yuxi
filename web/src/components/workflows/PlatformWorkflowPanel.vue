<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { Download, Layers, User, RefreshCw } from '@lucide/vue'

import { workflowApi } from '@/apis/workflow_api'
import { useCategories } from '@/composables/useCategories'
import InfoCard from '@/components/shared/InfoCard.vue'
import ExtensionCardGrid from '@/components/extensions/ExtensionCardGrid.vue'
import PageShoulder from '@/components/shared/PageShoulder.vue'

const router = useRouter()
const { categories: workflowCategories, loadCategories: loadWorkflowCategories } = useCategories('workflow')

const loading = ref(false)
const platformWorkflows = ref([])
const searchQuery = ref('')
const selectedCategory = ref('all')

const SCOPE_LABELS = { company: '公司', department: '部门', personal: '个人' }

const categoryTabOptions = computed(() => {
  const options = [{ label: '全部', value: 'all' }]
  for (const cat of workflowCategories.value) {
    options.push({ label: cat.label, value: String(cat.id) })
  }
  return options
})

// 分类计数（兼容 category_id 和旧 category 字符串字段）
const categoryCounts = computed(() => {
  const counts = { all: platformWorkflows.value.length }
  for (const cat of workflowCategories.value) {
    counts[String(cat.id)] = platformWorkflows.value.filter(wf => {
      if (wf.category_id && String(wf.category_id) === String(cat.id)) return true
      if (wf.category && wf.category === cat.slug) return true
      return false
    }).length
  }
  return counts
})

// 前端过滤（搜索 + 分类）
const filteredWorkflows = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  let list = platformWorkflows.value

  if (keyword) {
    list = list.filter(wf =>
      String(wf.name || '').toLowerCase().includes(keyword) ||
      String(wf.description || '').toLowerCase().includes(keyword)
    )
  }

  if (selectedCategory.value !== 'all') {
    list = list.filter(wf => {
      if (wf.category_id && String(wf.category_id) === selectedCategory.value) return true
      const cat = workflowCategories.value.find(c => String(c.id) === selectedCategory.value)
      if (cat && wf.category && wf.category === cat.slug) return true
      return false
    })
  }

  return list
})

const getWorkflowIcon = (wf) => {
  const icon = wf.icon
  if (!icon) return '🔄'
  if (icon.length > 4) return '🔄'
  const EMOJI_REGEX = /^[\p{Emoji}\u200d\ufe0f\u20e3\u2600-\u27bf\u2b50\u2b55]+$/u
  if (EMOJI_REGEX.test(icon)) return icon
  return '🔄'
}

const buildTags = (wf) => {
  const tags = []
  if (wf.category_id) {
    const cat = workflowCategories.value.find(c => c.id === wf.category_id)
    if (cat) tags.push({ name: cat.label, color: 'gray' })
  } else if (wf.category) {
    const cat = workflowCategories.value.find(c => c.slug === wf.category)
    if (cat) tags.push({ name: cat.label, color: 'gray' })
  }
  const stepCount = wf.definition?.steps?.length || 0
  if (stepCount) tags.push({ name: `${stepCount} 步骤`, color: 'blue' })
  return tags
}

const loadPlatformWorkflows = async () => {
  loading.value = true
  try {
    const params = {}
    if (selectedCategory.value !== 'all') {
      params.category_id = Number(selectedCategory.value)
    }
    const res = await workflowApi.listPlatform(params)
    platformWorkflows.value = res.data || []
  } catch (error) {
    console.error('加载平台工作流失败:', error)
    message.error('加载平台工作流失败')
  } finally {
    loading.value = false
  }
}

const handleImport = async (wf) => {
  // 先检查缺失的 Agent
  let missingAgents = []
  try {
    const checkRes = await workflowApi.checkAgents(wf.definition)
    missingAgents = checkRes.data?.missing || []
  } catch {
    // 检查失败，继续导入
  }

  const doImport = async () => {
    try {
      const res = await workflowApi.importWorkflow(wf.id)
      message.success(`工作流「${wf.name}」已导入`)
      router.push(`/workflows/${res.data.id}`)
    } catch (error) {
      message.error(error?.message || '导入失败')
    }
  }

  if (missingAgents.length > 0) {
    Modal.confirm({
      title: '导入工作流',
      content: `工作流「${wf.name}」引用了 ${missingAgents.length} 个当前系统中不存在的 Agent：\n${missingAgents.map(a => `  - ${a.name} (${a.slug})`).join('\n')}\n\n是否自动创建这些 Agent 并导入工作流？`,
      okText: '创建并导入',
      cancelText: '取消',
      async onOk() {
        // 先创建缺失的 Agent
        let createResult = null
        try {
          const res = await workflowApi.createMissingAgents(wf.definition, missingAgents.map(a => a.slug))
          createResult = res.data
          const createdCount = createResult?.created?.length || 0
          const failedCount = createResult?.failed?.length || 0
          if (failedCount > 0) {
            const failedNames = createResult.failed.map(f => `${f.name || f.slug}（${f.reason}）`).join('\n')
            Modal.warning({
              title: '部分 Agent 创建失败',
              content: `成功创建 ${createdCount} 个，失败 ${failedCount} 个：\n${failedNames}`,
            })
          } else {
            message.success(`已创建 ${createdCount} 个 Agent`)
          }
        } catch (error) {
          message.warning('Agent 创建请求失败，继续导入工作流')
        }
        await doImport()
      },
    })
  } else {
    doImport()
  }
}

defineExpose({
  loading,
  refresh: loadPlatformWorkflows,
})

onMounted(() => {
  loadPlatformWorkflows()
  loadWorkflowCategories()
})
</script>

<template>
  <div class="platform-workflow-panel">
    <PageShoulder v-model:search="searchQuery" search-placeholder="搜索平台工作流...">
      <template #actions>
        <a-button class="lucide-icon-btn" @click="loadPlatformWorkflows" :loading="loading">
          <RefreshCw :size="14" :class="{ spinning: loading }" />
        </a-button>
      </template>
    </PageShoulder>

    <!-- 分类标签 -->
    <div class="category-bar">
      <div class="category-scroll">
        <button
          v-for="opt in categoryTabOptions"
          :key="opt.value"
          type="button"
          class="category-tab"
          :class="{ active: selectedCategory === opt.value }"
          @click="selectedCategory = opt.value"
        >
          {{ opt.label }}
          <span v-if="categoryCounts[opt.value] !== undefined" class="category-count">
            {{ categoryCounts[opt.value] }}
          </span>
        </button>
      </div>
    </div>

    <!-- 工作流列表 -->
    <div v-if="!loading" class="workflow-list-area">
      <div v-if="filteredWorkflows.length === 0" class="empty-state">
        <a-empty :image="false" :description="searchQuery ? '没有匹配的平台工作流' : '暂无平台工作流'" />
      </div>
      <ExtensionCardGrid v-else :min-width="300">
        <InfoCard
          v-for="wf in filteredWorkflows"
          :key="wf.id"
          :title="wf.name"
          :description="wf.description || '暂无描述'"
          :default-icon="Layers"
          :tags="buildTags(wf)"
          class="workflow-card"
        >
          <template #icon>
            <span class="workflow-card-emoji">{{ getWorkflowIcon(wf) }}</span>
          </template>

          <template #footer>
            <span class="wf-footer-item">
              <Layers :size="12" />
              {{ wf.definition?.steps?.length || 0 }} 步骤
            </span>
            <span class="wf-footer-item wf-footer-time" style="margin-left: auto;">
              <a-button type="primary" size="small" @click.stop="handleImport(wf)">
                <template #icon><Download :size="12" /></template>
                导入
              </a-button>
            </span>
          </template>
        </InfoCard>
      </ExtensionCardGrid>
    </div>

    <div v-else class="loading-state">
      <a-spin size="large" />
    </div>
  </div>
</template>

<style lang="less" scoped>
@import '@/assets/css/extensions.less';

.platform-workflow-panel {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.category-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px var(--page-padding) 0;
  flex-shrink: 0;
}

.category-scroll {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.category-tab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--gray-600);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease;
  flex-shrink: 0;

  &:hover {
    color: var(--gray-900);
    background-color: var(--gray-50);
  }

  &.active {
    color: var(--gray-2000);
    background-color: color-mix(in srgb, var(--gray-800) 6%, var(--gray-0));
    font-weight: 600;
  }
}

.category-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--gray-100);
  color: var(--gray-500);
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.workflow-list-area {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px var(--page-padding);
}

.workflow-card {
  min-height: 160px;
}

.workflow-card :deep(.info-card-desc) {
  min-height: 2.8em;
}

.workflow-card :deep(.info-card-tags) {
  min-height: 28px;
}

.workflow-card :deep(.info-card-footer) {
  margin-top: auto;
}

.workflow-card-emoji {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  font-size: 18px;
  line-height: 1;
  overflow: hidden;
}

.wf-footer-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--gray-500);
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--gray-400);
  font-size: 14px;
}

.loading-state {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
  flex: 1;
}
</style>
