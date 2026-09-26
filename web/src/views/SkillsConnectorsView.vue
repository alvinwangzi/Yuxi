<template>
  <div class="skills-connectors-view extension-page-root">
    <PageHeader
      v-if="!isDetailPage"
      v-model:active-key="activeTab"
      title="技能 · 连接器"
      :tabs="extensionTabs"
      :loading="activeChildLoading"
      :show-border="true"
      aria-label="技能与连接器视图切换"
    />

    <div v-if="!isDetailPage" class="skills-content">
      <div v-if="activeTab === 'skills'" class="tab-panel">
        <!-- 技能面板内二级 Tab：技能列表 / 技能市场 / 技能审批(管理员) -->
        <div class="skills-sub-tabs">
          <a-tabs v-model:activeKey="skillSubTab" size="small">
            <a-tab-pane key="list" tab="技能列表" />
            <a-tab-pane key="market" tab="技能市场" />
            <a-tab-pane v-if="userStore.isAdmin" key="approval" tab="技能审批" />
          </a-tabs>
        </div>
        <div v-if="skillSubTab === 'list'" class="sub-tab-panel">
          <SkillCardList ref="skillsRef" />
        </div>
        <div v-if="skillSubTab === 'market'" class="sub-tab-panel">
          <SkillMarketPanel />
        </div>
        <div v-if="skillSubTab === 'approval' && userStore.isAdmin" class="sub-tab-panel">
          <MarketApprovalPanel />
        </div>
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'tools'" class="tab-panel">
        <ToolsCardList ref="toolsRef" />
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'mcp'" class="tab-panel">
        <McpCardList ref="mcpRef" />
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'channels'" class="tab-panel">
        <ChannelCardList ref="channelsRef" />
      </div>
    </div>

    <router-view v-else :key="route.path" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ToolsCardList from '@/components/extensions/ToolsCardList.vue'
import McpCardList from '@/components/extensions/McpCardList.vue'
import SkillCardList from '@/components/extensions/SkillCardList.vue'
import ChannelCardList from '@/components/extensions/ChannelCardList.vue'
import SkillMarketPanel from '@/components/marketplace/SkillMarketPanel.vue'
import MarketApprovalPanel from '@/components/marketplace/MarketApprovalPanel.vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const activeTab = ref(null)
const skillSubTab = ref('list')
const skillsRef = ref(null)
const toolsRef = ref(null)
const mcpRef = ref(null)
const channelsRef = ref(null)

const adminExtensionTabs = computed(() => [
  { key: 'skills', label: '技能' },
  { key: 'tools', label: '工具' },
  { key: 'mcp', label: 'MCP' },
  { key: 'channels', label: '渠道' }
])
const userExtensionTabs = [{ key: 'skills', label: '技能' }]
const extensionTabs = computed(() =>
  userStore.isAdmin ? adminExtensionTabs.value : userExtensionTabs
)
const allowedTabKeys = computed(() => extensionTabs.value.map((tab) => tab.key))
const defaultTabKey = computed(() => extensionTabs.value[0]?.key || 'skills')

const normalizeTab = (tab) => {
  if (allowedTabKeys.value.includes(tab)) return tab
  return defaultTabKey.value
}

const replaceTabQuery = (tab) => {
  const query = { ...route.query }
  if (tab === defaultTabKey.value) {
    delete query.tab
  } else {
    query.tab = tab
  }
  router.replace({ query })
}

const isDetailPage = computed(() => {
  return (
    route.path.startsWith('/skills/skill/') ||
    route.path.startsWith('/skills/mcp/')
  )
})

const activeChildLoading = computed(() => {
  const refMap = {
    skills: skillsRef,
    tools: toolsRef,
    mcp: mcpRef,
    channels: channelsRef
  }
  const child = refMap[activeTab.value]
  return child?.value?.loading || false
})
watch(
  () => [route.query.tab, userStore.isAdmin],
  ([tab]) => {
    const nextTab = normalizeTab(tab)
    if (activeTab.value !== nextTab) activeTab.value = nextTab
    if (tab && tab !== nextTab) replaceTabQuery(nextTab)
    // 非管理员时重置技能子 Tab，避免停留在审批页
    if (!userStore.isAdmin && skillSubTab.value === 'approval') {
      skillSubTab.value = 'list'
    }
  },
  { immediate: true }
)

watch(activeTab, (tab) => {
  if (!tab) return
  const nextTab = normalizeTab(tab)
  if (nextTab !== tab) {
    activeTab.value = nextTab
    return
  }
  if (route.query.tab === nextTab || (!route.query.tab && nextTab === defaultTabKey.value)) return
  replaceTabQuery(nextTab)
})
</script>

<style scoped lang="less">
@import '@/assets/css/extensions.less';

.skills-connectors-view {
  .skills-content {
    flex: 1;
    min-height: 0;
    overflow: hidden;

    .tab-panel {
      height: 100%;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }

    .skills-sub-tabs {
      padding: 0 16px;
      border-bottom: 1px solid #f0f0f0;

      :deep(.ant-tabs-nav) {
        margin-bottom: 0;
      }
    }

    .sub-tab-panel {
      flex: 1;
      min-height: 0;
      overflow-y: auto;
    }
  }
}
</style>
