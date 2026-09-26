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
          <template v-if="column.key === 'scan_score'">
            <template v-if="record.scan_score !== null && record.scan_score !== undefined">
              <a-tag :color="getScoreColor(record.scan_score)">
                {{ record.scan_score }}分
              </a-tag>
            </template>
            <span v-else class="text-gray">未扫描</span>
          </template>
          <template v-if="column.key === 'submitted_at'">
            {{ formatDate(record.submitted_at) }}
          </template>
          <template v-if="column.key === 'action'">
            <a-space v-if="record.status === 'pending'">
              <a-button type="link" size="small" @click="showDetail(record)">详情</a-button>
              <a-button type="primary" size="small" @click="showApproveModal(record)">通过</a-button>
              <a-button danger size="small" @click="showRejectModal(record)">驳回</a-button>
            </a-space>
            <span v-else class="text-gray">{{ record.review_note || '-' }}</span>
          </template>
        </template>
      </a-table>
    </a-spin>

    <!-- 审批详情抽屉 -->
    <a-drawer
      v-model:open="detailDrawerVisible"
      title="审批详情"
      width="640"
      :footer-style="{ textAlign: 'right' }"
    >
      <template v-if="currentSubmission">
        <!-- 基本信息 -->
        <div class="detail-section">
          <h4>基本信息</h4>
          <a-descriptions :column="1" size="small">
            <a-descriptions-item label="提交者">{{ currentSubmission.submitter_uid }}</a-descriptions-item>
            <a-descriptions-item label="提交说明">{{ currentSubmission.submission_note || '-' }}</a-descriptions-item>
            <a-descriptions-item label="提交时间">{{ formatDateTime(currentSubmission.submitted_at) }}</a-descriptions-item>
          </a-descriptions>
        </div>

        <!-- 安全扫描结果 -->
        <div class="detail-section" v-if="currentSubmission.scan_score !== null && currentSubmission.scan_score !== undefined">
          <h4>安全扫描结果</h4>
          <div class="scan-result-card">
            <div class="scan-score-header">
              <span class="scan-score-label">风险评分</span>
              <a-tag :color="getScoreColor(currentSubmission.scan_score)" class="scan-score-value">
                {{ currentSubmission.scan_score }}/100
              </a-tag>
            </div>
            <div class="scan-severity">
              风险等级：{{ getSeverityLabel(currentSubmission.scan_score) }}
            </div>
            <div class="scan-recommendation">
              {{ getRecommendation(currentSubmission.scan_score) }}
            </div>

            <!-- 发现项列表 -->
            <div v-if="currentSubmission.scan_findings && currentSubmission.scan_findings.length > 0" class="findings-list">
              <h5>发现项 ({{ currentSubmission.scan_findings.length }})</h5>
              <a-list
                :data-source="currentSubmission.scan_findings"
                size="small"
                :bordered="false"
              >
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-list-item-meta>
                      <template #title>
                        <a-space>
                          <a-tag :color="getFindingSeverityColor(item.severity)" size="small">
                            {{ item.severity }}
                          </a-tag>
                          <span>{{ item.rule_id }} - {{ item.message }}</span>
                        </a-space>
                      </template>
                      <template #description>
                        <div v-if="item.file" class="finding-detail">
                          文件：{{ item.file }}{{ item.line ? `:${item.line}` : '' }}
                        </div>
                        <div v-if="item.snippet" class="finding-snippet">
                          <code>{{ item.snippet }}</code>
                        </div>
                      </template>
                    </a-list-item-meta>
                  </a-list-item>
                </template>
              </a-list>
            </div>
            <div v-else class="no-findings">
              <a-alert message="未发现安全风险" type="success" show-icon />
            </div>
          </div>
        </div>

        <!-- 审批操作区 -->
        <div class="detail-section" v-if="currentSubmission.status === 'pending'">
          <h4>审批操作</h4>
          <a-space>
            <a-button type="primary" @click="showApproveModal(currentSubmission)">通过</a-button>
            <a-button danger @click="showRejectModal(currentSubmission)">驳回</a-button>
          </a-space>
        </div>
      </template>
    </a-drawer>

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
const detailDrawerVisible = ref(false)
const reviewNote = ref('')
const currentSubmission = ref(null)

const columns = [
  { title: '提交者', dataIndex: 'submitter_uid', key: 'submitter_uid', width: 120 },
  { title: '提交说明', dataIndex: 'submission_note', key: 'submission_note', ellipsis: true },
  { title: '安全评分', key: 'scan_score', width: 100 },
  { title: '状态', key: 'status', width: 100 },
  { title: '提交时间', key: 'submitted_at', width: 120 },
  { title: '操作', key: 'action', width: 200 },
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

const showDetail = (record) => {
  currentSubmission.value = record
  detailDrawerVisible.value = true
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
      detailDrawerVisible.value = false
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
      detailDrawerVisible.value = false
      await loadSubmissions()
    }
  } catch (err) {
    message.error(err.response?.data?.detail || '操作失败')
  }
}

const getScoreColor = (score) => {
  if (score >= 76) return 'red'
  if (score >= 51) return 'orange'
  if (score >= 26) return 'yellow'
  return 'green'
}

const getSeverityLabel = (score) => {
  if (score >= 76) return '高风险'
  if (score >= 51) return '中风险'
  if (score >= 26) return '低风险'
  return '安全'
}

const getRecommendation = (score) => {
  if (score >= 76) return '禁止审批通过，存在严重安全风险'
  if (score >= 51) return '建议人工审查后决定是否通过'
  if (score >= 26) return '存在轻微风险，可审批通过'
  return '未发现安全风险，可安全安装'
}

const getFindingSeverityColor = (severity) => {
  const colors = {
    critical: 'red',
    high: 'orange',
    medium: 'yellow',
    low: 'blue',
    info: 'default',
  }
  return colors[severity] || 'default'
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

const formatDateTime = (dateStr) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleString('zh-CN')
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

.detail-section {
  margin-bottom: 24px;
}

.detail-section h4 {
  margin: 0 0 12px 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
  border-bottom: 1px solid var(--gray-150);
  padding-bottom: 8px;
}

.detail-section h5 {
  margin: 12px 0 8px 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-800);
}

.scan-result-card {
  background: var(--gray-50);
  border-radius: 8px;
  padding: 16px;
}

.scan-score-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.scan-score-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-800);
}

.scan-score-value {
  font-size: 16px;
  font-weight: 700;
}

.scan-severity {
  font-size: 13px;
  color: var(--gray-700);
  margin-bottom: 4px;
}

.scan-recommendation {
  font-size: 13px;
  color: var(--gray-600);
  margin-bottom: 16px;
}

.findings-list {
  margin-top: 16px;
}

.finding-detail {
  font-size: 12px;
  color: var(--gray-600);
  margin-top: 4px;
}

.finding-snippet {
  margin-top: 4px;
}

.finding-snippet code {
  background: var(--gray-100);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: monospace;
  color: var(--gray-800);
}

.no-findings {
  margin-top: 16px;
}
</style>
