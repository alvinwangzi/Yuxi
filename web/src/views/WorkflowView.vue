<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import WorkflowManagePanel from '@/components/workflows/WorkflowManagePanel.vue'
import PlatformWorkflowPanel from '@/components/workflows/PlatformWorkflowPanel.vue'
import { workflowApi } from '@/apis/workflow_api'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const workflowPanelRef = ref(null)
const platformPanelRef = ref(null)

const activeLoading = computed(() => {
  if (isPlatformTab.value) return platformPanelRef.value?.loading || false
  return workflowPanelRef.value?.loading || false
})

const isPlatformTab = computed(() => route.path === '/workflows/platform')

function switchTab(tab) {
  if (tab === 'platform') {
    router.replace('/workflows/platform')
  } else {
    router.replace('/workflows')
  }
}

// 统计数据
const stats = ref({ total: 0, platform: 0, company: 0, personal: 0 })
const statsLoading = ref(false)

const loadStats = async () => {
  statsLoading.value = true
  try {
    const res = await workflowApi.getStats()
    stats.value = res.data || {}
  } catch {
    // 静默处理
  } finally {
    statsLoading.value = false
  }
}

// 初始化加载统计
loadStats()
</script>

<template>
  <div class="workflow-view">
    <PageHeader
      title="工作流管理"
      :loading="statsLoading"
      :show-border="true"
    >
      <template #info>
        <div class="summary-strip">
          <span>{{ stats.total || 0 }} 个工作流</span>
          <span v-if="stats.platform">{{ stats.platform }} 个平台</span>
          <span>{{ stats.company || 0 }} 个公司</span>
          <span>{{ stats.personal || 0 }} 个个人</span>
        </div>
      </template>
    </PageHeader>

    <div class="workflow-content">
      <div class="page-tabs">
        <button
          class="page-tab"
          :class="{ active: !isPlatformTab }"
          @click="switchTab('workflows')"
        >
          工作流
        </button>
        <button
          class="page-tab"
          :class="{ active: isPlatformTab }"
          @click="switchTab('platform')"
        >
          平台工作流库
        </button>
      </div>
      <div class="tab-panel">
        <WorkflowManagePanel v-if="!isPlatformTab" ref="workflowPanelRef" />
        <PlatformWorkflowPanel v-else ref="platformPanelRef" />
      </div>
    </div>
  </div>
</template>

<style lang="less" scoped>
.workflow-view {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--gray-0);
  color: var(--gray-1000);
}

.workflow-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;

  .tab-panel {
    height: 100%;
    min-height: 0;
    overflow-y: auto;
  }
}

.summary-strip {
  display: flex;
  gap: 8px;

  span {
    padding: 6px 10px;
    border: 1px solid var(--gray-100);
    border-radius: 7px;
    background: var(--gray-10);
    color: var(--gray-700);
    font-size: 12px;
    line-height: 18px;
  }
}

.page-tabs {
  display: flex;
  gap: 0;
  padding: 12px 16px 0;
  border-bottom: 1px solid var(--gray-150);
}

.page-tab {
  padding: 8px 16px;
  border: none;
  background: none;
  color: var(--gray-500);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color 0.2s, border-color 0.2s;

  &:hover {
    color: var(--gray-800);
  }

  &.active {
    color: var(--gray-1000);
    border-bottom-color: var(--main-color);
  }
}
</style>
