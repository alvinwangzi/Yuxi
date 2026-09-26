<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/shared/PageHeader.vue'
import AgentManagePanel from '@/components/model-management/AgentManagePanel.vue'
import RoleTemplatePanel from '@/components/roles/RoleTemplatePanel.vue'

const route = useRoute()
const router = useRouter()

const agentPanelRef = ref(null)
const rolePanelRef = ref(null)
const activeLoading = computed(() => {
  if (isRoleTab.value) return rolePanelRef.value?.loading || false
  return agentPanelRef.value?.loading || agentPanelRef.value?.saving || false
})
const activeStats = computed(() => agentPanelRef.value?.stats || {})

const isRoleTab = computed(() => route.path === '/agent-manage/roles')

function switchTab(tab) {
  if (tab === 'roles') {
    router.replace('/agent-manage/roles')
  } else {
    router.replace('/agent-manage')
  }
}
</script>

<template>
  <div class="agent-manage-view">
    <PageHeader
      title="智能体管理"
      :loading="activeLoading"
      :show-border="true"
    >
      <template #info>
        <div class="summary-strip">
          <span>{{ activeStats.total || 0 }} 个智能体</span>
          <span>{{ activeStats.manageable || 0 }} 个可管理</span>
        </div>
      </template>
    </PageHeader>

    <div class="agent-manage-content">
      <div class="page-tabs">
        <button
          class="page-tab"
          :class="{ active: !isRoleTab }"
          @click="switchTab('agents')"
        >
          智能体
        </button>
        <button
          class="page-tab"
          :class="{ active: isRoleTab }"
          @click="switchTab('roles')"
        >
          平台角色库
        </button>
      </div>
      <div class="tab-panel">
        <AgentManagePanel v-if="!isRoleTab" ref="agentPanelRef" />
        <RoleTemplatePanel v-else ref="rolePanelRef" />
      </div>
    </div>
  </div>
</template>

<style lang="less" scoped>
.agent-manage-view {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--gray-0);
  color: var(--gray-1000);
}

.agent-manage-content {
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
