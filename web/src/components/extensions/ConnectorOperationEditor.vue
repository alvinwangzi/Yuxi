<template>
  <a-modal
    :open="open"
    :title="`操作管理 — ${connector?.name}`"
    :width="800"
    :footer="null"
    :destroy-on-close="true"
    @cancel="handleClose"
  >
    <div class="connector-operation-editor">
      <div class="operation-toolbar">
        <a-button v-if="connector?.connector_type === 'generic_rest'" type="primary" size="small" @click="openNewOperation">
          <template #icon><Plus :size="14" /></template>
          添加操作
        </a-button>
        <a-button size="small" @click="fetchOperations">
          <template #icon><RefreshCw :size="14" /></template>
          刷新
        </a-button>
      </div>

      <a-spin :spinning="loading">
        <div v-if="operations.length === 0 && !loading" class="empty-operations">
          <a-empty description="暂无操作，点击上方按钮添加" />
        </div>

        <div v-else class="operation-list">
          <div v-for="op in operations" :key="op.slug" class="operation-item">
            <div class="operation-item-header">
              <div class="operation-item-info">
                <a-tag :color="op.operation_type === 'write' ? 'orange' : 'blue'" :bordered="false">
                  {{ op.operation_type === 'write' ? '写入' : '读取' }}
                </a-tag>
                <span class="operation-name">{{ op.name }}</span>
                <span class="operation-slug">{{ op.slug }}</span>
              </div>
              <div class="operation-item-actions">
                <a-button size="small" @click="editOperation(op)">编辑</a-button>
                <a-button size="small" danger @click="confirmDelete(op)">删除</a-button>
              </div>
            </div>
            <div v-if="op.description" class="operation-desc">{{ op.description }}</div>
            <div class="operation-meta">
              <span>HTTP: {{ op.http_method }} {{ op.endpoint_template || '-' }}</span>
              <span v-if="op.operation_type === 'write' && op.approval_policy === 'required'" class="approval-badge">需审批</span>
            </div>
          </div>
        </div>
      </a-spin>

      <!-- 操作编辑表单 -->
      <a-modal
        v-model:open="editModalVisible"
        :title="editingNew ? '添加操作' : '编辑操作'"
        :width="640"
        :confirm-loading="editSaving"
        @ok="saveOperation"
      >
        <a-form layout="vertical" class="operation-form">
          <a-form-item label="名称" required>
            <a-input v-model:value="editForm.name" placeholder="操作显示名称" />
          </a-form-item>
          <a-form-item label="标识 (slug)" required>
            <a-input
              v-model:value="editForm.slug"
              placeholder="英文标识，如 query_customer"
              :disabled="!editingNew"
            />
          </a-form-item>
          <a-form-item label="分类" required>
            <a-radio-group v-model:value="editForm.operation_type" :disabled="!editingNew">
              <a-radio value="read">读取</a-radio>
              <a-radio value="write">写入</a-radio>
            </a-radio-group>
          </a-form-item>
          <a-form-item label="描述">
            <a-textarea v-model:value="editForm.description" :rows="2" />
          </a-form-item>

          <a-divider>HTTP 配置</a-divider>

          <a-form-item label="HTTP 方法">
            <a-select v-model:value="editForm.http_method" :disabled="providerOwns('http_method')">
              <a-select-option value="GET">GET</a-select-option>
              <a-select-option value="POST">POST</a-select-option>
              <a-select-option value="PUT">PUT</a-select-option>
              <a-select-option value="PATCH">PATCH</a-select-option>
              <a-select-option value="DELETE">DELETE</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="路径模板">
            <a-input v-model:value="editForm.endpoint_template" :disabled="providerOwns('endpoint_template')" placeholder="/v1/records/&#123;&#123;record_id&#125;&#125;" />
          </a-form-item>

          <a-form-item label="请求参数 Schema (JSON)">
            <a-textarea
              v-model:value="editForm.request_schema_json"
              :rows="4"
              placeholder='{"type": "object", "properties": {...}}'
            />
          </a-form-item>

          <a-form-item label="响应映射 (JSON)">
            <a-textarea
              v-model:value="editForm.response_mapping_json"
              :rows="3"
              placeholder='{"result": "data"}'
            />
          </a-form-item>

          <a-form-item label="查询模板 (JSON)"><a-textarea v-model:value="editForm.query_template_json" :disabled="providerOwns('query_template')" :rows="3" /></a-form-item>
          <a-form-item label="请求正文模板 (JSON)"><a-textarea v-model:value="editForm.body_template_json" :disabled="providerOwns('body_template')" :rows="3" /></a-form-item>
          <a-form-item label="读取重试策略 (JSON)"><a-textarea v-model:value="editForm.retry_policy_json" :rows="2" placeholder='REST 读取最多三次，例如 {"max_attempts":3}；写入不自动重试' /></a-form-item>
          <a-form-item label="远端幂等策略 (JSON)"><a-textarea v-model:value="editForm.remote_idempotency_json" :rows="2" placeholder='REST 写入，例如 {"header_name":"Idempotency-Key"}；需目标接口支持' /></a-form-item>
          <a-form-item label="响应类型"><a-select v-model:value="editForm.response_type" :disabled="providerOwns('response_type')"><a-select-option value="json">JSON</a-select-option><a-select-option value="text">文本</a-select-option><a-select-option value="empty">无正文</a-select-option></a-select></a-form-item>
          <a-form-item label="写入审批策略"><a-select v-model:value="editForm.approval_policy"><a-select-option value="required">每次人工审批</a-select-option><a-select-option value="preauthorized">预授权（仍检查写权限）</a-select-option></a-select></a-form-item>
        </a-form>
      </a-modal>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { Plus, RefreshCw } from '@lucide/vue'
import { operationPayload } from '@/utils/connector_forms'
import {
  getConnectorOperations,
  createConnectorOperation,
  updateConnectorOperation,
  deleteConnectorOperation,
} from '@/apis/connector_api'

const props = defineProps({
  open: Boolean,
  connector: Object,
})

const emit = defineEmits(['update:open', 'saved'])

const loading = ref(false)
let requestGeneration = 0
const operations = ref([])
const editModalVisible = ref(false)
const editingNew = ref(true)
const editingOperation = ref(null)
const editSaving = ref(false)

const editForm = reactive({
  name: '',
  slug: '',
  operation_type: 'read',
  description: '',
  http_method: 'GET',
  endpoint_template: '',
  request_schema_json: '',
  response_mapping_json: '',
  approval_policy: 'required', response_type: 'json', query_template_json: '', body_template_json: '', retry_policy_json: '', remote_idempotency_json: '',
})

watch(
  [() => props.open, () => props.connector?.slug],
  ([val]) => {
    requestGeneration++
    loading.value = false
    operations.value = []
    editModalVisible.value = false
    if (val && props.connector?.slug) {
      fetchOperations()
    }
  },
)

async function fetchOperations() {
  if (!props.connector?.slug) return
  loading.value = true
  const generation = ++requestGeneration
  try {
    const result = await getConnectorOperations(props.connector.slug)
    if (generation !== requestGeneration) return
    if (result.success) {
      operations.value = result.data || []
    }
  } catch (err) {
    if (generation !== requestGeneration) return
    message.error(err.message || '获取操作列表失败')
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}

function providerOwns(field) { return editingOperation.value?.provider_owned_fields?.includes(field) || false }

function openNewOperation() {
  editingNew.value = true
  editingOperation.value = null
  Object.assign(editForm, {
    name: '', slug: '', operation_type: 'read', description: '',
    http_method: 'GET', endpoint_template: '', request_schema_json: '',
    response_mapping_json: '', approval_policy: 'required', response_type: 'json', query_template_json: '', body_template_json: '', retry_policy_json: '', remote_idempotency_json: '',
  })
  editModalVisible.value = true
}

function editOperation(op) {
  editingNew.value = false
  editingOperation.value = op
  Object.assign(editForm, {
    name: op.name || '',
    slug: op.slug || '',
    operation_type: op.operation_type || 'read',
    description: op.description || '',
    http_method: op.http_method || 'GET',
    endpoint_template: op.endpoint_template || '',
    request_schema_json: op.request_schema ? JSON.stringify(op.request_schema, null, 2) : '',
    response_mapping_json: op.response_mapping ? JSON.stringify(op.response_mapping, null, 2) : '',
    approval_policy: op.approval_policy || 'required', response_type: op.response_type || 'json',
    query_template_json: op.query_template ? JSON.stringify(op.query_template, null, 2) : '',
    body_template_json: op.body_template ? JSON.stringify(op.body_template, null, 2) : '',
    retry_policy_json: op.retry_policy ? JSON.stringify(op.retry_policy, null, 2) : '',
    remote_idempotency_json: op.remote_idempotency ? JSON.stringify(op.remote_idempotency, null, 2) : '',
  })
  editModalVisible.value = true
}

async function saveOperation() {
  if (!editForm.name || !editForm.slug) {
    message.warning('请填写名称和标识')
    return
  }

  let payload
  try { payload = operationPayload(editForm, editingOperation.value) } catch (error) { message.error(error.message); return }
  if (!editingNew.value) { delete payload.slug; delete payload.operation_type }
  editSaving.value = true
  try {
    let result
    if (editingNew.value) {
      result = await createConnectorOperation(props.connector.slug, payload)
    } else {
      result = await updateConnectorOperation(props.connector.slug, editForm.slug, payload)
    }

    if (result.success) {
      message.success(editingNew.value ? '操作已创建' : '操作已更新')
      editModalVisible.value = false
      await fetchOperations()
      emit('saved')
    } else {
      message.error(result.message || '保存失败')
    }
  } catch (err) {
    message.error(err.message || '保存失败')
  } finally {
    editSaving.value = false
  }
}

function confirmDelete(op) {
  Modal.confirm({
    title: '确认删除操作',
    content: `确定要删除操作 "${op.name}" 吗？`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        const result = await deleteConnectorOperation(props.connector.slug, op.slug)
        if (result.success) {
          message.success('操作已删除')
          await fetchOperations()
        } else {
          message.error(result.message || '删除失败')
        }
      } catch (err) {
        message.error(err.message || '删除失败')
      }
    },
  })
}

function handleClose() {
  emit('update:open', false)
}
</script>

<style lang="less" scoped>
.connector-operation-editor {
  max-height: 65vh;
  overflow-y: auto;
}

.operation-form {
  max-height: 58vh;
  overflow-y: auto;
  padding-right: 8px;
}

.operation-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.empty-operations {
  padding: 32px 0;
}

.operation-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.operation-item {
  padding: 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
}

.operation-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.operation-item-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.operation-name {
  font-weight: 600;
  color: var(--gray-900);
}

.operation-slug {
  color: var(--gray-500);
  font-size: 12px;
  font-family: monospace;
}

.operation-item-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.operation-desc {
  margin-top: 4px;
  color: var(--gray-600);
  font-size: 13px;
}

.operation-meta {
  display: flex;
  gap: 12px;
  margin-top: 6px;
  color: var(--gray-500);
  font-size: 12px;
}

.approval-badge {
  color: var(--color-warning-700);
  font-weight: 600;
}

.operation-form {
  max-height: 55vh;
  overflow-y: auto;
  padding-right: 4px;
}
</style>
