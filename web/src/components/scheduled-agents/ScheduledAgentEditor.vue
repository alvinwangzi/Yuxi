<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'

import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import ProjectSelectionSection from '@/components/ProjectSelectionSection.vue'
import ToolApprovalModeSelector from '@/components/ToolApprovalModeSelector.vue'
import { workflowApi } from '@/apis/workflow_api'
import { AUTO_PROJECT_ID } from '@/utils/projectSelection'
import {
  applyFrequencyChange,
  buildCronExpression,
  dayOptions,
  intervalUnits,
  monthOptions,
  parseCronExpression,
  scheduleFrequencies,
  weekdayOptions
} from '@/utils/scheduleFrequency'

const props = defineProps({
  job: { type: Object, default: null },
  agents: { type: Array, default: () => [] },
  workflows: { type: Array, default: () => [] },
  saving: { type: Boolean, default: false },
  saveState: { type: String, default: 'idle' },
  error: { type: String, default: '' }
})
const emit = defineEmits(['change'])

const defaultSchedule = {
  frequency: 'daily',
  time: '09:00',
  weekdays: [1],
  dayOfMonth: 1,
  month: 1,
  intervalValue: 1,
  intervalUnit: 'hour',
  cronMinute: '0',
  cronHour: '9',
  cronDay: '*',
  cronMonth: '*',
  cronWeekday: '*',
  cronExpression: '0 9 * * *'
}

const agentValues = computed(() =>
  props.agents.map((agent) => agent.slug || agent.id).filter(Boolean)
)

function initialForm(job) {
  const schedule = job ? parseCronExpression(job.cron_expression) : defaultSchedule
  const cronExpr = schedule?.cronExpression || buildCronExpression(schedule) || defaultSchedule.cronExpression
  const cronParts = cronExpr.split(/\s+/)
  return {
    name: job?.name || '',
    prompt: job?.prompt || '',
    project_id: job?.project_id || '',
    target_type: job?.target_type || 'agent',
    agent_slug: job?.agent_slug || agentValues.value[0] || '',
    workflow_id: job?.workflow_id || '',
    input_variables: job?.input_variables || {},
    ...schedule,
    cronExpression: cronExpr,
    cronMinute: cronParts[0] || '0',
    cronHour: cronParts[1] || '9',
    cronDay: cronParts[2] || '*',
    cronMonth: cronParts[3] || '*',
    cronWeekday: cronParts[4] || '*',
    model_spec: job?.model_spec || '',
    timezone: job?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai',
    tool_approval_mode: job?.tool_approval_mode || 'default'
  }
}

const form = reactive(initialForm(props.job))
let hydrating = false

const daysInSelectedMonth = computed(() => {
  if (form.frequency !== 'yearly') return 31
  if (Number(form.month) === 2) return 28
  return [4, 6, 9, 11].includes(Number(form.month)) ? 30 : 31
})
const availableDayOptions = computed(() => dayOptions.slice(0, daysInSelectedMonth.value))

const saveLabel = computed(() => {
  if (!props.job && props.saveState === 'invalid') return '填写完整后自动创建'
  if (props.saveState === 'dirty') return '等待自动保存'
  if (props.saveState === 'saving' || props.saving) return '正在保存'
  if (props.saveState === 'saved') return '已自动保存'
  if (props.saveState === 'error') return '保存失败'
  if (props.saveState === 'invalid') return '补全必填项后自动保存'
  return props.job ? '修改会自动保存' : '填写完整后自动创建'
})

function validationMessage() {
  if (!form.name.trim()) return '请输入任务名称'
  if (!form.project_id || form.project_id === AUTO_PROJECT_ID) return '请选择一个 Project'
  // 根据 target_type 校验不同字段
  if (form.target_type === 'workflow') {
    if (!form.workflow_id) return '请选择要执行的工作流'
  } else {
    if (!form.prompt.trim()) return '请输入任务指令'
    if (!form.agent_slug) return '请选择执行智能体'
  }
  if (form.frequency === 'weekly' && !form.weekdays.length) return '请至少选择一个执行日'
  if (form.frequency === 'interval') {
    const n = Number(form.intervalValue)
    if (!n || n < 1) return '请输入有效的间隔数值'
    if (form.intervalUnit !== 'minute' && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(form.time)) {
      return '请选择执行时间'
    }
  } else if (form.frequency !== 'custom' && !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(form.time)) {
    return '请选择执行时间'
  }
  if (form.frequency === 'custom') {
    const parts = [form.cronMinute, form.cronHour, form.cronDay, form.cronMonth, form.cronWeekday]
    if (parts.some(p => !p || p.trim() === '')) return '请填写完整的 Cron 字段'
  }
  return ''
}

function buildCustomCron() {
  return [form.cronMinute, form.cronHour, form.cronDay, form.cronMonth, form.cronWeekday].join(' ')
}

function changePayload() {
  const validationError = validationMessage()
  if (validationError) return { error: validationError, payload: null }
  const payload = {
    name: form.name.trim(),
    project_id: form.project_id,
    target_type: form.target_type,
    cron_expression: form.frequency === 'custom' ? buildCustomCron() : buildCronExpression(form),
    timezone: form.timezone
  }
  // 根据 target_type 添加不同字段
  if (form.target_type === 'workflow') {
    payload.workflow_id = Number(form.workflow_id)
    payload.input_variables = form.input_variables || {}
  } else {
    payload.prompt = form.prompt.trim()
    payload.agent_slug = form.agent_slug
    payload.model_spec = form.model_spec
    payload.tool_approval_mode = form.tool_approval_mode
  }
  return { error: '', payload }
}

function toggleWeekday(day) {
  const selected = new Set(form.weekdays)
  if (selected.has(day)) selected.delete(day)
  else selected.add(day)
  form.weekdays = [...selected].sort((left, right) => left - right)
}

watch(agentValues, (values) => {
  if (!form.agent_slug && values.length) form.agent_slug = values[0]
})

watch(daysInSelectedMonth, (days) => {
  if (form.dayOfMonth > days) form.dayOfMonth = days
})

watch(
  () => props.job?.id,
  async (jobId, previousJobId) => {
    if (jobId === previousJobId) return
    hydrating = true
    Object.assign(form, initialForm(props.job))
    await nextTick()
    hydrating = false
  }
)

watch(
  form,
  () => {
    if (!hydrating) emit('change', changePayload())
  },
  { deep: true }
)

/** 切换频率并保留切换前的结构化 Cron。 */
function changeFrequency(frequency) {
  Object.assign(form, applyFrequencyChange(form, frequency))
}

// 工作流变量定义
const workflowVariables = ref([])
const workflowLoading = ref(false)

// 当选择工作流时加载变量定义
watch(
  () => form.workflow_id,
  async (workflowId) => {
    if (form.target_type !== 'workflow' || !workflowId) {
      workflowVariables.value = []
      return
    }
    workflowLoading.value = true
    try {
      const res = await workflowApi.get(workflowId)
      const data = res?.data || res
      if (data) {
        // 优先从 definition.variables 读取，兼容从开始步骤中读取
        let variables = data.definition?.variables || []
        if (!variables.length) {
          const startStep = (data.definition?.steps || []).find(s => s.type === 'start')
          if (startStep?.variables) {
            variables = startStep.variables
          }
        }
        workflowVariables.value = variables.map(v => typeof v === 'string' ? { name: v, default: '' } : v)
        // 初始化未设置的变量为默认值
        const currentVars = form.input_variables || {}
        const newVars = {}
        for (const v of workflowVariables.value) {
          newVars[v.name] = currentVars[v.name] ?? v.default ?? ''
        }
        form.input_variables = newVars
      }
    } catch (err) {
      console.error('加载工作流变量失败:', err)
    } finally {
      workflowLoading.value = false
    }
  },
  { immediate: true }
)
</script>

<template>
  <section class="inline-editor" aria-label="任务配置">
    <div class="title-line">
      <input
        v-model="form.name"
        class="name-input"
        maxlength="255"
        aria-label="任务名称"
        placeholder="未命名任务"
      />
      <span class="save-state" :class="saveState">{{ saveLabel }}</span>
    </div>

    <!-- 执行目标选择器 -->
    <div class="target-type-selector">
      <label class="target-type-option" :class="{ active: form.target_type === 'agent' }">
        <input type="radio" v-model="form.target_type" value="agent" />
        <span class="target-icon">🤖</span>
        <span>智能体</span>
      </label>
      <label class="target-type-option" :class="{ active: form.target_type === 'workflow' }">
        <input type="radio" v-model="form.target_type" value="workflow" />
        <span class="target-icon">⚙️</span>
        <span>工作流</span>
      </label>
    </div>

    <!-- Agent 模式：显示 prompt 输入 -->
    <label v-if="form.target_type === 'agent'" class="prompt-field">
      <span class="sr-only">任务指令</span>
      <textarea
        v-model="form.prompt"
        maxlength="32000"
        rows="4"
        placeholder="描述每次触发时智能体需要完成的工作"
      />
    </label>

    <p v-if="error" class="save-error" role="alert">{{ error }}</p>

    <section class="settings-section" aria-labelledby="context-settings-heading">
      <h3 id="context-settings-heading">详情</h3>
      <div class="settings-card">
        <!-- 工作流模式：显示工作流选择器 -->
        <div v-if="form.target_type === 'workflow'" class="setting-row">
          <span>工作流</span>
          <div class="setting-control">
            <select v-model="form.workflow_id" :disabled="saving" aria-label="选择工作流">
              <option value="" disabled>请选择工作流</option>
              <option
                v-for="wf in workflows"
                :key="wf.id"
                :value="wf.id"
              >
                {{ wf.name }}
              </option>
            </select>
          </div>
        </div>
        <!-- 工作流输入变量 -->
        <template v-if="form.target_type === 'workflow' && form.workflow_id">
          <div v-if="workflowLoading" class="setting-row">
            <span>加载变量中...</span>
          </div>
          <template v-else-if="workflowVariables.length > 0">
            <div
              v-for="v in workflowVariables"
              :key="v.name"
              class="setting-row"
            >
              <span :title="v.description || ''">{{ v.name }}</span>
              <div class="setting-control">
                <input
                  v-model="form.input_variables[v.name]"
                  type="text"
                  :placeholder="v.default || v.description || ''"
                  :disabled="saving"
                />
              </div>
            </div>
          </template>
          <div v-else class="setting-row workflow-no-vars">
            <span>此工作流无输入变量</span>
          </div>
        </template>
        <!-- Agent 模式：显示智能体选择器 -->
        <div v-if="form.target_type === 'agent'" class="setting-row">
          <span>智能体</span>
          <div class="setting-control">
            <select v-model="form.agent_slug" :disabled="saving" aria-label="执行智能体">
              <option
                v-for="agent in agents"
                :key="agent.slug || agent.id"
                :value="agent.slug || agent.id"
              >
                {{ agent.name || agent.slug || agent.id }}
              </option>
            </select>
          </div>
        </div>
        <div class="setting-row">
          <span>Project</span>
          <div class="setting-control">
            <ProjectSelectionSection
              v-model="form.project_id"
              :disabled="saving"
              :allow-auto="false"
              eager-load
              aria-label="任务 Project"
            />
          </div>
        </div>
        <!-- 以下设置仅在 Agent 模式下显示 -->
        <template v-if="form.target_type === 'agent'">
          <div class="setting-row">
            <span>模型</span>
            <div class="setting-control">
              <ModelSelectorComponent
                :model_spec="form.model_spec"
                clearable
                size="nano"
                display-name="mini"
                placeholder="跟随智能体模型"
                @select-model="(spec) => (form.model_spec = spec)"
              />
            </div>
          </div>
          <div class="setting-row">
            <span>工具审批</span>
            <div class="setting-control">
              <ToolApprovalModeSelector v-model="form.tool_approval_mode" />
            </div>
          </div>
        </template>
      </div>
      <p v-if="form.target_type === 'agent' && form.tool_approval_mode === 'always_trust'" class="trust-warning">
        允许敏感工具无人值守执行，仅用于可信的智能体和 Project。
      </p>
    </section>

    <section class="settings-section" aria-labelledby="schedule-settings-heading">
      <h3 id="schedule-settings-heading">频率</h3>
      <div class="settings-card">
        <fieldset class="setting-row frequency-row">
          <legend class="sr-only">重复频率</legend>
          <span aria-hidden="true">重复</span>
          <div class="frequency-options">
            <label v-for="frequency in scheduleFrequencies" :key="frequency.value">
              <input
                type="radio"
                name="schedule-frequency"
                :value="frequency.value"
                :checked="form.frequency === frequency.value"
                @change="changeFrequency(frequency.value)"
              />
              <span>{{ frequency.label }}</span>
            </label>
          </div>
        </fieldset>
        <div v-if="form.frequency === 'weekly'" class="setting-row weekday-row">
          <span>执行日</span>
          <div class="weekday-options" aria-label="每周执行日">
            <button
              v-for="weekday in weekdayOptions"
              :key="weekday.value"
              type="button"
              :class="{ selected: form.weekdays.includes(weekday.value) }"
              :aria-pressed="form.weekdays.includes(weekday.value)"
              @click="toggleWeekday(weekday.value)"
            >
              {{ weekday.label }}
            </button>
          </div>
        </div>
        <div v-if="form.frequency === 'yearly'" class="setting-row">
          <span>月份</span>
          <div class="setting-control">
            <select v-model.number="form.month" aria-label="执行月份">
              <option v-for="month in monthOptions" :key="month.value" :value="month.value">
                {{ month.label }}
              </option>
            </select>
          </div>
        </div>
        <div v-if="['monthly', 'yearly'].includes(form.frequency)" class="setting-row">
          <span>日期</span>
          <div class="setting-control">
            <select v-model.number="form.dayOfMonth" aria-label="执行日期">
              <option v-for="day in availableDayOptions" :key="day.value" :value="day.value">
                {{ day.label }}
              </option>
            </select>
          </div>
        </div>
        <!-- 间隔模式：每隔 X [单位] -->
        <div v-if="form.frequency === 'interval'" class="setting-row interval-row">
          <span>每隔</span>
          <div class="interval-controls">
            <input
              v-model.number="form.intervalValue"
              type="number"
              min="1"
              max="999"
              class="interval-input"
              aria-label="间隔数值"
            />
            <select v-model="form.intervalUnit" class="interval-unit-select" aria-label="间隔单位">
              <option v-for="unit in intervalUnits" :key="unit.value" :value="unit.value">
                {{ unit.label }}
              </option>
            </select>
            <span class="interval-suffix">执行一次</span>
          </div>
        </div>
        <!-- 间隔模式的小时/天需要设置基准时间 -->
        <div v-if="form.frequency === 'interval' && form.intervalUnit !== 'minute'" class="setting-row">
          <span>基准时间</span>
          <input v-model="form.time" type="time" aria-label="基准执行时间" />
        </div>
        <!-- 自定义 Cron 表单 -->
        <div v-if="form.frequency === 'custom'" class="custom-cron-section">
          <div class="custom-cron-header">按字段设置执行时间</div>
          <div class="custom-cron-grid">
            <div class="cron-field">
              <label>分钟</label>
              <input v-model="form.cronMinute" placeholder="0" class="cron-input" />
              <span class="cron-hint">0-59, 如 0,30</span>
            </div>
            <div class="cron-field">
              <label>小时</label>
              <input v-model="form.cronHour" placeholder="9" class="cron-input" />
              <span class="cron-hint">0-23, 如 8,18</span>
            </div>
            <div class="cron-field">
              <label>日</label>
              <input v-model="form.cronDay" placeholder="*" class="cron-input" />
              <span class="cron-hint">1-31 或 *</span>
            </div>
            <div class="cron-field">
              <label>月</label>
              <input v-model="form.cronMonth" placeholder="*" class="cron-input" />
              <span class="cron-hint">1-12 或 *</span>
            </div>
            <div class="cron-field">
              <label>星期</label>
              <input v-model="form.cronWeekday" placeholder="*" class="cron-input" />
              <span class="cron-hint">0-7 或 *</span>
            </div>
          </div>
          <div class="custom-cron-preview">
            <span class="preview-label">Cron 表达式：</span>
            <code class="preview-value">{{ buildCustomCron() }}</code>
          </div>
          <div class="custom-cron-legend">
            <span><code>*</code> = 每个（不限制）</span>
            <span><code>8,18</code> = 多个值（8点 和 18点）</span>
            <span><code>1-5</code> = 范围（1 到 5）</span>
            <span><code>*/3</code> = 每隔（每 3 个）</span>
          </div>
        </div>
        <!-- 其他频率的时间选择 -->
        <label v-if="form.frequency !== 'interval' && form.frequency !== 'custom'" class="setting-row">
          <span>时间</span>
          <input v-model="form.time" type="time" aria-label="执行时间" />
        </label>
      </div>
    </section>
  </section>
</template>

<style lang="less" scoped>
.inline-editor {
  min-width: 0;
  color: var(--gray-1000);
}

.title-line {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 22px 6px;
}

.name-input {
  min-width: 0;
  padding: 0;
  border: 0;
  outline: 0;
  flex: 1;
  background: transparent;
  color: var(--gray-1000);
  font: inherit;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 24px;

  &:focus {
    box-shadow: 0 1px 0 var(--main-color);
  }
}

.save-state {
  color: var(--gray-400);
  font-size: 12px;
  white-space: nowrap;

  &.saving,
  &.dirty {
    color: var(--gray-600);
  }

  &.saved {
    color: var(--color-success-700);
  }

  &.error,
  &.invalid {
    color: var(--color-error-700);
  }
}

.target-type-selector {
  display: flex;
  gap: 8px;
  padding: 8px 22px;

  .target-type-option {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border: 1px solid var(--gray-200);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
    background: var(--gray-50);
    font-size: 14px;
    color: var(--gray-700);

    input[type="radio"] {
      display: none;
    }

    .target-icon {
      font-size: 16px;
    }

    &:hover {
      border-color: var(--primary-300);
      background: var(--primary-50);
    }

    &.active {
      border-color: var(--primary-500);
      background: var(--primary-100);
      color: var(--primary-700);
      font-weight: 500;
    }
  }
}

.prompt-field {
  display: block;
  padding: 10px 14px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  margin: 8px 22px 18px;
  background: var(--gray-25);

  textarea {
    width: 100%;
    min-height: 72px;
    padding: 0;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--gray-800);
    font: inherit;
    font-size: 13px;
    line-height: 1.6;
    resize: vertical;

    &:focus {
      box-shadow: none;
    }
  }

  &:focus-within {
    border-color: var(--gray-300);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--main-color) 8%, transparent);
  }
}

.save-error {
  margin: 0 22px 8px;
  font-size: 12px;
  line-height: 18px;
  color: var(--color-error-700);
}

.trust-warning {
  padding: 0 2px;
  margin: 6px 0 0;
  color: var(--color-warning-800);
  font-size: 12px;
  line-height: 18px;
  text-align: right;
}

.settings-section {
  padding: 0 22px 18px;

  h3 {
    margin: 0 0 6px;
    color: var(--gray-500);
    font-size: 11px;
    font-weight: 500;
  }
}

.settings-card {
  overflow: hidden;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);

  > .setting-row:last-child {
    border-bottom: 0;
  }
}

.setting-row {
  display: grid;
  min-height: 40px;
  margin: 0;
  padding: 0 14px;
  border-bottom: 1px solid var(--gray-100);
  grid-template-columns: 110px 1fr;
  align-items: center;

  > span {
    color: var(--gray-600);
    font-size: 13px;
  }

  input,
  select {
    width: 100%;
    max-width: 280px;
    height: 30px;
    padding: 0 8px;
    border: 1px solid transparent;
    border-radius: 5px;
    outline: none;
    background: transparent;
    color: var(--gray-900);
    font: inherit;
    font-size: 13px;
    text-align: left;

    &:hover {
      background: var(--gray-50);
    }

    &:focus {
      border-color: var(--gray-200);
      background: var(--gray-0);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--main-color) 10%, transparent);
    }
  }

  select {
    cursor: pointer;
    text-align-last: left;
  }

  input[type='time'] {
    width: 130px;
    max-width: none;
  }
}

.frequency-row {
  min-inline-size: 0;
  border-top: 0;
  border-inline: 0;
}

.frequency-options {
  display: flex;
  justify-content: flex-start;
  gap: 10px;

  label {
    display: inline-flex;
    color: var(--gray-700);
    cursor: pointer;
    font-size: 12px;
    align-items: center;
    gap: 3px;
  }

  input {
    width: auto;
    height: auto;
    padding: 0;
    accent-color: var(--main-color);
  }
}

.setting-control {
  min-width: 0;
  text-align: left;

  :deep(.project-trigger),
  :deep(.project-selection) {
    justify-content: flex-start;
  }

  :deep(.model-select) {
    justify-content: flex-start;
  }

  :deep(.config-dropdown-trigger) {
    justify-content: flex-start;
  }
}

.weekday-options {
  display: flex;
  justify-content: flex-start;
  gap: 4px;

  button {
    width: 28px;
    height: 28px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: 5px;
    background: transparent;
    color: var(--gray-500);
    font: inherit;
    font-size: 12px;
    cursor: pointer;

    &:hover {
      background: var(--gray-50);
      color: var(--gray-800);
    }

    &.selected {
      border-color: var(--gray-200);
      background: var(--gray-100);
      color: var(--gray-900);
    }
  }
}

.interval-row {
  .interval-controls {
    display: flex;
    align-items: center;
    gap: 8px;
    justify-content: flex-start;
  }

  .interval-input {
    width: 64px;
    padding: 4px 8px;
    border: 1px solid var(--gray-200);
    border-radius: 6px;
    background: var(--gray-50);
    color: var(--gray-900);
    font: inherit;
    font-size: 14px;
    text-align: center;
    outline: none;

    &:focus {
      border-color: var(--primary-500);
      background: #fff;
    }
  }

  .interval-unit-select {
    padding: 4px 8px;
    border: 1px solid var(--gray-200);
    border-radius: 6px;
    background: var(--gray-50);
    color: var(--gray-900);
    font: inherit;
    font-size: 14px;
    outline: none;
    cursor: pointer;

    &:focus {
      border-color: var(--primary-500);
      background: #fff;
    }
  }

  .interval-suffix {
    color: var(--gray-500);
    font-size: 14px;
  }
}

.custom-cron-section {
  padding: 12px 14px;
  border-top: 1px solid var(--gray-100);

  .custom-cron-header {
    font-size: 13px;
    font-weight: 500;
    color: var(--gray-700);
    margin-bottom: 12px;
  }

  .custom-cron-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;

    .cron-field {
      display: flex;
      flex-direction: column;
      gap: 4px;

      label {
        font-size: 12px;
        color: var(--gray-500);
        font-weight: 500;
      }

      .cron-input {
        padding: 6px 8px;
        border: 1px solid var(--gray-200);
        border-radius: 6px;
        background: var(--gray-50);
        color: var(--gray-900);
        font: inherit;
        font-size: 14px;
        text-align: center;
        outline: none;
        width: 100%;

        &:focus {
          border-color: var(--primary-500);
          background: #fff;
        }
      }

      .cron-hint {
        font-size: 11px;
        color: var(--gray-400);
        text-align: center;
      }
    }
  }

  .custom-cron-preview {
    margin-top: 12px;
    padding: 8px 12px;
    background: var(--gray-50);
    border-radius: 6px;
    display: flex;
    align-items: center;
    gap: 8px;

    .preview-label {
      font-size: 12px;
      color: var(--gray-500);
    }

    .preview-value {
      font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
      font-size: 13px;
      color: var(--primary-600);
      background: #fff;
      padding: 2px 8px;
      border-radius: 4px;
    }
  }

  .custom-cron-legend {
    margin-top: 10px;
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    font-size: 12px;
    color: var(--gray-500);

    code {
      font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
      font-size: 12px;
      background: var(--gray-100);
      padding: 1px 5px;
      border-radius: 3px;
      color: var(--gray-700);
    }
  }
}

.inline-editor :deep(.project-selection) {
  display: block;
  width: 100%;
}

.inline-editor :deep(.project-trigger),
.inline-editor :deep(.model-select--nano),
.inline-editor :deep(.config-dropdown-trigger) {
  width: 100%;
  max-width: none;
  height: 30px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--gray-900);
  font: inherit;
  font-size: 13px;
  justify-content: flex-end;
  text-align: right;
}

.inline-editor :deep(.project-trigger-label),
.inline-editor :deep(.model-info),
.inline-editor :deep(.model-text),
.inline-editor :deep(.config-dropdown-text) {
  flex: 0 1 auto;
  font: inherit;
  font-size: 13px;
  text-align: right;
}

.inline-editor :deep(.config-dropdown-chevron) {
  margin-left: 2px;
}

.inline-editor :deep(.model-select-content) {
  justify-content: flex-end;
}

.inline-editor :deep(.project-trigger:hover:not(:disabled)),
.inline-editor :deep(.model-select--nano:hover),
.inline-editor :deep(.config-dropdown-trigger:hover:not(:disabled)) {
  border-color: transparent;
  background: var(--gray-50);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 720px) {
  .title-line,
  .settings-section {
    padding-inline: 14px;
  }

  .prompt-field {
    margin-inline: 14px;
  }

  .save-error {
    margin-inline: 14px;
  }

  .title-line {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .name-input {
    width: 100%;
  }

  .setting-row {
    grid-template-columns: 80px 1fr;
  }

  .weekday-options {
    flex-wrap: wrap;
  }

  .frequency-options {
    flex-wrap: wrap;
  }
}

.workflow-no-vars {
  opacity: 0.6;
  font-size: 0.85em;
}
</style>
