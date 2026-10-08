<template>
  <a-modal
    :open="open"
    title="调用结果核对"
    :width="560"
    :destroy-on-close="true"
    :confirm-loading="submitting"
    @ok="handleSubmit"
    @cancel="handleClose"
  >
    <div v-if="invocation" class="reconcile-modal">
      <a-alert
        type="warning"
        show-icon
        message="该调用状态未知，需要根据远端证据人工判定"
        class="reconcile-alert"
      />

      <div class="reconcile-info">
        <div class="reconcile-row">
          <label>调用 ID</label>
          <span class="mono">{{ invocation.invocation_id }}</span>
        </div>
        <div class="reconcile-row">
          <label>操作</label>
          <span>{{ invocation.operation_slug }}</span>
        </div>
        <div class="reconcile-row">
          <label>调用者</label>
          <span>{{ invocation.actor_uid || '-' }}</span>
        </div>
        <div class="reconcile-row">
          <label>时间</label>
          <span>{{ formatTime(invocation.created_at) }}</span>
        </div>
      </div>

      <div v-if="invocation.evidence" class="reconcile-evidence">
        <div class="evidence-title">远端证据</div>
        <pre>{{ formatEvidence(invocation.evidence) }}</pre>
      </div>

      <a-form layout="vertical" class="reconcile-form">
        <a-form-item label="判定结果" required>
          <a-radio-group v-model:value="verdict">
            <a-radio value="succeeded">确认成功</a-radio>
            <a-radio value="failed">确认失败</a-radio>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="核对证据与原因" required>
          <a-textarea v-model:value="reason" :rows="2" placeholder="只读回查记录、关联 ID 和判定原因（必填）" />
        </a-form-item>
        <a-form-item v-if="verdict === 'succeeded'" label="独立回查取得的映射结果 (JSON)" required>
          <a-textarea v-model:value="resultJson" :rows="4" placeholder="填写同一记录的回查结果，供原步骤恢复使用" />
        </a-form-item>
      </a-form>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { reconcileInvocation } from '@/apis/connector_api'

const props = defineProps({
  open: Boolean,
  invocation: Object,
})

const emit = defineEmits(['update:open', 'resolved'])

const verdict = ref('failed')
const reason = ref('')
const resultJson = ref('')
const submitting = ref(false)

function formatTime(t) {
  if (!t) return '-'
  try { return new Date(t).toLocaleString('zh-CN') } catch { return t }
}

function formatEvidence(evidence) {
  if (!evidence) return ''
  if (typeof evidence === 'string') {
    try { return JSON.stringify(JSON.parse(evidence), null, 2) } catch { return evidence }
  }
  return JSON.stringify(evidence, null, 2)
}

watch(
  () => props.open,
  (val) => {
    if (val) {
      verdict.value = 'failed'
      reason.value = ''
      resultJson.value = ''
    }
  },
)

async function handleSubmit() {
  if (!props.invocation?.invocation_id) return
  if (!reason.value.trim()) { message.warning('请填写独立远端证据与判定原因'); return }
  let readbackResult = null
  if (verdict.value === 'succeeded') {
    try { readbackResult = JSON.parse(resultJson.value) } catch { message.warning('请填写有效 JSON 回查结果'); return }
    if (readbackResult === null) { message.warning('成功核对需要实际回查结果'); return }
  }
  submitting.value = true
  try {
    const result = await reconcileInvocation(props.invocation.invocation_id, {
      resolution: verdict.value,
      reason: reason.value || undefined,
      result: readbackResult,
    })
    if (result.success) {
      message.success('核对完成')
      emit('resolved')
    } else {
      message.error(result.message || '核对失败')
    }
  } catch (err) {
    message.error(err.message || '核对失败')
  } finally {
    submitting.value = false
  }
}

function handleClose() {
  emit('update:open', false)
}
</script>

<style lang="less" scoped>
.reconcile-modal {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.reconcile-alert {
  margin-bottom: 4px;
}

.reconcile-info {
  padding: 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-50);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.reconcile-row {
  display: flex;
  gap: 12px;
  font-size: 13px;

  label {
    color: var(--gray-500);
    font-weight: 600;
    min-width: 60px;
  }

  .mono {
    font-family: monospace;
    font-size: 12px;
  }
}

.reconcile-evidence {
  padding: 10px;
  background: var(--gray-50);
  border-radius: 6px;
  max-height: 160px;
  overflow-y: auto;

  .evidence-title {
    font-weight: 600;
    font-size: 13px;
    margin-bottom: 6px;
    color: var(--gray-700);
  }

  pre {
    margin: 0;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
  }
}

.reconcile-form {
  margin-top: 4px;
}
</style>
