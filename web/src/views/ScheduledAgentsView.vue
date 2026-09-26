<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { ExternalLink, Eye, History, Plus, Power, PowerOff, RefreshCw, Trash2, X, Zap } from '@lucide/vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'

import { scheduledAgentApi } from '@/apis/scheduled_agent_api'
import ScheduledAgentEditor from '@/components/scheduled-agents/ScheduledAgentEditor.vue'
import {
  createRetriableRequestIds,
  createScheduledAgentAutosave
} from '@/components/scheduled-agents/scheduledAgentAutosave'
import PageShoulder from '@/components/shared/PageShoulder.vue'
import { useAgentStore } from '@/stores/agent'
import { describeSchedule, parseCronExpression } from '@/utils/scheduleFrequency'

const router = useRouter()
const agentStore = useAgentStore()
const jobs = ref([])
const workflows = ref([])
const loading = ref(false)
const saving = ref(false)
const listError = ref('')
const editorError = ref('')
const saveState = ref('idle')
const selectedJobId = ref('')
const creatingDraft = ref(false)
const activeActionId = ref('')
const searchQuery = ref('')
const statusFilter = ref('all')
const runNowRequests = createRetriableRequestIds()
const togglingJobId = ref('')

// 历史抽屉状态
const historyOpen = ref(false)
const historyJobId = ref('')
const historyRuns = ref([])
const historyTotal = ref(0)
const historyLoading = ref(false)
const historyOffset = ref(0)
const HISTORY_PAGE_SIZE = 20

const historyJob = computed(() => jobs.value.find((j) => j.id === historyJobId.value) || null)

const ACCEPTED_RUN_NOW_STATUSES = new Set([
  'dispatching',
  'submitted',
  'queued',
  'dispatched',
  'pending',
  'running'
])
const RUN_STATUS_LABELS = {
  dispatching: '提交中',
  submitted: '已提交',
  queued: '排队中',
  dispatched: '已派发',
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  skipped: '已跳过',
  failed: '失败',
  rejected: '已拒绝',
  cancelled: '已取消',
  interrupted: '已中断',
  unknown: '未知'
}

const availableAgents = computed(() =>
  (agentStore.agents || []).filter((agent) => !agent.is_subagent)
)
const selectedJob = computed(() => jobs.value.find((job) => job.id === selectedJobId.value) || null)
const detailOpen = computed(() => creatingDraft.value || Boolean(selectedJob.value))
const detailStatusLabel = computed(() => {
  if (creatingDraft.value) return '新任务'
  return selectedJob.value?.enabled ? '已开启' : '已关闭'
})

const filteredJobs = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  return jobs.value.filter((job) => {
    if (statusFilter.value === 'enabled' && !job.enabled) return false
    if (statusFilter.value === 'paused' && job.enabled) return false
    if (!query) return true
    return [job.name, job.prompt, agentLabel(job), scheduleLabel(job)]
      .filter(Boolean)
      .some((value) => String(value).toLocaleLowerCase().includes(query))
  })
})

const filterOptions = computed(() => [
  { value: 'all', label: '全部', count: jobs.value.length },
  { value: 'enabled', label: '已开启', count: jobs.value.filter((job) => job.enabled).length },
  { value: 'paused', label: '已关闭', count: jobs.value.filter((job) => !job.enabled).length }
])

async function load({ silent = false } = {}) {
  if (!silent) loading.value = true
  listError.value = ''
  try {
    jobs.value = (await scheduledAgentApi.list()).jobs || []
    if (selectedJobId.value && !jobs.value.some((job) => job.id === selectedJobId.value)) {
      selectedJobId.value = ''
    }
  } catch (error) {
    listError.value = error.message || '加载定时任务失败'
  } finally {
    if (!silent) loading.value = false
  }
}

async function loadWorkflows() {
  try {
    const result = await scheduledAgentApi.listWorkflows()
    workflows.value = result.data || result || []
  } catch (error) {
    console.error('加载工作流失败:', error)
  }
}

function scheduleLabel(job) {
  return describeSchedule(parseCronExpression(job.cron_expression))
}

function agentLabel(job) {
  if (job.target_type === 'workflow') {
    return workflows.value.find((wf) => wf.id === job.workflow_id)?.name || '工作流'
  }
  return (
    availableAgents.value.find((agent) => (agent.slug || agent.id) === job.agent_slug)?.name ||
    job.agent_slug
  )
}

const autosave = createScheduledAgentAutosave({
  persist: ({ jobId, payload, requestId }) =>
    jobId
      ? scheduledAgentApi.update(jobId, payload)
      : scheduledAgentApi.create({ ...payload, request_id: requestId }),
  onPersisted(savedJob, { created, finalizeDraft }) {
    if (created) jobs.value = [{ ...savedJob, runs: [] }, ...jobs.value]
    else {
      jobs.value = jobs.value.map((job) =>
        job.id === savedJob.id ? { ...job, ...savedJob, runs: job.runs || [] } : job
      )
    }
    if (finalizeDraft) {
      creatingDraft.value = false
      selectedJobId.value = savedJob.id
    }
  },
  onState(next) {
    saveState.value = next.state
    saving.value = next.saving
    editorError.value = next.error
  }
})

function flushAutoSave() {
  return autosave.flush()
}

async function confirmSave(payload) {
  saving.value = true
  editorError.value = ''
  try {
    if (creatingDraft.value) {
      const requestId = runNowRequests.get('create')
      const savedJob = await scheduledAgentApi.create({ ...payload, request_id: requestId })
      jobs.value = [{ ...savedJob, runs: [] }, ...jobs.value]
      creatingDraft.value = false
      selectedJobId.value = savedJob.id
      autosave.leaveEditor()
      runNowRequests.complete('create')
      message.success('任务已创建')
    } else {
      const jobId = selectedJob.value?.id
      if (!jobId) throw new Error('任务 ID 不存在')
      const savedJob = await scheduledAgentApi.update(jobId, payload)
      jobs.value = jobs.value.map((job) =>
        job.id === savedJob.id ? { ...job, ...savedJob, runs: job.runs || [] } : job
      )
      autosave.leaveEditor()
      message.success('任务已保存')
    }
  } catch (error) {
    editorError.value = error.message || (creatingDraft.value ? '创建任务失败' : '保存任务失败')
  } finally {
    saving.value = false
  }
}

function cancelDraft() {
  creatingDraft.value = false
  selectedJobId.value = ''
  autosave.leaveEditor()
}

async function selectJob(job) {
  if (!(await flushAutoSave())) return
  creatingDraft.value = false
  selectedJobId.value = job.id
  autosave.leaveEditor()
}

async function openCreate() {
  if (!(await flushAutoSave())) return
  autosave.beginDraft()
  creatingDraft.value = true
  selectedJobId.value = ''
}

async function closeDetail() {
  const discardingInvalidDraft = creatingDraft.value && autosave.canDiscardInvalidDraft()
  if (!discardingInvalidDraft && !(await flushAutoSave())) return
  creatingDraft.value = false
  selectedJobId.value = ''
  autosave.leaveEditor()
}

async function runAction(job, action, fallback) {
  if (!(await flushAutoSave())) return null
  activeActionId.value = job.id
  try {
    const result = await action()
    await load({ silent: true })
    return result
  } catch (error) {
    message.error(error.message || fallback)
    return null
  } finally {
    activeActionId.value = ''
  }
}

async function toggle(job) {
  if (togglingJobId.value) return
  togglingJobId.value = job.id
  try {
    const updated = await scheduledAgentApi.update(job.id, { enabled: !job.enabled })
    jobs.value = jobs.value.map((j) => (j.id === updated.id ? { ...j, ...updated, runs: j.runs || [] } : j))
    message.success(updated.enabled ? '任务已开启' : '任务已关闭')
  } catch (error) {
    message.error(error.message || '更新任务状态失败')
  } finally {
    togglingJobId.value = ''
  }
}

async function runNow(job) {
  if (!(await flushAutoSave())) return
  activeActionId.value = job.id
  const requestId = runNowRequests.get(job.id)
  try {
    const run = await scheduledAgentApi.runNow(job.id, requestId)
    runNowRequests.complete(job.id)
    await load({ silent: true })
    if (ACCEPTED_RUN_NOW_STATUSES.has(run.status)) {
      message.success('已创建一次立即运行')
    } else if (run.status === 'skipped') {
      message.warning(run.error_message || '本次运行已跳过')
    } else {
      message.error(run.error_message || `立即运行状态：${run.status || '未知'}`)
    }
  } catch (error) {
    message.error(error.message || '立即运行失败')
  } finally {
    activeActionId.value = ''
  }
}

function remove(job) {
  Modal.confirm({
    title: '删除定时任务？',
    content: '删除只会停止未来触发，不会删除已经产生的 AgentRun。',
    okText: '删除',
    cancelText: '取消',
    okType: 'danger',
    async onOk() {
      const removed = await runAction(
        job,
        () => scheduledAgentApi.remove(job.id),
        '删除定时任务失败'
      )
      if (removed !== null) await closeDetail()
    }
  })
}

function formatRunTime(value) {
  if (!value) return '等待调度'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(date)
}

function runStatusLabel(run) {
  return RUN_STATUS_LABELS[run.status] || run.status
}

function runStatusTone(run) {
  if (run.status === 'completed') return 'success'
  if (['failed', 'rejected', 'cancelled', 'interrupted'].includes(run.status)) return 'danger'
  if (run.status === 'skipped') return 'warning'
  if (run.status === 'unknown') return 'muted'
  return 'active'
}

function canOpenConversation(run) {
  return Boolean(run.conversation_available && run.thread_id)
}

async function openConversation(run) {
  if (!canOpenConversation(run)) return
  if (!(await flushAutoSave())) return
  await router.push({ name: 'AgentCompWithThreadId', params: { thread_id: run.thread_id } })
}

/** 工作流类型运行记录是否可查看执行详情 */
function canViewRunDetail(run) {
  return run.target_type === 'workflow'
}

/** 跳转到工作流编辑器查看运行详情 */
async function viewRunDetail(run) {
  if (!canViewRunDetail(run)) return
  if (!(await flushAutoSave())) return
  // 需要找到对应的工作流 ID，从 job 的 workflow_id 获取
  const workflowId = run.workflow_id || selectedJob.value?.workflow_id || historyJob.value?.workflow_id
  if (!workflowId) {
    message.warning('无法找到对应的工作流')
    return
  }
  const params = { name: 'WorkflowEditor', params: { id: workflowId } }
  // 只有有 workflow_run_id 时才传递 run_id 参数以自动打开运行结果
  if (run.workflow_run_id) {
    params.query = { run_id: run.workflow_run_id }
  }
  await router.push(params)
}

/** 统一的运行记录点击处理 */
async function handleRunClick(run) {
  if (canOpenConversation(run)) {
    await openConversation(run)
  } else if (canViewRunDetail(run)) {
    await viewRunDetail(run)
  }
}

function runRecordLabel(run) {
  const trigger = run.trigger === 'manual' ? '手动运行' : '定时运行'
  let availability
  if (run.target_type === 'workflow') {
    availability = canViewRunDetail(run) ? '，查看工作流执行详情' : ''
  } else {
    availability = canOpenConversation(run) ? '，打开对应对话' : '，没有可用对话'
  }
  return `${trigger}，${runStatusLabel(run)}，${formatRunTime(run.scheduled_for)}${availability}`
}

function lastExecutionInfo(job) {
  const last = job.last_execution
  if (!last) return { label: '未执行', tone: 'muted' }
  const time = formatRunTime(last.scheduled_for)
  if (last.status === 'completed') return { label: `${time} 成功`, tone: 'success' }
  if (['failed', 'rejected', 'cancelled', 'interrupted'].includes(last.status)) {
    return { label: `${time} 失败`, tone: 'danger' }
  }
  if (['running', 'pending', 'dispatching', 'submitted', 'queued', 'dispatched'].includes(last.status)) {
    return { label: `${time} ${runStatusLabel(last)}`, tone: 'active' }
  }
  if (last.status === 'skipped') return { label: `${time} 已跳过`, tone: 'warning' }
  return { label: `${time} ${runStatusLabel(last)}`, tone: 'muted' }
}

async function openHistory(job) {
  historyJobId.value = job.id
  historyOffset.value = 0
  historyOpen.value = true
  await loadHistoryRuns()
}

function closeHistory() {
  historyOpen.value = false
  historyJobId.value = ''
  historyRuns.value = []
  historyTotal.value = 0
  historyOffset.value = 0
}

async function loadHistoryRuns() {
  if (!historyJobId.value) return
  historyLoading.value = true
  try {
    const result = await scheduledAgentApi.listRuns(historyJobId.value, {
      limit: HISTORY_PAGE_SIZE,
      offset: historyOffset.value
    })
    historyRuns.value = result.runs || []
    historyTotal.value = result.total || 0
  } catch (error) {
    message.error(error.message || '加载历史记录失败')
    historyRuns.value = []
    historyTotal.value = 0
  } finally {
    historyLoading.value = false
  }
}

function historyNextPage() {
  if (historyOffset.value + HISTORY_PAGE_SIZE < historyTotal.value) {
    historyOffset.value += HISTORY_PAGE_SIZE
    loadHistoryRuns()
  }
}

function historyPrevPage() {
  if (historyOffset.value > 0) {
    historyOffset.value = Math.max(0, historyOffset.value - HISTORY_PAGE_SIZE)
    loadHistoryRuns()
  }
}

function formatFullTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(date)
}

watch([searchQuery, statusFilter], () => {
  if (!selectedJob.value) return
  if (!filteredJobs.value.some((job) => job.id === selectedJob.value.id)) void closeDetail()
})

onMounted(async () => {
  if (!agentStore.isInitialized) await agentStore.initialize()
  await Promise.all([load(), loadWorkflows()])
})

onBeforeRouteLeave(() => flushAutoSave())

defineExpose({ beforeLeave: flushAutoSave, loading, saving })
</script>

<template>
  <div class="scheduled-view">
    <section class="scheduled-shell" :class="{ open: detailOpen }">
      <aside class="list-pane" aria-label="定时任务列表">
        <PageShoulder
          v-model:search="searchQuery"
          class="schedule-shoulder"
          search-placeholder="搜索已安排任务"
        >
          <template #actions>
            <a-button
              class="lucide-icon-btn"
              :disabled="loading"
              aria-label="刷新定时任务"
              @click="load()"
            >
              <RefreshCw
                :size="14"
                class="page-shoulder-refresh-icon"
                :class="{ 'is-spinning': loading }"
              />
            </a-button>
            <a-button type="primary" class="lucide-icon-btn" @click="openCreate">
              <Plus :size="14" />
              新建任务
            </a-button>
          </template>
        </PageShoulder>

        <a-alert v-if="listError" class="list-alert" type="error" show-icon :message="listError">
          <template #action><a-button size="small" @click="load()">重新加载</a-button></template>
        </a-alert>

        <template v-else>
          <div class="filter-row" aria-label="任务状态筛选">
            <button
              v-for="option in filterOptions"
              :key="option.value"
              type="button"
              :class="{ active: statusFilter === option.value }"
              :aria-pressed="statusFilter === option.value"
              @click="statusFilter = option.value"
            >
              {{ option.label }} <span>{{ option.count }}</span>
            </button>
          </div>

          <div v-if="loading" class="task-skeleton" aria-label="正在加载定时任务">
            <span v-for="index in 3" :key="index"></span>
          </div>

          <div v-else-if="filteredJobs.length" class="task-list">
            <div
              v-for="job in filteredJobs"
              :key="job.id"
              class="task-card"
              :class="{ selected: selectedJobId === job.id }"
              :aria-current="selectedJobId === job.id ? 'true' : undefined"
            >
              <div class="task-card-main" @click="selectJob(job)">
                <div class="task-card-row1">
                  <span class="task-card-badge" :class="job.enabled ? 'enabled' : 'disabled'">
                    {{ job.enabled ? '已开启' : '已关闭' }}
                  </span>
                  <strong class="task-card-title">{{ job.name }}</strong>
                </div>
                <div class="task-card-row2">
                  <small class="task-card-freq">{{ scheduleLabel(job) }}</small>
                  <span class="task-card-last-run">
                    <span class="run-dot" :class="lastExecutionInfo(job).tone"></span>
                    <span>{{ lastExecutionInfo(job).label }}</span>
                  </span>
                </div>
              </div>
              <div class="task-card-actions">
                <button type="button" class="card-btn" title="查看详情" @click="selectJob(job)">
                  <Eye :size="14" />
                </button>
                <button type="button" class="card-btn" title="历史记录" @click="openHistory(job)">
                  <History :size="14" />
                </button>
                <button
                  type="button"
                  class="card-btn"
                  :title="job.enabled ? '关闭' : '开启'"
                  :disabled="togglingJobId === job.id"
                  @click.stop="toggle(job)"
                >
                  <Power v-if="!job.enabled" :size="14" />
                  <PowerOff v-else :size="14" />
                </button>
                <button
                  type="button"
                  class="card-btn danger"
                  title="删除"
                  :disabled="activeActionId === job.id"
                  @click.stop="remove(job)"
                >
                  <Trash2 :size="14" />
                </button>
              </div>
            </div>
          </div>

          <div v-else class="list-empty">
            <strong>{{ jobs.length ? '没有匹配的任务' : '还没有定时任务' }}</strong>
            <span>{{ jobs.length ? '调整搜索或筛选条件。' : '使用右上角的新建任务开始。' }}</span>
          </div>
        </template>
      </aside>

      <Transition name="detail-slide">
        <main v-if="detailOpen" class="detail-pane">
          <header class="detail-toolbar">
            <span class="task-status" :class="{ paused: selectedJob && !selectedJob.enabled }">
              {{ detailStatusLabel }}
            </span>
            <div class="detail-actions">
              <template v-if="selectedJob">
                <button
                  type="button"
                  :disabled="Boolean(activeActionId)"
                  @click="runNow(selectedJob)"
                >
                  <Zap :size="15" aria-hidden="true" />
                  立即运行
                </button>
                <button
                  type="button"
                  :disabled="togglingJobId === selectedJob.id"
                  @click="toggle(selectedJob)"
                >
                  <Power v-if="!selectedJob.enabled" :size="15" aria-hidden="true" />
                  <PowerOff v-else :size="15" aria-hidden="true" />
                  {{ selectedJob.enabled ? '关闭' : '开启' }}
                </button>
                <button
                  type="button"
                  @click="openHistory(selectedJob)"
                >
                  <History :size="15" aria-hidden="true" />
                  历史
                </button>
                <button
                  type="button"
                  class="icon-button danger"
                  aria-label="删除任务"
                  :disabled="Boolean(activeActionId)"
                  @click="remove(selectedJob)"
                >
                  <Trash2 :size="15" aria-hidden="true" />
                </button>
              </template>
              <button
                type="button"
                class="icon-button"
                aria-label="关闭任务详情"
                @click="closeDetail"
              >
                <X :size="17" aria-hidden="true" />
              </button>
            </div>
          </header>

          <ScheduledAgentEditor
            :job="selectedJob"
            :agents="availableAgents"
            :workflows="workflows"
            :saving="saving"
            :save-state="saveState"
            :error="editorError"
            :is-new="creatingDraft"
            @confirm="confirmSave"
            @cancel="cancelDraft"
          />

          <section v-if="selectedJob" class="history-section" aria-labelledby="runs-heading">
            <header>
              <div>
                <h3 id="runs-heading">最近运行</h3>
                <p>{{ selectedJob.runs?.length || 0 }} 条记录</p>
              </div>
              <button type="button" class="view-all-btn" @click="openHistory(selectedJob)">
                <History :size="13" /> 查看全部
              </button>
            </header>

            <div v-if="selectedJob.runs?.length" class="run-list">
              <div
                v-for="run in selectedJob.runs"
                :key="run.id"
                class="run-row"
                :class="{ actionable: canOpenConversation(run) || canViewRunDetail(run) }"
                :role="(canOpenConversation(run) || canViewRunDetail(run)) ? 'button' : undefined"
                :tabindex="(canOpenConversation(run) || canViewRunDetail(run)) ? 0 : undefined"
                :aria-label="runRecordLabel(run)"
                @click="handleRunClick(run)"
                @keydown.enter="handleRunClick(run)"
              >
                <span class="run-status" :class="runStatusTone(run)">{{ runStatusLabel(run) }}</span>
                <span class="run-copy">
                  <strong>{{ run.trigger === 'manual' ? '手动运行' : '定时运行' }}</strong>
                  <small v-if="run.error_message" :title="run.error_message">{{ run.error_message }}</small>
                  <small v-else>{{
                    run.target_type === 'workflow'
                      ? (canViewRunDetail(run) ? '查看工作流执行详情' : '')
                      : (canOpenConversation(run) ? '查看对话和运行结果' : '')
                  }}</small>
                </span>
                <time :datetime="run.scheduled_for">{{ formatRunTime(run.scheduled_for) }}</time>
                <ExternalLink v-if="canOpenConversation(run) || canViewRunDetail(run)" :size="15" aria-hidden="true" />
              </div>
            </div>
            <p v-else class="runs-empty">任务运行后，记录会显示在这里。</p>
          </section>
        </main>
      </Transition>
    </section>

    <!-- 历史抽屉 -->
    <Transition name="drawer-slide">
      <aside v-if="historyOpen" class="history-drawer" aria-label="运行历史">
        <header class="drawer-header">
          <div>
            <h2>{{ historyJob?.name || '任务' }} — 运行历史</h2>
            <span>{{ historyTotal }} 条记录</span>
          </div>
          <button type="button" class="icon-button" aria-label="关闭历史" @click="closeHistory">
            <X :size="17" />
          </button>
        </header>

        <div v-if="historyLoading" class="drawer-loading">加载中…</div>
        <div v-else-if="!historyRuns.length" class="drawer-empty">暂无运行记录。</div>
        <div v-else class="drawer-list">
          <div
            v-for="run in historyRuns"
            :key="run.id"
            class="drawer-run-row"
            :class="{ actionable: canOpenConversation(run) || canViewRunDetail(run) }"
            :role="(canOpenConversation(run) || canViewRunDetail(run)) ? 'button' : undefined"
            :tabindex="(canOpenConversation(run) || canViewRunDetail(run)) ? 0 : undefined"
            @click="handleRunClick(run)"
            @keydown.enter="handleRunClick(run)"
          >
            <div class="drawer-run-top">
              <span class="run-status" :class="runStatusTone(run)">{{ runStatusLabel(run) }}</span>
              <span class="drawer-trigger">{{ run.trigger === 'manual' ? '手动' : '定时' }}</span>
              <time>{{ formatFullTime(run.scheduled_for) }}</time>
            </div>
            <div class="drawer-run-bottom">
              <span v-if="run.started_at">开始：{{ formatFullTime(run.started_at) }}</span>
              <span v-else class="muted">未开始</span>
              <span v-if="run.completed_at">结束：{{ formatFullTime(run.completed_at) }}</span>
              <span v-if="run.error_message" class="drawer-error" :title="run.error_message">
                {{ run.error_message }}
              </span>
            </div>
            <ExternalLink v-if="canOpenConversation(run) || canViewRunDetail(run)" :size="14" class="drawer-link-icon" />
          </div>
        </div>

        <footer v-if="historyTotal > HISTORY_PAGE_SIZE" class="drawer-footer">
          <button type="button" :disabled="historyOffset === 0" @click="historyPrevPage">上一页</button>
          <span>{{ historyOffset + 1 }}–{{ Math.min(historyOffset + HISTORY_PAGE_SIZE, historyTotal) }} / {{ historyTotal }}</span>
          <button type="button" :disabled="historyOffset + HISTORY_PAGE_SIZE >= historyTotal" @click="historyNextPage">下一页</button>
        </footer>
      </aside>
    </Transition>
  </div>
</template>

<style lang="less" scoped>
.scheduled-view {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex-direction: column;
}

.schedule-shoulder {
  width: 100%;
  max-width: 820px;
  margin: 0 auto;
  flex: none;

  :deep(.page-shoulder-left) {
    min-width: 0;
    flex: 1;
  }

  :deep(.search-input) {
    width: min(280px, 100%);
  }
}

.scheduled-shell {
  display: flex;
  flex: 1;
  width: 100%;
  min-height: 0;
  overflow: hidden;
  color: var(--gray-1000);
}

.list-alert {
  flex: 1;
  margin: 20px;
}

.list-pane {
  display: flex;
  flex-direction: column;
  flex: 1 1 100%;
  min-width: 0;
  height: 100%;
  overflow-y: auto;
  border-right: 1px solid transparent;
  transition:
    flex-basis 160ms cubic-bezier(0.16, 1, 0.3, 1),
    max-width 160ms cubic-bezier(0.16, 1, 0.3, 1),
    border-color 160ms ease,
    background-color 160ms ease;
}

.scheduled-shell:not(.open) .list-pane {
  max-width: 820px;
  margin: 0 auto;
  margin-top: 20px;
  padding-bottom: 24px;
}

.scheduled-shell.open .list-pane {
  flex: 0 0 40%;
  max-width: 40%;
  border-right-color: var(--gray-150);
}

.filter-row {
  position: sticky;
  z-index: 1;
  top: 0;
  padding: 10px 14px 12px;
  background: inherit;
  display: flex;
  align-items: center;
  gap: 4px;

  button {
    display: inline-flex;
    min-height: 28px;
    padding: 0 8px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: var(--gray-500);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    align-items: center;
    gap: 5px;

    &:hover,
    &.active {
      background: var(--gray-50);
      color: var(--gray-900);
    }

    span {
      color: var(--gray-400);
      font-variant-numeric: tabular-nums;
    }
  }
}

.task-list {
  display: grid;
  padding: 8px 12px;
  gap: 6px;
}

.task-card {
  display: flex;
  min-height: 64px;
  padding: 10px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  align-items: center;
  gap: 8px;
  transition:
    border-color 120ms ease,
    background-color 120ms ease;

  &:hover {
    border-color: var(--gray-200);
    background: var(--gray-10);
  }

  &.selected {
    border-color: var(--main-color);
    background: var(--main-50);
  }
}

.task-card-main {
  flex: 1;
  min-width: 0;
  cursor: pointer;
  display: grid;
  gap: 4px;
}

.task-card-row1 {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.task-card-title {
  overflow: hidden;
  color: var(--gray-900);
  font-size: 13px;
  font-weight: 550;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.task-card-badge {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 500;

  &.enabled {
    background: var(--color-success-50);
    color: var(--color-success-700);
  }

  &.disabled {
    background: var(--gray-100);
    color: var(--gray-500);
  }
}

.task-card-row2 {
  display: flex;
  align-items: center;
  gap: 12px;
}

.task-card-freq {
  color: var(--gray-400);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.task-card-last-run {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--gray-500);
  font-size: 11px;
}

.run-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--gray-300);

  &.success { background: var(--color-success-500); }
  &.danger { background: var(--color-error-500); }
  &.active { background: var(--color-info-500); }
  &.warning { background: var(--color-warning-500); }
  &.muted { background: var(--gray-300); }
}

.task-card-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 2px;
}

.card-btn {
  display: inline-flex;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--gray-500);
  cursor: pointer;
  align-items: center;
  justify-content: center;

  &:hover:not(:disabled) {
    background: var(--gray-50);
    color: var(--gray-800);
  }

  &:focus-visible {
    outline: 2px solid var(--main-color);
    outline-offset: 1px;
  }

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  &.danger:hover:not(:disabled) {
    background: var(--color-error-50);
    color: var(--color-error-700);
  }
}

.task-skeleton {
  display: grid;
  padding: 8px 12px;
  gap: 4px;

  span {
    height: 62px;
    border-radius: 9px;
    background: var(--gray-25);
  }
}

.list-empty {
  display: grid;
  min-height: 240px;
  color: var(--gray-400);
  place-content: center;
  justify-items: center;
  gap: 5px;

  strong {
    color: var(--gray-700);
    font-size: 14px;
  }

  span {
    font-size: 12px;
  }
}

.detail-pane {
  flex: 0 0 60%;
  width: 60%;
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  background: var(--gray-0);
}

.detail-toolbar {
  display: flex;
  min-height: 48px;
  padding: 0 16px 0 22px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.task-status {
  color: var(--color-success-700);
  font-size: 12px;

  &.paused {
    color: var(--gray-500);
  }
}

.detail-actions {
  display: flex;
  align-items: center;
  gap: 4px;

  button {
    display: inline-flex;
    height: 30px;
    padding: 0 8px;
    border: 1px solid transparent;
    border-radius: 5px;
    background: transparent;
    color: var(--gray-700);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
    align-items: center;
    justify-content: center;
    gap: 4px;

    svg {
      flex: none;
    }

    &:hover:not(:disabled) {
      background: var(--gray-50);
      color: var(--gray-1000);
    }

    &:focus-visible {
      outline: 2px solid var(--main-color);
      outline-offset: 1px;
    }

    &:disabled {
      cursor: default;
      opacity: 0.45;
    }
  }

  .icon-button {
    width: 30px;
    padding: 0;
  }

  .danger:hover:not(:disabled) {
    background: var(--color-error-50);
    color: var(--color-error-700);
  }
}

.history-section {
  padding: 0 22px 24px;

  > header {
    display: flex;
    padding: 10px 0 6px;
    border-bottom: 1px solid var(--gray-150);
    align-items: flex-end;
    justify-content: space-between;

    h3 {
      margin: 0;
      color: var(--gray-700);
      font-size: 12px;
      font-weight: 500;
    }

    p {
      margin: 2px 0 0;
      color: var(--gray-400);
      font-size: 11px;
    }

    > span {
      color: var(--gray-400);
      font-size: 11px;
    }
  }
}

.run-list {
  border-bottom: 1px solid var(--gray-100);
}

.run-row {
  display: grid;
  width: 100%;
  min-height: 44px;
  padding: 10px 12px;
  border: 0;
  border-bottom: 1px solid var(--gray-100);
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  grid-template-columns: 58px minmax(0, 1fr) auto 18px;
  align-items: center;
  gap: 10px;

  &:last-child {
    border-bottom: 0;
  }

  &.actionable {
    cursor: pointer;

    &:hover {
      background: var(--gray-25);
    }
  }

  &:focus-visible {
    outline: 2px solid var(--main-color);
    outline-offset: 1px;
  }

  time,
  svg,
  .no-conversation {
    color: var(--gray-400);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
}

.run-status {
  color: var(--color-info-700);
  font-size: 11px;

  &.success {
    color: var(--color-success-700);
  }

  &.danger {
    color: var(--color-error-700);
  }

  &.warning {
    color: var(--color-warning-800);
  }
}

.run-copy {
  display: grid;
  min-width: 0;
  gap: 2px;

  strong,
  small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: var(--gray-800);
    font-size: 12px;
    font-weight: 550;
  }

  small {
    color: var(--gray-400);
    font-size: 11px;
  }
}

.runs-empty {
  margin: 0;
  padding: 22px 0;
  border-bottom: 1px solid var(--gray-100);
  color: var(--gray-400);
  font-size: 12px;
}

.view-all-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--gray-500);
  font: inherit;
  font-size: 11px;
  cursor: pointer;

  &:hover {
    background: var(--gray-50);
    color: var(--gray-800);
  }
}

/* 历史抽屉 */
.history-drawer {
  position: fixed;
  z-index: 100;
  top: 0;
  right: 0;
  display: flex;
  width: 400px;
  max-width: 90vw;
  height: 100%;
  flex-direction: column;
  border-left: 1px solid var(--gray-150);
  background: var(--gray-0);
  box-shadow: -4px 0 16px rgb(0 0 0 / 6%);
}

.drawer-header {
  display: flex;
  padding: 16px 20px;
  border-bottom: 1px solid var(--gray-150);
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;

  h2 {
    margin: 0;
    color: var(--gray-900);
    font-size: 15px;
    font-weight: 600;
  }

  span {
    color: var(--gray-400);
    font-size: 12px;
  }

  .icon-button {
    display: inline-flex;
    width: 30px;
    height: 30px;
    padding: 0;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: var(--gray-500);
    cursor: pointer;
    align-items: center;
    justify-content: center;

    &:hover {
      background: var(--gray-50);
      color: var(--gray-800);
    }
  }
}

.drawer-loading,
.drawer-empty {
  display: grid;
  padding: 40px 20px;
  color: var(--gray-400);
  font-size: 13px;
  place-content: center;
}

.drawer-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 12px;
}

.drawer-run-row {
  position: relative;
  display: grid;
  min-height: 56px;
  padding: 10px 8px;
  border-bottom: 1px solid var(--gray-100);
  gap: 4px;

  &.actionable {
    cursor: pointer;

    &:hover {
      background: var(--gray-25);
    }
  }

  &:focus-visible {
    outline: 2px solid var(--main-color);
    outline-offset: -2px;
  }
}

.drawer-run-top {
  display: flex;
  align-items: center;
  gap: 8px;

  time {
    margin-left: auto;
    color: var(--gray-400);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
}

.drawer-trigger {
  color: var(--gray-500);
  font-size: 11px;
}

.drawer-run-bottom {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--gray-500);
  font-size: 11px;

  .muted {
    color: var(--gray-400);
  }
}

.drawer-error {
  overflow: hidden;
  max-width: 200px;
  color: var(--color-error-600);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-link-icon {
  position: absolute;
  top: 10px;
  right: 8px;
  color: var(--gray-400);
}

.drawer-footer {
  display: flex;
  padding: 10px 20px;
  border-top: 1px solid var(--gray-150);
  align-items: center;
  justify-content: space-between;
  gap: 8px;

  span {
    color: var(--gray-500);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  button {
    padding: 4px 10px;
    border: 1px solid var(--gray-200);
    border-radius: 5px;
    background: transparent;
    color: var(--gray-700);
    font: inherit;
    font-size: 12px;
    cursor: pointer;

    &:hover:not(:disabled) {
      background: var(--gray-50);
    }

    &:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
  }
}

.drawer-slide-enter-active,
.drawer-slide-leave-active {
  transition: transform 200ms cubic-bezier(0.16, 1, 0.3, 1);
}

.drawer-slide-enter-from,
.drawer-slide-leave-to {
  transform: translateX(100%);
}

.detail-slide-enter-active {
  transition:
    flex-basis 160ms cubic-bezier(0.16, 1, 0.3, 1),
    width 160ms cubic-bezier(0.16, 1, 0.3, 1),
    opacity 130ms ease,
    transform 160ms cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
  min-width: 0 !important;
}

.detail-slide-leave-active {
  transition:
    flex-basis 140ms cubic-bezier(0.16, 1, 0.3, 1),
    width 140ms cubic-bezier(0.16, 1, 0.3, 1),
    opacity 110ms ease,
    transform 140ms cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
  min-width: 0 !important;
}

.detail-slide-enter-from,
.detail-slide-leave-to {
  flex-basis: 0 !important;
  width: 0 !important;
  min-width: 0 !important;
  opacity: 0;
  transform: translateX(14px);
}

@media (max-width: 1100px) {
  .scheduled-shell.open {
    display: block;
  }

  .open .list-pane {
    display: none;
  }

  .scheduled-shell.open .detail-pane {
    width: 100%;
    height: 100%;
    flex: 1 1 100%;
  }
}

@media (max-width: 640px) {
  .schedule-shoulder {
    gap: 8px;
    padding-inline: 12px;
  }

  .scheduled-shell:not(.open) .list-pane {
    padding-inline: 12px;
  }

  .detail-toolbar {
    padding-inline: 12px;
  }

  .detail-actions button:not(.icon-button) {
    width: 30px;
    padding: 0;
    font-size: 0;
    gap: 0;
  }

  .history-section {
    padding-inline: 16px;
  }

  .run-row {
    grid-template-columns: 52px minmax(0, 1fr) 18px;

    time,
    .no-conversation {
      display: none;
    }
  }

  .task-card-actions {
    flex-wrap: wrap;
  }

  .history-drawer {
    width: 100%;
    max-width: 100vw;
  }
}

@media (prefers-reduced-motion: reduce) {
  .scheduled-shell,
  .list-pane {
    transition: none;
  }

  .detail-slide-enter-active,
  .detail-slide-leave-active {
    transition: none;
  }

  .detail-slide-enter-from,
  .detail-slide-leave-to {
    transform: none;
  }
}
</style>
