<template>
  <div class="connector-cards-page extension-page-root">
    <PageShoulder search-placeholder="搜索连接器..." v-model:search="searchQuery">
      <template #actions>
        <a-tooltip title="刷新连接器" placement="bottom">
          <a-button
            class="lucide-icon-btn"
            aria-label="刷新连接器"
            :disabled="loading"
            @click="fetchConnectors"
          >
            <RefreshCw
              :size="14"
              class="page-shoulder-refresh-icon"
              :class="{ 'is-spinning': loading }"
            />
          </a-button>
        </a-tooltip>
        <a-button type="primary" @click="openCreateModal" class="lucide-icon-btn">
          <Plus :size="14" />
          <span>添加连接器</span>
        </a-button>
      </template>
    </PageShoulder>

    <div class="category-tab-bar">
      <button
        v-for="key in typeTabs"
        :key="key.value"
        type="button"
        class="tab-item"
        :class="{ active: selectedType === key.value }"
        @click="selectedType = key.value"
      >
        {{ key.label }}
        <span v-if="typeCounts[key.value]" class="tab-count">{{ typeCounts[key.value] }}</span>
      </button>
    </div>

    <a-spin :spinning="loading">
      <div v-if="filteredConnectors.length === 0 && !loading" class="extension-card-grid-empty-state">
        <a-empty :image="false" :description="searchQuery ? '无匹配连接器' : '暂无连接器，点击上方按钮添加'" />
      </div>

      <ExtensionCardGrid v-else :min-width="300">
        <InfoCard
          v-for="conn in filteredConnectors"
          :key="conn.slug"
          variant="mini"
          :title="conn.name"
          :description="conn.description || '暂无描述'"
          :tags="conn.tags || []"
          @click="openDetail(conn)"
        >
          <template #icon>
            <span class="info-card-emoji-icon">{{ getTypeIcon(conn.connector_type) }}</span>
          </template>
          <template #subtitle>
            <div class="connector-card-meta">
              <a-tag :color="conn.enabled ? 'green' : 'default'" :bordered="false" class="conn-status-tag">
                {{ conn.enabled ? '已启用' : '已停用' }}
              </a-tag>
              <span class="conn-type-label">{{ getTypeLabel(conn.connector_type) }}</span>
            </div>
          </template>
          <template #action>
            <button
              type="button"
              class="mcp-card-action"
              :disabled="actionLoadingSlug === conn.slug"
              aria-label="编辑连接器"
              @click.stop="openDetail(conn)"
            >
              <Settings :size="15" class="action-icon" />
            </button>
            <button
              type="button"
              class="mcp-card-action mcp-card-action-danger"
              :disabled="actionLoadingSlug === conn.slug"
              aria-label="删除连接器"
              @click.stop="confirmDelete(conn)"
            >
              <Check :size="15" class="action-icon action-icon-check" />
              <Trash2 :size="15" class="action-icon action-icon-trash" />
            </button>
          </template>
        </InfoCard>
      </ExtensionCardGrid>
    </a-spin>

    <ConnectorConfigModal
      v-model:open="configModalVisible"
      :connector="currentConnector"
      :connector-types="connectorTypes"
      @saved="handleSaved"
    />

    <ConnectorOperationEditor
      v-model:open="operationEditorVisible"
      :connector="currentConnector"
      @saved="handleOperationSaved"
    />

    <ConnectorUsagePanel
      v-model:open="usagePanelVisible"
      :connector="currentConnector"
    />

    <ConnectorApprovalPanel
      v-model:open="approvalPanelVisible"
      :connector="currentConnector"
    />

    <ConnectorReconcileModal
      v-model:open="reconcileModalVisible"
      :invocation="currentInvocation"
      @resolved="handleReconcileResolved"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { Check, Plus, RefreshCw, Settings, Trash2 } from '@lucide/vue'
import {
  getConnectors,
  getConnectorTypes,
  deleteConnector,
} from '@/apis/connector_api'
import ExtensionCardGrid from './ExtensionCardGrid.vue'
import InfoCard from '@/components/shared/InfoCard.vue'
import PageShoulder from '@/components/shared/PageShoulder.vue'
import ConnectorConfigModal from './ConnectorConfigModal.vue'
import ConnectorOperationEditor from './ConnectorOperationEditor.vue'
import ConnectorUsagePanel from './ConnectorUsagePanel.vue'
import ConnectorApprovalPanel from './ConnectorApprovalPanel.vue'
import ConnectorReconcileModal from './ConnectorReconcileModal.vue'

const TYPE_LABELS = {
  generic_rest: '通用 REST',
  salesforce: 'Salesforce',
  feishu_bitable_crm: '飞书多维表格',
}

const TYPE_ICONS = {
  generic_rest: '🔗',
  salesforce: '☁️',
  feishu_bitable_crm: '📊',
}

const loading = ref(false)
const connectors = ref([])
const connectorTypes = ref([])
const searchQuery = ref('')
const selectedType = ref('all')
const actionLoadingSlug = ref('')

const configModalVisible = ref(false)
const operationEditorVisible = ref(false)
const usagePanelVisible = ref(false)
const approvalPanelVisible = ref(false)
const reconcileModalVisible = ref(false)
const currentConnector = ref(null)
const currentInvocation = ref(null)

const typeTabs = computed(() => {
  const tabs = [{ value: 'all', label: '全部' }]
  for (const t of connectorTypes.value) {
    tabs.push({ value: t.type, label: TYPE_LABELS[t.type] || t.type })
  }
  return tabs
})

const typeCounts = computed(() => {
  const counts = { all: connectors.value.length }
  for (const conn of connectors.value) {
    const t = conn.connector_type
    counts[t] = (counts[t] || 0) + 1
  }
  return counts
})

const filteredConnectors = computed(() => {
  let result = [...connectors.value]
  if (selectedType.value !== 'all') {
    result = result.filter((c) => c.connector_type === selectedType.value)
  }
  if (!searchQuery.value) return result
  const q = searchQuery.value.toLowerCase()
  return result.filter(
    (c) =>
      c.name.toLowerCase().includes(q) ||
      (c.description || '').toLowerCase().includes(q) ||
      c.slug.toLowerCase().includes(q),
  )
})

function getTypeLabel(type) {
  return TYPE_LABELS[type] || type
}

function getTypeIcon(type) {
  return TYPE_ICONS[type] || '🔗'
}

function openCreateModal() {
  currentConnector.value = null
  configModalVisible.value = true
}

function openDetail(conn) {
  currentConnector.value = conn
  configModalVisible.value = true
}

function openOperationEditor(conn) {
  currentConnector.value = conn
  operationEditorVisible.value = true
}

function openUsagePanel(conn) {
  currentConnector.value = conn
  usagePanelVisible.value = true
}

function openApprovalPanel(conn) {
  currentConnector.value = conn
  approvalPanelVisible.value = true
}

function confirmDelete(conn) {
  Modal.confirm({
    title: '确认删除连接器',
    content: `确定要删除连接器 "${conn.name}" 吗？关联的调用历史将保留但不可再调用。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        actionLoadingSlug.value = conn.slug
        const result = await deleteConnector(conn.slug)
        if (result.success) {
          message.success('连接器已删除')
          await fetchConnectors()
        } else {
          message.error(result.message || '删除失败')
        }
      } catch (err) {
        message.error(err.message || '删除失败')
      } finally {
        actionLoadingSlug.value = ''
      }
    },
  })
}

async function fetchConnectors() {
  try {
    loading.value = true
    const result = await getConnectors()
    if (result.success) {
      connectors.value = result.data || []
    }
  } catch (err) {
    message.error(err.message || '获取连接器列表失败')
  } finally {
    loading.value = false
  }
}

async function fetchTypes() {
  try {
    const result = await getConnectorTypes()
    if (result.success) {
      connectorTypes.value = result.data || []
    }
  } catch {
    // 类型加载失败不阻断页面
  }
}

function handleSaved() {
  configModalVisible.value = false
  fetchConnectors()
}

function handleOperationSaved() {
  operationEditorVisible.value = false
}

function handleReconcileResolved() {
  reconcileModalVisible.value = false
}

onMounted(() => {
  fetchTypes()
  fetchConnectors()
})

defineExpose({
  fetchConnectors,
  loading,
  openUsagePanel,
  openApprovalPanel,
  openOperationEditor,
})
</script>

<style lang="less" scoped>
@import '@/assets/css/extensions.less';

.info-card-emoji-icon {
  font-size: 18px;
  line-height: 1;
}

.connector-card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}

.conn-status-tag {
  font-size: 11px;
  line-height: 18px;
  padding: 0 6px;
}

.conn-type-label {
  color: var(--gray-500);
  font-size: 12px;
}

.mcp-card-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--main-color);
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background-color 0.18s ease,
    color 0.18s ease;

  &:hover,
  &:focus {
    outline: none;
    border-color: var(--main-200);
    background: var(--main-50);
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  &.mcp-card-action-danger {
    color: var(--color-success-700);

    .action-icon-trash {
      display: none;
    }

    &:hover,
    &:focus {
      border-color: var(--color-error-100);
      background: var(--color-error-50);
      color: var(--color-error-700);

      .action-icon-check {
        display: none;
      }

      .action-icon-trash {
        display: block;
      }
    }
  }
}

.action-icon {
  flex-shrink: 0;
}
</style>
