<script setup>
import { computed, ref } from 'vue'

import PageHeader from '@/components/shared/PageHeader.vue'
import RoleTemplatePanel from '@/components/roles/RoleTemplatePanel.vue'

const panelRef = ref(null)
const activeLoading = computed(() => panelRef.value?.loading || false)
</script>

<template>
  <div class="roles-view">
    <PageHeader
      title="角色模板"
      :loading="activeLoading"
      :show-border="true"
    />

    <div class="roles-content">
      <div class="tab-panel">
        <RoleTemplatePanel ref="panelRef" />
      </div>
    </div>
  </div>
</template>

<style lang="less" scoped>
.roles-view {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--gray-0);
  color: var(--gray-1000);
}

.roles-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;

  .tab-panel {
    height: 100%;
    min-height: 0;
    overflow-y: auto;
  }
}
</style>
