<template>
  <a-modal
    :open="open"
    :title="`调用记录 — ${connector?.name}`"
    :width="720"
    :footer="null"
    :destroy-on-close="true"
    @cancel="handleClose"
  >
    <div class="connector-usage-panel">
      <div class="usage-toolbar">
        <a-select v-model:value="filterStatus" placeholder="状态筛选" allow-clear style="width: 140px" @change="fetchUsage">
          <a-select-option value="success">成功</a-select-option>
          <a-select-option value="failed">失败</a-select-option>
          <a-select-option value="pending_approval">待审批</a-select-option>
          <a-select-option value="unknown">未知</a-select-option>
        </a-select>
        <a-button size="small" @click="fetchUsage">
          <template #icon><RefreshCw :size="14" /></template>
          刷新
        </a-button>
      </div>

      <a-spin :spinning="loading">
        <a-table
          :data-source="invocations"
          :columns="columns"
          :pagination="pagination"
          :loading="loading"
          size="small"
          row-key="invocation_id"
          @change="handleTableChange"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag :color="statusColor(record.status)" :bordered="false">
                {{ statusLabel(record.status) }}
              </a-tag>
            </template>
            <template v-if="column.key === 'consumer'">
              <span>{{ record.consumer_type === 'agent' ? 'Agent' : '工作流' }}</span>
            </template>
            <template v-if="column.key === 'created_at'">
              <span>{{ formatTime(record.created_at) }}</span>
            </template>
            <template v-if="column.key === 'actions'">
              <a-button
                v-if="record.status === 'unknown'"
                size="small"
                type="link"
                @click="$emit('reconcile', record)"
              >
                核对
              </a-button>
            </template>
          </template>
        </a-table>
      </a-spin>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { RefreshCw } from '@lucide/vue'
import { getConnectorUsage } from '@/apis/connector_api'

const props = defineProps({
  open: Boolean,
  connector: Object,
})

const emit = defineEmits(['update:open', 'reconcile'])

const loading = ref(false)
const invocations = ref([])
const filterStatus = ref(null)
const pagination = ref({ current: 1, pageSize: 20, total: 0 })

const columns = [
  { title: '状态', key: 'status', width: 100 },
  { title: '消费方', key: 'consumer', width: 80 },
  { title: '操作', dataIndex: 'operation_slug', key: 'operation', width: 140 },
  { title: '调用者', dataIndex: 'actor_uid', key: 'actor', width: 120, ellipsis: true },
  { title: '时间', key: 'created_at', width: 160 },
  { title: '', key: 'actions', width: 60 },
]

const STATUS_LABELS = {
  success: '成功',
  failed: '失败',
  pending_approval: '待审批',
  running: '执行中',
  unknown: '未知',
  cancelled: '已取消',
}

const STATUS_COLORS = {
  success: 'green',
  failed: 'red',
  pending_approval: 'orange',
  running: 'blue',
  unknown: 'default',
  cancelled: 'gray',
}

function statusLabel(s) { return STATUS_LABELS[s] || s }
function statusColor(s) { return STATUS_COLORS[s] || 'default' }

function formatTime(t) {
  if (!t) return '-'
  try {
    return new Date(t).toLocaleString('zh-CN')
  } catch {
    return t
  }
}

watch(
  () => props.open,
  (val) => {
    if (val && props.connector?.slug) {
      pagination.value.current = 1
      fetchUsage()
    }
  },
)

async function fetchUsage() {
  if (!props.connector?.slug) return
  loading.value = true
  try {
    const params = {
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
    }
    if (filterStatus.value) params.status = filterStatus.value
    const result = await getConnectorUsage(props.connector.slug, params)
    if (result.success) {
      invocations.value = result.data?.items || result.data || []
      pagination.value.total = result.data?.total || invocations.value.length
    }
  } catch (err) {
    message.error(err.message || '获取调用记录失败')
  } finally {
    loading.value = false
  }
}

function handleTableChange(pag) {
  pagination.value.current = pag.current
  fetchUsage()
}

function handleClose() {
  emit('update:open', false)
}
</script>

<style lang="less" scoped>
.connector-usage-panel {
  max-height: 65vh;
  overflow-y: auto;
}

.usage-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
</style>
