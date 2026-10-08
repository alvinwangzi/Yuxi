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
        <a-button type="primary" @click="openCreateModal" class="lucide-icon-btn" :disabled="typesLoading || !!typesError || !connectorTypes.length || (vaultStatus && vaultStatus.status !== 'ok')">
          <Plus :size="14" />
          <span>添加连接器</span>
        </a-button>
      </template>
    </PageShoulder>
    <a-alert v-if="typesError" type="error" show-icon message="连接器类型加载失败，请重试">
      <template #action><a-button size="small" :loading="typesLoading" @click="fetchTypes">重试加载类型</a-button></template>
    </a-alert>
    <a-alert v-if="vaultStatus && vaultStatus.status !== 'ok'" type="warning" show-icon
      message="连接器保险库不可用，请配置有效 key ring 后创建或启用连接器" />

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
          :description="[conn.enabled ? '已启用' : '已停用', getTypeLabel(conn.connector_type), conn.description].filter(Boolean).join(' · ')"
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
          <template #card-more-action-corner>
            <a-menu>
              <a-menu-item @click="openOperationEditor(conn)">操作管理</a-menu-item>
              <a-menu-item @click="openUsagePanel(conn)">调用记录</a-menu-item>
              <a-menu-item @click="openApprovalPanel(conn)">待审批调用</a-menu-item>
            </a-menu>
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
    <a-pagination v-if="totalConnectors > pageSize" v-model:current="currentPage" :page-size="pageSize" :total="totalConnectors" :show-size-changer="false" @change="fetchConnectors" />

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
      @reconcile="openReconcile"
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
import { ref, computed, onMounted, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { Check, Plus, RefreshCw, Settings, Trash2 } from '@lucide/vue'
import {
  getConnectors,
  getConnector,
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
const typesLoading = ref(false)
const typesError = ref(false)
let typeRequestGeneration = 0
let listRequestGeneration = 0
let detailRequestGeneration = 0
const vaultStatus = ref(null)
const searchQuery = ref('')
const selectedType = ref('all')
const currentPage = ref(1)
const pageSize = 20
const totalConnectors = ref(0)
watch([searchQuery, selectedType], () => { currentPage.value = 1; fetchConnectors() })
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

const filteredConnectors = computed(() => connectors.value)

function getTypeLabel(type) {
  return TYPE_LABELS[type] || type
}

function getTypeIcon(type) {
  return TYPE_ICONS[type] || '🔗'
}

function openCreateModal() {
  detailRequestGeneration += 1
  currentConnector.value = null
  configModalVisible.value = true
}

async function openDetail(conn) {
  const generation = ++detailRequestGeneration
  try {
    const result = await getConnector(conn.slug)
    if (generation !== detailRequestGeneration) return
    currentConnector.value = result.data
    configModalVisible.value = true
  } catch (error) {
    if (generation === detailRequestGeneration) message.error(error.message || '读取配置失败')
  }
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
  const generation = ++listRequestGeneration
  try {
    loading.value = true
    const result = await getConnectors({ page: currentPage.value, page_size: pageSize, search: searchQuery.value, connector_type: selectedType.value === 'all' ? undefined : selectedType.value })
    if (generation !== listRequestGeneration) return
    if (result.success) {
      connectors.value = result.data || []
      totalConnectors.value = result.total || 0
    }
  } catch (err) {
    if (generation !== listRequestGeneration) return
    message.error(err.message || '获取连接器列表失败')
  } finally {
    if (generation === listRequestGeneration) loading.value = false
  }
}

async function fetchTypes() {
  const generation = ++typeRequestGeneration
  typesLoading.value = true
  typesError.value = false
  try {
    const result = await getConnectorTypes()
    if (generation !== typeRequestGeneration) return
    const types = Array.isArray(result.data) ? result.data.filter(type => type.type && (type.capabilities?.read || type.capabilities?.write)) : []
    if (!result.success || !types.length) throw new Error('connector_types_unavailable')
    connectorTypes.value = types
    vaultStatus.value = result.vault || null
  } catch {
    if (generation !== typeRequestGeneration) return
    connectorTypes.value = []
    typesError.value = true
  } finally {
    if (generation === typeRequestGeneration) typesLoading.value = false
  }
}

function handleSaved() {
  configModalVisible.value = false
  fetchConnectors()
}

function handleOperationSaved() {
  fetchConnectors()
}

function openReconcile(invocation) {
  currentInvocation.value = invocation
  usagePanelVisible.value = false
  reconcileModalVisible.value = true
}
function handleReconcileResolved() {
  reconcileModalVisible.value = false
  usagePanelVisible.value = true
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
