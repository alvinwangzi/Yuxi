<template>
  <div class="extensions-view extension-page-root">
    <PageHeader
      v-if="!isDetailPage"
      v-model:active-key="activeTab"
      title="知识库"
      :tabs="extensionTabs"
      :loading="activeChildLoading"
      :show-border="true"
      aria-label="知识库视图切换"
    />

    <div v-if="!isDetailPage" class="extensions-content">
      <div v-if="userStore.isAdmin && activeTab === 'knowledge'" class="tab-panel">
        <DataBaseView ref="knowledgeRef" embedded />
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
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const activeTab = ref('knowledge')
const knowledgeRef = ref(null)

const extensionTabs = computed(() => {
  if (userStore.isAdmin) return [{ key: 'knowledge', label: '知识库' }]
  return []
})

const isDetailPage = computed(() => {
  return (
    route.path.startsWith('/extensions/knowledgebase/')
  )
})

const activeChildLoading = computed(() => {
  if (activeTab.value === 'knowledge') return knowledgeRef.value?.loading || false
  return false
})

watch(
  () => [route.query.tab, userStore.isAdmin],
  () => {
    if (activeTab.value !== 'knowledge') activeTab.value = 'knowledge'
  },
  { immediate: true }
)
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
