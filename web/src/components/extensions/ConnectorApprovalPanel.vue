<template>
  <a-modal
    :open="open"
    title="待审批调用"
    :width="640"
    :footer="null"
    :destroy-on-close="true"
    @cancel="handleClose"
  >
    <div class="connector-approval-panel">
      <a-spin :spinning="loading">
        <div v-if="pendingItems.length === 0 && !loading" class="empty-approval">
          <a-empty description="暂无待审批调用" />
        </div>

        <div v-else class="approval-list">
          <div v-for="item in pendingItems" :key="item.invocation_id" class="approval-item">
            <div class="approval-item-header">
              <span class="approval-operation">{{ item.operation_slug }}</span>
              <a-tag color="orange" :bordered="false">{{ item.status === 'unknown' ? '等待核对' : '待审批' }}</a-tag>
            </div>
            <div class="approval-item-meta">
              <span>调用者: {{ item.actor_uid || '-' }}</span>
              <span>时间: {{ formatTime(item.created_at) }}</span>
            </div>
            <div v-if="item.request_digest" class="approval-digest">
              <pre>{{ formatDigest(item.request_digest) }}</pre>
            </div>
            <div v-if="item.request_summary" class="approval-digest">
              <div>连接器：{{ item.connector_slug }} · {{ item.request_summary.method }} {{ item.request_summary.endpoint_template }}</div>
              <div>目标：{{ JSON.stringify(item.request_summary.targets || {}) }}</div>
              <div>公开变更：{{ JSON.stringify(item.request_summary.changes || {}) }}</div>
              <div>变更字段：{{ (item.request_summary.changed_fields || []).join('、') || '固定操作' }}</div>
              <div>版本：连接器 {{ item.connector_revision }} / 操作 {{ item.operation_revision }}</div>
              <div>有效期：{{ item.approval_expires_at ? formatTime(item.approval_expires_at) : '批准后开始计时' }}</div>
            </div>
            <a-alert v-if="item.status === 'unknown'" type="warning" message="远端结局未知，暂停后续步骤；需管理员根据独立回查证据核对，不能直接重发。" />
            <div v-if="item.status === 'unknown'" class="approval-item-actions">
              <a-button v-if="userStore.isAdmin" size="small" @click="openReconciliation(item)">核对</a-button>
              <span v-else>请联系管理员核对此调用</span>
            </div>
            <template v-else>
              <a-alert v-if="!item.request_summary?.approval_ready" type="warning" message="审批摘要不完整，暂不能批准；请联系管理员" />
              <div v-if="item.actor_uid !== userStore.uid">仅调用者本人可以决定此调用</div>
              <div class="approval-item-actions">
                <a-button type="primary" size="small" :loading="actionLoading === item.invocation_id" :disabled="item.actor_uid !== userStore.uid || !item.request_summary?.approval_ready" @click="approve(item)">
                  批准
                </a-button>
                <a-button danger size="small" :loading="actionLoading === item.invocation_id" :disabled="item.actor_uid !== userStore.uid" @click="reject(item)">
                  拒绝
                </a-button>
              </div>
            </template>
          </div>
        </div>
      </a-spin>
    </div>
  </a-modal>
  <ConnectorReconcileModal v-model:open="reconciliationOpen" :invocation="reconciliationItem" @resolved="handleResolved" />
</template>

<script setup>
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { getConnectorUsage, getInvocation, submitDecision } from '@/apis/connector_api'
import ConnectorReconcileModal from './ConnectorReconcileModal.vue'

import { useUserStore } from '@/stores/user'
const userStore = useUserStore()
const props = defineProps({
  open: Boolean,
  connector: Object,
  invocationIds: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:open', 'decided'])

const loading = ref(false)
let requestGeneration = 0
const pendingItems = ref([])
const actionLoading = ref('')
const reconciliationOpen = ref(false)
const reconciliationItem = ref(null)

function openReconciliation(item) {
  reconciliationItem.value = item
  reconciliationOpen.value = true
}

async function handleResolved() {
  reconciliationOpen.value = false
  await fetchPending()
  emit('decided', reconciliationItem.value)
}

function formatTime(t) {
  if (!t) return '-'
  try { return new Date(t).toLocaleString('zh-CN') } catch { return t }
}

function formatDigest(digest) {
  if (!digest) return ''
  if (typeof digest === 'string') {
    try { return JSON.stringify(JSON.parse(digest), null, 2) } catch { return digest }
  }
  return JSON.stringify(digest, null, 2)
}

watch(
  [() => props.open, () => props.connector?.slug, () => JSON.stringify(props.invocationIds)],
  ([val]) => {
    requestGeneration++
    loading.value = false
    pendingItems.value = []
    if (val && (props.connector?.slug || props.invocationIds.length)) {
      fetchPending()
    }
  },
)

async function fetchPending() {
  if (!props.connector?.slug && !props.invocationIds.length) return
  loading.value = true
  const generation = ++requestGeneration
  try {
    if (props.invocationIds.length) {
      const results = await Promise.all(props.invocationIds.map(getInvocation))
      if (generation !== requestGeneration) return
      pendingItems.value = results.map(result => result.data).filter(item => ['awaiting_approval', 'unknown'].includes(item.status))
      return
    }
    const result = await getConnectorUsage(props.connector.slug, { status: 'awaiting_approval' })
    if (generation !== requestGeneration) return
    if (result.success) {
      pendingItems.value = result.data?.items || result.data || []
    }
  } catch (err) {
    if (generation !== requestGeneration) return
    message.error(err.message || '获取审批列表失败')
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}

async function approve(item) {
  actionLoading.value = item.invocation_id
  try {
    const result = await submitDecision(item.invocation_id, { decision: 'approve', expected_digest: item.request_digest })
    if (result.success) {
      message.success('已批准')
      await fetchPending()
      emit('decided', item)
    } else {
      message.error(result.message || '操作失败')
    }
  } catch (err) {
    message.error(err.message || '操作失败')
  } finally {
    actionLoading.value = ''
  }
}

async function reject(item) {
  actionLoading.value = item.invocation_id
  try {
    const result = await submitDecision(item.invocation_id, { decision: 'reject', expected_digest: item.request_digest })
    if (result.success) {
      message.success('已拒绝')
      await fetchPending()
      emit('decided', item)
    } else {
      message.error(result.message || '操作失败')
    }
  } catch (err) {
    message.error(err.message || '操作失败')
  } finally {
    actionLoading.value = ''
  }
}

function handleClose() {
  requestGeneration++
  emit('update:open', false)
}
</script>

<style lang="less" scoped>
.connector-approval-panel {
  max-height: 65vh;
  overflow-y: auto;
}

.empty-approval {
  padding: 32px 0;
}

.approval-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.approval-item {
  padding: 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
}

.approval-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.approval-operation {
  font-weight: 600;
  color: var(--gray-900);
}

.approval-item-meta {
  display: flex;
  gap: 16px;
  margin-top: 4px;
  color: var(--gray-500);
  font-size: 12px;
}

.approval-digest {
  margin-top: 8px;
  padding: 8px;
  background: var(--gray-50);
  border-radius: 6px;
  max-height: 120px;
  overflow-y: auto;

  pre {
    margin: 0;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
  }
}

.approval-item-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  justify-content: flex-end;
}
</style>
