<template>
  <div class="workflow-view">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-left">
        <h1 class="page-title">
          <Workflow class="title-icon" :size="24" />
          工作流
        </h1>
        <a-tag v-if="workflows.length" color="blue">{{ workflows.length }} 个工作流</a-tag>
      </div>
      <div class="header-actions">
        <a-button type="primary" @click="showCreateModal = true">
          <template #icon><Plus /></template>
          新建工作流
        </a-button>
      </div>
    </div>

    <!-- 分类标签 -->
    <div class="category-tabs">
      <a-segmented
        v-model:value="selectedCategory"
        :options="categoryOptions"
        @change="loadWorkflows"
      />
    </div>

    <!-- 工作流列表 -->
    <div class="workflow-grid" v-if="!loading">
      <div
        v-for="workflow in workflows"
        :key="workflow.id"
        class="workflow-card"
        @click="openWorkflow(workflow)"
      >
        <div class="card-header">
          <span class="workflow-icon">{{ workflow.icon || '🔄' }}</span>
          <div class="card-title-area">
            <div class="workflow-name">{{ workflow.name }}</div>
            <div class="workflow-category" v-if="workflow.category">
              {{ getCategoryName(workflow.category) }}
            </div>
          </div>
        </div>
        <div class="workflow-desc">{{ workflow.description || '暂无描述' }}</div>
        <div class="card-footer">
          <a-tag size="small">{{ workflow.step_count || 0 }} 步骤</a-tag>
          <a-tag v-if="workflow.is_builtin" color="gold" size="small">内置</a-tag>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="workflows.length === 0" class="empty-state">
        <Empty description="暂无工作流">
          <a-button type="primary" @click="showCreateModal = true">创建第一个工作流</a-button>
        </Empty>
      </div>
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
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="newWorkflow.name" placeholder="输入工作流名称" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="newWorkflow.description" placeholder="工作流描述（可选）" :rows="3" />
        </a-form-item>
        <a-form-item label="分类">
          <a-select v-model:value="newWorkflow.category" placeholder="选择分类（可选）" allowClear>
            <a-select-option v-for="cat in WORKFLOW_CATEGORIES" :key="cat.id" :value="cat.id">
              {{ cat.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { Workflow, Plus } from '@lucide/vue'
import { workflowApi } from '@/apis/workflow_api'

// 工作流分类（与后端 Workflow.category 字段对应）
const WORKFLOW_CATEGORIES = [
  { id: 'office', name: '办公效率' },
  { id: 'dev', name: '开发工具' },
  { id: 'data', name: '数据处理' },
  { id: 'content', name: '内容创作' },
  { id: 'info', name: '信息管理' },
  { id: 'business', name: '业务流程' },
  { id: 'enterprise', name: '企业服务' },
  { id: 'productivity', name: '生产力' },
  { id: 'other', name: '其他' },
]

const router = useRouter()

// 状态
const loading = ref(false)
const creating = ref(false)
const workflows = ref([])
const selectedCategory = ref('all')
const showCreateModal = ref(false)
const newWorkflow = ref({
  name: '',
  description: '',
  category: null
})

// 分类选项
const categoryOptions = computed(() => {
  const options = [{ label: '全部', value: 'all' }]
  WORKFLOW_CATEGORIES.forEach(cat => {
    options.push({ label: cat.name, value: cat.id })
  })
  return options
})

// 分类名称映射
const categoryNameMap = computed(() => {
  const map = {}
  WORKFLOW_CATEGORIES.forEach(cat => {
    map[cat.id] = cat.name
  })
  return map
})

const getCategoryName = (id) => categoryNameMap.value[id] || id

// 加载工作流列表
const loadWorkflows = async () => {
  loading.value = true
  try {
    const params = {}
    if (selectedCategory.value !== 'all') {
      params.category = selectedCategory.value
    }
    const res = await workflowApi.list(params)
    workflows.value = res.data || []
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
      category: newWorkflow.value.category,
    })
    message.success('工作流创建成功')
    showCreateModal.value = false
    newWorkflow.value = { name: '', description: '', category: null }
    await loadWorkflows()
    // 跳转到编辑页
    router.push(`/workflows/${res.data.id}`)
  } catch (error) {
    console.error('创建工作流失败:', error)
    message.error(error?.message || '创建工作流失败')
  } finally {
    creating.value = false
  }
}

// 打开工作流
const openWorkflow = (workflow) => {
  router.push(`/workflows/${workflow.id}`)
}

onMounted(() => {
  loadWorkflows()
})
</script>

<style scoped>
.workflow-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 24px;
  overflow: auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-icon {
  color: var(--primary-color);
}

.header-actions {
  display: flex;
  align-items: center;
}

.header-actions :deep(.ant-btn) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.header-actions :deep(.ant-btn > span) {
  line-height: 1;
  vertical-align: middle;
}

.category-tabs {
  margin-bottom: 24px;
}

.workflow-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.workflow-card {
  background: var(--gray-0);
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 8px var(--shadow-1);
}

.workflow-card:hover {
  border-color: var(--main-400);
  box-shadow: 0 4px 16px var(--shadow-3);
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.workflow-icon {
  font-size: 28px;
}

.card-title-area {
  flex: 1;
  min-width: 0;
}

.workflow-name {
  font-weight: 600;
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-category {
  font-size: 12px;
  color: var(--text-color-tertiary);
  margin-top: 2px;
}

.workflow-desc {
  font-size: 13px;
  color: var(--text-color-secondary);
  line-height: 1.5;
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  gap: 8px;
}

.empty-state,
.loading-state {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
  grid-column: 1 / -1;
}
</style>

<style>
/* 全局样式：修复工作流页面按钮文字垂直居中 */
.workflow-view .header-actions .ant-btn {
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  line-height: 1 !important;
}

.workflow-view .header-actions .ant-btn > span {
  line-height: 1 !important;
  vertical-align: middle !important;
}
</style>
