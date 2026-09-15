<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { Workflow, Plus, Layers, User, Trash2, RefreshCw } from '@lucide/vue'
import { workflowApi } from '@/apis/workflow_api'
import { authApi } from '@/apis/auth_api'
import { useUserStore } from '@/stores/user'
import { useCategories } from '@/composables/useCategories'
import { formatRelative } from '@/utils/time'
import InfoCard from '@/components/shared/InfoCard.vue'
import ExtensionCardGrid from '@/components/extensions/ExtensionCardGrid.vue'
import PageShoulder from '@/components/shared/PageShoulder.vue'

const userStore = useUserStore()
const { categories: workflowCategories, loadCategories: loadWorkflowCategories } = useCategories('workflow')

const router = useRouter()
const SCOPE_LABELS = { company: '公司', department: '部门', personal: '个人' }

// 状态
const loading = ref(false)
const creating = ref(false)
const workflows = ref([])
const searchQuery = ref('')
const selectedCategory = ref('all')
const showCreateModal = ref(false)
const newWorkflow = ref({
  name: '',
  description: '',
  category_id: null,
  scope: 'personal',
})

// uid → 用户名映射
const userMap = ref({})

// 判断是否为 emoji 图标
const EMOJI_REGEX = /^[\p{Emoji}\u200d\ufe0f\u20e3\u3299\u3297\u231a\u23f0\u23f3\u2600-\u27bf\u2b50\u2b55\u23e9-\u23fa\u25aa-\u25ab\u25b6\u25c0\u25fb-\u25fe\u2614\u2615\u2648-\u2653\u267f\u2693\u26a1\u26aa-\u26ab\u26bd-\u26be\u26c4-\u26c5\u26ce\u26d4\u26ea\u26f2-\u26f3\u26f5\u26fa\u26fd\u2702-\u270d\u270f\u2712\u2714\u2716\u271d\u2721\u2728\u2733-\u2734\u2744\u2747\u274c\u274e\u2753-\u2755\u2757\u2763-\u2764\u2795-\u2797\u27a1\u27b0\u27bf\u2934-\u2935\u2b05-\u2b07\u2b1b-\u2b1c\u2b50\u2b55\u3030\u303d\u3297\u3299\ufe0f]+$/u

const getWorkflowIcon = (wf) => {
  const icon = wf.icon
  if (!icon) return '🔄'
  if (icon.length > 4) return '🔄'
  if (EMOJI_REGEX.test(icon)) return icon
  return ''
}

// 解析创建者名称
const resolveCreatorName = (uid) => {
  if (!uid) return '未知'
  if (uid === userStore.uid) return '我'
  return userMap.value[uid] || uid.slice(0, 8)
}

// 构建工作流标签
const buildWorkflowTags = (wf) => {
  const tags = []
  if (wf.category_id) {
    const cat = workflowCategories.value.find(c => c.id === wf.category_id)
    if (cat) tags.push({ name: cat.label, color: 'gray' })
  } else if (wf.category) {
    const oldCats = { office: '办公效率', dev: '开发工具', data: '数据处理', content: '内容创作', info: '信息管理', business: '业务流程', enterprise: '企业服务', productivity: '生产力', other: '其他' }
    tags.push({ name: oldCats[wf.category] || wf.category, color: 'gray' })
  }
  if (wf.scope === 'platform') {
    tags.push({ name: '平台', color: 'gold' })
  }
  const scopeLabel = SCOPE_LABELS[wf.scope] || wf.scope
  if (scopeLabel && scopeLabel !== '个人') {
    tags.push({ name: scopeLabel, color: 'blue' })
  }
  return tags
}

const formatRelativeTime = (value) => {
  if (!value) return ''
  return formatRelative(value)
}

// 分类标签选项
const categoryTabs = computed(() => [
  { key: 'all', label: '全部' },
  ...workflowCategories.value.map(cat => ({ key: String(cat.id), label: cat.label }))
])

// 前端过滤（搜索 + 分类）
const filteredWorkflows = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  let list = workflows.value

  // 搜索过滤
  if (keyword) {
    list = list.filter(wf =>
      String(wf.name || '').toLowerCase().includes(keyword) ||
      String(wf.description || '').toLowerCase().includes(keyword)
    )
  }

  // 分类过滤
  if (selectedCategory.value !== 'all') {
    list = list.filter(wf => String(wf.category_id) === selectedCategory.value)
  }

  return list
})

// 分类计数
const categoryCounts = computed(() => {
  const counts = { all: workflows.value.length }
  for (const cat of workflowCategories.value) {
    counts[String(cat.id)] = workflows.value.filter(wf => String(wf.category_id) === String(cat.id)).length
  }
  return counts
})

// 加载用户列表
const loadUserMap = async () => {
  try {
    const users = await authApi.getUsers({ limit: 500 })
    const map = {}
    for (const u of (users || [])) {
      if (u.uid && u.username) map[u.uid] = u.username
    }
    userMap.value = map
  } catch {
    // 非管理员可能无法获取用户列表，静默处理
  }
}

// 加载工作流列表
const loadWorkflows = async () => {
  loading.value = true
  try {
    const params = {}
    // 非管理员只看公司级 + 个人级（自己的）
    if (!userStore.isAdmin) {
      params.scope = 'company'
    }
    const res = await workflowApi.list(params)
    let list = (res.data || []).filter(w => w.scope !== 'platform')
    // 非管理员：额外合并个人级工作流
    if (!userStore.isAdmin) {
      const personalRes = await workflowApi.list({ ...params, scope: 'personal' })
      const personalList = (personalRes.data || []).filter(w => w.created_by === userStore.uid && w.scope !== 'platform')
      list = [...list, ...personalList]
    }
    workflows.value = list
  } catch (error) {
    console.error('加载工作流失败:', error)
    message.error('加载工作流失败')
  } finally {
    loading.value = false
  }
}

// 创建工作流
const handleCreate = async () => {
  if (!newWorkflow.value.name.trim()) {
    message.warning('请输入工作流名称')
    return
  }

  creating.value = true
  try {
    const res = await workflowApi.create({
      name: newWorkflow.value.name,
      description: newWorkflow.value.description,
      category_id: newWorkflow.value.category_id,
      scope: newWorkflow.value.scope,
    })
    message.success('工作流创建成功')
    showCreateModal.value = false
    newWorkflow.value = { name: '', description: '', category_id: null, scope: 'personal' }
    await loadWorkflows()
    router.push(`/workflows/${res.data.id}`)
  } catch (error) {
    console.error('创建工作流失败:', error)
    message.error(error?.message || '创建工作流失败')
  } finally {
    creating.value = false
  }
}

// 删除工作流
const confirmDelete = (wf) => {
  if (wf.scope === 'platform') {
    message.warning('平台工作流不能删除')
    return
  }
  Modal.confirm({
    title: `删除「${wf.name}」`,
    content: '删除后不可恢复，相关运行记录也将一并清除。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await workflowApi.delete(wf.id)
        message.success('工作流已删除')
        await loadWorkflows()
      } catch (error) {
        message.error(error?.message || '删除工作流失败')
      }
    }
  })
}

// 打开工作流
const openWorkflow = (workflow) => {
  router.push(`/workflows/${workflow.id}`)
}

onMounted(() => {
  loadWorkflows()
  loadUserMap()
  loadWorkflowCategories()
})

defineExpose({
  loading,
  refresh: loadWorkflows,
})
</script>

<template>
  <div class="workflow-manage-panel">
    <PageShoulder v-model:search="searchQuery" search-placeholder="搜索工作流...">
      <template #actions>
        <a-button type="primary" class="lucide-icon-btn" @click="showCreateModal = true">
          <Plus :size="14" />
          新建工作流
        </a-button>
        <a-button class="lucide-icon-btn" @click="loadWorkflows" :loading="loading">
          <RefreshCw :size="14" :class="{ spinning: loading }" />
        </a-button>
      </template>
    </PageShoulder>

    <!-- 分类标签 -->
    <div class="category-bar">
      <div class="category-scroll">
        <button
          v-for="cat in categoryTabs"
          :key="cat.key"
          type="button"
          class="category-tab"
          :class="{ active: selectedCategory === cat.key }"
          @click="selectedCategory = cat.key"
        >
          {{ cat.label }}
          <span v-if="categoryCounts[cat.key] !== undefined" class="category-count">
            {{ categoryCounts[cat.key] }}
          </span>
        </button>
      </div>
    </div>

    <!-- 工作流列表 -->
    <div v-if="!loading" class="workflow-list-area">
      <div v-if="filteredWorkflows.length === 0" class="workflow-empty-state">
        <a-empty :image="false" :description="searchQuery ? '没有匹配的工作流' : '暂无工作流'" />
      </div>
      <ExtensionCardGrid v-else :min-width="300">
        <InfoCard
          v-for="wf in filteredWorkflows"
          :key="wf.id"
          :title="wf.name"
          :description="wf.description || '暂无描述'"
          :default-icon="Workflow"
          :tags="buildWorkflowTags(wf)"
          class="workflow-card"
          @click="openWorkflow(wf)"
        >
          <template #icon>
            <span class="workflow-card-emoji">{{ getWorkflowIcon(wf) }}</span>
          </template>

          <template #footer>
            <span class="wf-footer-item">
              <Layers :size="12" />
              {{ wf.step_count || 0 }} 步骤
            </span>
            <span class="wf-footer-item">
              <User :size="12" />
              {{ resolveCreatorName(wf.created_by) }}
            </span>
            <span class="wf-footer-item wf-footer-time">
              {{ formatRelativeTime(wf.created_at) }}
            </span>
          </template>

          <template v-if="userStore.isAdmin" #card-more-action-corner>
            <a-menu>
              <a-menu-item key="delete" :danger="true" @click.stop="confirmDelete(wf)">
                <span class="lucide-menu-item">
                  <Trash2 :size="14" />
                  <span>删除工作流</span>
                </span>
              </a-menu-item>
            </a-menu>
          </template>
        </InfoCard>
      </ExtensionCardGrid>
    </div>

    <!-- 加载状态 -->
    <div v-else class="loading-state">
      <a-spin size="large" />
    </div>

    <!-- 创建工作流弹窗 -->
    <a-modal
      v-model:open="showCreateModal"
      title="新建工作流"
      @ok="handleCreate"
      :confirmLoading="creating"
      width="520px"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="newWorkflow.name" placeholder="输入工作流名称" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="newWorkflow.description" placeholder="工作流描述（可选）" :rows="3" />
        </a-form-item>
        <a-form-item label="分类">
          <a-select v-model:value="newWorkflow.category_id" placeholder="选择分类（可选）" allowClear>
            <a-select-option v-for="cat in workflowCategories" :key="cat.id" :value="cat.id">
              {{ cat.label }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="可见范围">
          <a-radio-group v-model:value="newWorkflow.scope">
            <a-radio value="personal">个人</a-radio>
            <a-radio value="department">部门</a-radio>
            <a-radio value="company">公司</a-radio>
          </a-radio-group>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style lang="less" scoped>
@import '@/assets/css/extensions.less';

.workflow-manage-panel {
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
  transition:
    background-color 0.2s ease,
    color 0.2s ease;
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

.workflow-list-area {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.workflow-empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 100px 20px;
  text-align: center;
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

.workflow-card {
  min-height: 180px;
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

.wf-footer-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--gray-500);
}

.wf-footer-time {
  margin-left: auto;
}

.loading-state {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
  flex: 1;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
