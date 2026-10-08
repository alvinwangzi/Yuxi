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
        <a-select v-model:value="filterStatus" placeholder="状态筛选" allow-clear style="width: 140px" @change="changeFilter">
          <a-select-option value="succeeded">成功</a-select-option>
          <a-select-option value="failed">失败</a-select-option>
          <a-select-option value="awaiting_approval">待审批</a-select-option>
          <a-select-option value="unknown">未知</a-select-option>
        </a-select>
        <a-range-picker v-model:value="filterDates" show-time :placeholder="['开始时间', '结束时间']" @change="changeFilter" />
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
              <span>{{ record.consumer_type === 'agent' ? 'Agent' : record.consumer_type === 'workflow' ? '工作流' : '管理测试' }}</span>
            </template>
            <template v-if="column.key === 'created_at'">
              <span>{{ formatTime(record.created_at) }}</span>
            </template>
            <template v-if="column.key === 'actions'">
              <a-button size="small" type="link" @click="openDetail(record)">详情</a-button>
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
  <a-modal v-model:open="detailOpen" title="调用与尝试详情" :footer="null" :width="720" @cancel="closeDetail">
    <a-alert v-if="detailError" type="error" :message="detailError" />
    <a-spin :spinning="detailLoading">
      <div v-if="detailData">
        <div>调用：{{ detailData.invocation_id }} · {{ detailData.status }} / {{ detailData.remote_outcome }}</div>
        <div>Agent Run：{{ detailData.agent_run_id || '-' }} · 工作流 Run：{{ detailData.workflow_run_id || '-' }}</div>
        <div>版本：连接器 {{ detailData.connector_revision }} / 操作 {{ detailData.operation_revision }}</div>
        <pre>{{ JSON.stringify({ request: detailData.request_summary, result: detailData.response_summary, error: detailData.error_code }, null, 2) }}</pre>
        <a-table :data-source="detailData.attempts || []" :columns="attemptColumns" :pagination="false" row-key="id" size="small" />
      </div>
    </a-spin>
  </a-modal>
</template>

<script setup>
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { RefreshCw } from '@lucide/vue'
import { getConnectorUsage, getManagementInvocation } from '@/apis/connector_api'

const props = defineProps({
  open: Boolean,
  connector: Object,
})

const emit = defineEmits(['update:open', 'reconcile'])

const loading = ref(false)
const invocations = ref([])
const filterStatus = ref(null)
const filterDates = ref(null)
const pagination = ref({ current: 1, pageSize: 20, total: 0 })
let requestGeneration = 0
let detailGeneration = 0
const detailOpen = ref(false)
const detailData = ref(null)
const detailError = ref('')
const detailLoading = ref(false)
const attemptColumns = [{ title: '尝试', dataIndex: 'attempt_no' }, { title: '发送状态', dataIndex: 'send_state' }, { title: 'HTTP', dataIndex: 'response_status' }, { title: '关联请求', dataIndex: 'provider_request_id' }, { title: '开始', dataIndex: 'started_at' }, { title: '结束', dataIndex: 'completed_at' }]

const columns = [
  { title: '状态', key: 'status', width: 100 },
  { title: '消费方', key: 'consumer', width: 80 },
  { title: '操作', dataIndex: 'operation_slug', key: 'operation', width: 140 },
  { title: '调用者', dataIndex: 'actor_uid', key: 'actor', width: 120, ellipsis: true },
  { title: '时间', key: 'created_at', width: 160 },
  { title: '', key: 'actions', width: 120 },
]

const STATUS_LABELS = {
  succeeded: '成功',
  failed: '失败',
  prepared: '已准备',
  rejected: '已拒绝',
  awaiting_approval: '待审批',
  running: '执行中',
  unknown: '未知',
  cancelled: '已取消',
}

const STATUS_COLORS = {
  succeeded: 'green',
  failed: 'red',
  awaiting_approval: 'orange',
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
  [() => props.open, () => props.connector?.slug],
  ([val]) => {
    requestGeneration++
    loading.value = false
    closeDetail()
    invocations.value = []
    if (val && props.connector?.slug) {
      pagination.value.current = 1
      fetchUsage()
    }
  },
)

async function fetchUsage() {
  if (!props.connector?.slug) return
  loading.value = true
  const generation = ++requestGeneration
  try {
    const params = {
      page: pagination.value.current,
      page_size: pagination.value.pageSize,
    }
    if (filterStatus.value) params.status = filterStatus.value
    if (filterDates.value?.length === 2) {
      params.created_from = filterDates.value[0].toISOString()
      params.created_to = filterDates.value[1].toISOString()
    }
    const result = await getConnectorUsage(props.connector.slug, params)
    if (generation !== requestGeneration) return
    if (result.success) {
      invocations.value = result.data?.items || result.data || []
      pagination.value.total = result.total || 0
    }
  } catch (err) {
    if (generation !== requestGeneration) return
    message.error(err.message || '获取调用记录失败')
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}

function handleTableChange(pag) {
  pagination.value.current = pag.current
  fetchUsage()
}

function handleClose() {
  requestGeneration++
  closeDetail()
  emit('update:open', false)
}

function changeFilter() {
  pagination.value.current = 1
  fetchUsage()
}
async function openDetail(record) {
  const generation = ++detailGeneration
  detailOpen.value = true
  detailData.value = null
  detailError.value = ''
  detailLoading.value = true
  try {
    const response = await getManagementInvocation(record.invocation_id)
    if (generation === detailGeneration) detailData.value = response.data
  } catch (error) { if (generation === detailGeneration) detailError.value = error.message || '详情读取失败' }
  finally { if (generation === detailGeneration) detailLoading.value = false }
}
function closeDetail() { detailGeneration++; detailOpen.value = false; detailLoading.value = false }
</script>

<style lang="less" scoped>
.connector-usage-panel {
  max-height: 65vh;
  overflow-y: auto;
}

.usage-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
</style>
