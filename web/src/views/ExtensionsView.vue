<template>
  <div class="extensions-view extension-page-root">
    <PageHeader
      v-if="!isDetailPage"
      v-model:active-key="activeTab"
      title="扩展管理"
      :tabs="extensionTabs"
      :loading="activeChildLoading"
      :show-border="true"
      aria-label="扩展视图切换"
    />

    <div v-if="!isDetailPage" class="extensions-content">
      <div v-if="userStore.isAdmin && activeTab === 'knowledge'" class="tab-panel">
        <DataBaseView ref="knowledgeRef" embedded />
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'mcp'" class="tab-panel">
        <McpCardList ref="mcpRef" />
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'tools'" class="tab-panel">
        <ToolsCardList ref="toolsRef" />
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'skills'" class="tab-panel">
        <SkillCardList ref="skillsRef" />
      </div>
      <div v-if="userStore.isAdmin && activeTab === 'connectors'" class="tab-panel">
        <ConnectorCardList ref="connectorsRef" />
      </div>
    </div>

    <router-view v-else :key="route.path" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import DataBaseView from '@/views/DataBaseView.vue'
import McpCardList from '@/components/extensions/McpCardList.vue'
import ToolsCardList from '@/components/extensions/ToolsCardList.vue'
import SkillCardList from '@/components/extensions/SkillCardList.vue'
import ConnectorCardList from '@/components/extensions/ConnectorCardList.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const activeTab = ref(route.query.tab || 'knowledge')
const knowledgeRef = ref(null)
const mcpRef = ref(null)
const toolsRef = ref(null)
const skillsRef = ref(null)
const connectorsRef = ref(null)

const extensionTabs = computed(() => {
  if (userStore.isAdmin) {
    return [
      { key: 'knowledge', label: '知识库' },
      { key: 'mcp', label: 'MCP' },
      { key: 'tools', label: '工具' },
      { key: 'skills', label: '技能' },
      { key: 'connectors', label: '连接器' }
    ]
  }
  return []
})

const isDetailPage = computed(() => {
  return (
    route.path.startsWith('/extensions/knowledgebase/')
  )
})

const activeChildLoading = computed(() => {
  switch (activeTab.value) {
    case 'knowledge': return knowledgeRef.value?.loading || false
    case 'mcp': return mcpRef.value?.loading || false
    case 'tools': return toolsRef.value?.loading || false
    case 'skills': return skillsRef.value?.loading || false
    case 'connectors': return connectorsRef.value?.loading || false
    default: return false
  }
})

// 同步 URL tab 参数到 activeTab
watch(
  () => [route.query.tab, userStore.isAdmin],
  ([tab]) => {
    const validTabs = ['knowledge', 'mcp', 'tools', 'skills', 'connectors']
    if (tab && validTabs.includes(tab)) {
      activeTab.value = tab
    } else if (!validTabs.includes(activeTab.value)) {
      activeTab.value = 'knowledge'
    }
  },
  { immediate: true }
)

// activeTab 变化时同步回 URL
watch(activeTab, (newTab) => {
  if (route.query.tab !== newTab) {
    router.replace({ query: { ...route.query, tab: newTab } })
  }
})
</script>

<style scoped lang="less">
@import '@/assets/css/extensions.less';

.extensions-view {
  .extensions-content {
    flex: 1;
    min-height: 0;
    overflow: hidden;

    .tab-panel {
      height: 100%;
      min-height: 0;
      overflow-y: auto;
    }
  }
}
</style>
