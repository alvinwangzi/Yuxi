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
              <a-tag color="orange" :bordered="false">待审批</a-tag>
            </div>
            <div class="approval-item-meta">
              <span>调用者: {{ item.actor_uid || '-' }}</span>
              <span>时间: {{ formatTime(item.created_at) }}</span>
            </div>
            <div v-if="item.request_digest" class="approval-digest">
              <pre>{{ formatDigest(item.request_digest) }}</pre>
            </div>
            <div class="approval-item-actions">
              <a-button type="primary" size="small" :loading="actionLoading === item.invocation_id" @click="approve(item)">
                批准
              </a-button>
              <a-button danger size="small" :loading="actionLoading === item.invocation_id" @click="reject(item)">
                拒绝
              </a-button>
            </div>
          </div>
        </div>
      </a-spin>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { getConnectorUsage, submitDecision } from '@/apis/connector_api'

const props = defineProps({
  open: Boolean,
  connector: Object,
})

const emit = defineEmits(['update:open'])

const loading = ref(false)
const pendingItems = ref([])
const actionLoading = ref('')

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
  () => props.open,
  (val) => {
    if (val && props.connector?.slug) {
      fetchPending()
    }
  },
)

async function fetchPending() {
  if (!props.connector?.slug) return
  loading.value = true
  try {
    const result = await getConnectorUsage(props.connector.slug, { status: 'pending_approval' })
    if (result.success) {
      pendingItems.value = result.data?.items || result.data || []
    }
  } catch (err) {
    message.error(err.message || '获取审批列表失败')
  } finally {
    loading.value = false
  }
}

async function approve(item) {
  actionLoading.value = item.invocation_id
  try {
    const result = await submitDecision(item.invocation_id, { decision: 'approve' })
    if (result.success) {
      message.success('已批准')
      await fetchPending()
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
    const result = await submitDecision(item.invocation_id, { decision: 'reject' })
    if (result.success) {
      message.success('已拒绝')
      await fetchPending()
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
