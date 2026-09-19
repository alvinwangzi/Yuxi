<template>
  <div class="market-approval-panel">
    <div class="panel-header">
      <h3>技能审批</h3>
      <a-button @click="loadSubmissions" :loading="loading">
        <template #icon><ReloadOutlined /></template>
        刷新
      </a-button>
    </div>

    <a-spin :spinning="loading">
      <a-table
        :columns="columns"
        :data-source="submissions"
        :pagination="false"
        row-key="id"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'pending' ? 'orange' : record.status === 'approved' ? 'green' : 'red'">
              {{ record.status === 'pending' ? '待审批' : record.status === 'approved' ? '已通过' : '已驳回' }}
            </a-tag>
          </template>
          <template v-if="column.key === 'submitted_at'">
            {{ formatDate(record.submitted_at) }}
          </template>
          <template v-if="column.key === 'action'">
            <a-space v-if="record.status === 'pending'">
              <a-button type="primary" size="small" @click="showApproveModal(record)">通过</a-button>
              <a-button danger size="small" @click="showRejectModal(record)">驳回</a-button>
            </a-space>
            <span v-else class="text-gray">{{ record.review_note || '-' }}</span>
          </template>
        </template>
      </a-table>
    </a-spin>

    <!-- 审批通过弹窗 -->
    <a-modal v-model:open="approveModalVisible" title="审批通过" @ok="handleApprove" ok-text="确认通过">
      <a-form-item label="审批说明">
        <a-textarea v-model:value="reviewNote" :rows="3" placeholder="可选的审批说明" />
      </a-form-item>
    </a-modal>

    <!-- 驳回弹窗 -->
    <a-modal v-model:open="rejectModalVisible" title="驳回" @ok="handleReject" ok-text="确认驳回" ok-type="danger">
      <a-form-item label="驳回原因" required>
        <a-textarea v-model:value="reviewNote" :rows="3" placeholder="请填写驳回原因" />
      </a-form-item>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { marketplaceApi } from '@/apis/marketplace_api'

const loading = ref(false)
const submissions = ref([])
const approveModalVisible = ref(false)
const rejectModalVisible = ref(false)
const reviewNote = ref('')
const currentSubmission = ref(null)

const columns = [
  { title: '提交者', dataIndex: 'submitter_uid', key: 'submitter_uid', width: 120 },
  { title: '提交说明', dataIndex: 'submission_note', key: 'submission_note', ellipsis: true },
  { title: '状态', key: 'status', width: 100 },
  { title: '提交时间', key: 'submitted_at', width: 120 },
  { title: '操作', key: 'action', width: 160 },
]

const loadSubmissions = async () => {
  loading.value = true
  try {
    const res = await marketplaceApi.listPendingSubmissions()
    if (res.success) {
      submissions.value = res.data
    }
  } catch (err) {
    message.error('加载审批列表失败')
  } finally {
    loading.value = false
  }
}

const showApproveModal = (record) => {
  currentSubmission.value = record
  reviewNote.value = ''
  approveModalVisible.value = true
}

const showRejectModal = (record) => {
  currentSubmission.value = record
  reviewNote.value = ''
  rejectModalVisible.value = true
}

const handleApprove = async () => {
  try {
    const res = await marketplaceApi.approveSubmission(currentSubmission.value.id, {
      review_note: reviewNote.value,
    })
    if (res.success) {
      message.success('审批通过')
      approveModalVisible.value = false
      await loadSubmissions()
    }
  } catch (err) {
    message.error(err.response?.data?.detail || '操作失败')
  }
}

const handleReject = async () => {
  if (!reviewNote.value) {
    message.warning('请填写驳回原因')
    return
  }
  try {
    const res = await marketplaceApi.rejectSubmission(currentSubmission.value.id, {
      review_note: reviewNote.value,
    })
    if (res.success) {
      message.success('已驳回')
      rejectModalVisible.value = false
      await loadSubmissions()
    }
  } catch (err) {
    message.error(err.response?.data?.detail || '操作失败')
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

onMounted(() => {
  loadSubmissions()
})
</script>

<style scoped>
.market-approval-panel {
  padding: 0;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.panel-header h3 {
  margin: 0;
}

.text-gray {
  color: #999;
  font-size: 12px;
}
</style>
