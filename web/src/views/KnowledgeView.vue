<template>
  <div class="knowledge-view extension-page-root">
    <PageHeader v-if="!isDetailPage" title="知识库" :loading="knowledgeRef?.loading || false" :show-border="true" />
    <div v-if="!isDetailPage" class="knowledge-content">
      <DataBaseView ref="knowledgeRef" embedded />
    </div>
    <router-view v-else :key="route.path" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import DataBaseView from '@/views/DataBaseView.vue'

const route = useRoute()
const knowledgeRef = ref(null)
const isDetailPage = computed(() => Boolean(route.params.kbId))
</script>

<style scoped lang="less">
@import '@/assets/css/extensions.less';
.knowledge-content { flex: 1; min-height: 0; overflow-y: auto; }
</style>
