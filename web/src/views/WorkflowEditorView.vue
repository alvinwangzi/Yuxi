<template>
  <div class="workflow-editor">
    <!-- 顶部工具栏 -->
    <div class="editor-toolbar">
      <div class="toolbar-left">
        <a-button @click="goBack">
          <template #icon><ArrowLeft /></template>
        </a-button>
        <a-input
          v-if="workflow"
          v-model:value="workflow.name"
          class="workflow-name-input"
          @change="markDirty"
        />
        <a-tag v-if="workflow?.is_builtin" color="gold">内置</a-tag>
        <a-tag v-if="isDirty" color="orange">未保存</a-tag>
      </div>
      <div class="toolbar-right">
        <a-button @click="showRunModal = true" :disabled="isDirty || businessNodeCount === 0">
          <template #icon><Play /></template>
          运行
        </a-button>
        <a-button type="primary" @click="saveWorkflow" :loading="saving">
          <template #icon><Save /></template>
          保存
        </a-button>
      </div>
    </div>

    <!-- 编辑器主体 -->
    <div class="editor-body" v-if="workflow">
      <!-- 画布占满全部空间 -->
      <div class="flow-canvas">
        <VueFlow
          v-model="flowElements"
          :default-viewport="{ zoom: 1, x: 0, y: 0 }"
          :min-zoom="0.2"
          :max-zoom="4"
          :delete-key-code="['Backspace', 'Delete']"
          @node-click="onNodeClick"
          @connect="onConnect"
          @nodes-change="onNodesChange"
          @edges-change="onEdgesChange"
          @drop="onDrop"
          @dragover="onDragOver"
        >
          <Background :gap="16" pattern-color="#e5e7eb" />
          <Controls />
          <MiniMap :node-color="getMiniMapColor" />
          <template #node-workflow="nodeProps">
            <WorkflowNode :data="nodeProps.data" />
          </template>
          <template #edge-workflow="edgeProps">
            <WorkflowEdge v-bind="edgeProps" />
          </template>
        </VueFlow>

        <!-- 空画布提示 -->
        <div v-if="businessNodeCount === 0" class="canvas-empty-hint">
          <Inbox :size="48" stroke-width="1" color="#d1d5db" />
          <p>从底部拖拽节点到此处，并从「开始」连出流程</p>
        </div>

        <!-- 浮动：全局设置按钮 -->
        <div class="floating-settings-btn" @click="showSettings = !showSettings">
          <Settings :size="18" />
        </div>

        <!-- 浮动：全局设置面板 -->
        <div class="floating-settings-panel" v-if="showSettings">
          <div class="panel-header">
            <span>全局设置</span>
            <a-button size="small" type="text" @click="showSettings = false">
              <template #icon><X :size="14" /></template>
            </a-button>
          </div>
          <div class="settings-content">
            <div class="settings-row">
              <span class="settings-label">并发度</span>
              <a-input-number
                v-model:value="concurrency"
                :min="1"
                :max="20"
                style="width: 100%"
                @change="markDirty"
              />
            </div>
            <div class="panel-hint">点击画布上的「开始」节点编辑输入变量</div>
          </div>
        </div>

        <!-- 浮动：步骤编辑抽屉 -->
        <div class="step-drawer" v-if="selectedStep" :class="{ collapsed: stepPanelCollapsed }">
          <div class="panel-header">
            <div class="panel-header-left">
              <a-button
                size="small"
                type="text"
                @click="stepPanelCollapsed = !stepPanelCollapsed"
                :title="stepPanelCollapsed ? '展开' : '收起'"
              >
                <template #icon><ChevronRight v-if="stepPanelCollapsed" :size="14" /><ChevronLeft v-else :size="14" /></template>
              </a-button>
              <span>编辑步骤</span>
            </div>
            <div class="panel-header-actions">
              <a-button
                v-if="!isBoundaryNode(selectedStep.id)"
                size="small"
                type="text"
                danger
                @click="confirmRemoveStep(selectedStep.id)"
              >
                <template #icon><Trash2 :size="14" /></template>
              </a-button>
            </div>
          </div>
          <div class="step-form" v-show="!stepPanelCollapsed">
            <a-form layout="vertical">
              <a-form-item label="步骤 ID">
                <a-input :value="selectedStep.id" disabled />
              </a-form-item>

              <!-- 开始步骤：编辑输入变量（保存到 definition.variables） -->
              <template v-if="selectedStep.type === 'start'">
                <a-form-item label="名称">
                  <a-input v-model:value="selectedStep.name" @change="onNameChange" />
                </a-form-item>
                <a-divider>输入变量</a-divider>
                <div v-for="(v, idx) in variables" :key="idx" class="start-variable-item">
                  <a-input
                    v-model:value="v.name"
                    placeholder="变量名"
                    size="small"
                    @change="markDirty"
                  />
                  <a-input
                    v-model:value="v.default"
                    placeholder="默认值"
                    size="small"
                    @change="markDirty"
                  />
                  <a-button size="small" type="text" danger @click="removeVariable(idx)">
                    <template #icon><Trash2 :size="12" /></template>
                  </a-button>
                </div>
                <div v-if="variables.length === 0" class="empty-variables">
                  暂无输入变量
                </div>
                <a-button size="small" block @click="addVariable">
                  <template #icon><Plus :size="12" /></template>
                  添加变量
                </a-button>
              </template>

              <!-- 结束步骤：编辑最终输出 -->
              <template v-else-if="selectedStep.type === 'end'">
                <a-form-item label="名称">
                  <a-input v-model:value="selectedStep.name" @change="onNameChange" />
                </a-form-item>
                <a-form-item label="输出格式">
                  <a-select
                    v-model:value="selectedStep.format"
                    placeholder="Markdown（默认）"
                    allowClear
                    @change="markDirty"
                  >
                    <a-select-option value="markdown">Markdown</a-select-option>
                    <a-select-option value="text">纯文本</a-select-option>
                    <a-select-option value="json">JSON</a-select-option>
                  </a-select>
                </a-form-item>
                <a-form-item label="输出模板">
                  <a-textarea
                    v-model:value="selectedStep.template"
                    :rows="6"
                    placeholder="最终输出模板，可使用 {{变量名}}；留空则汇总上游 output_key 结果"
                    @change="markDirty"
                  />
                </a-form-item>
              </template>

              <!-- 业务步骤 -->
              <template v-else>
                <a-form-item label="名称">
                  <a-input v-model:value="selectedStep.name" @change="onNameChange" />
                </a-form-item>
                <a-form-item label="类型">
                  <a-select v-model:value="selectedStep.type" @change="onTypeChange">
                    <a-select-option v-for="(desc, type) in stepTypes" :key="type" :value="type">
                      {{ desc }}
                    </a-select-option>
                  </a-select>
                </a-form-item>

                <!-- LLM 步骤特有字段 -->
                <template v-if="selectedStep.type === 'llm'">
                  <a-form-item label="Prompt">
                    <a-textarea
                      v-model:value="selectedStep.prompt"
                      :rows="6"
                      placeholder="输入 prompt，可使用 {{变量名}} 引用上下文变量"
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="引用 Agent（可选）">
                    <a-input
                      v-model:value="selectedStep.agent_slug"
                      placeholder="已有 agent 的 slug，留空使用默认模型"
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="模型规格（可选）">
                    <a-input
                      v-model:value="selectedStep.model_spec"
                      placeholder="如 deepseek/deepseek-chat；留空用系统默认"
                      @change="markDirty"
                    />
                  </a-form-item>
                </template>

                <!-- Tool 步骤特有字段 -->
                <template v-if="selectedStep.type === 'tool'">
                  <a-form-item label="工具名称">
                    <a-input
                      v-model:value="selectedStep.tool_name"
                      placeholder="工具 slug"
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="工具参数 (JSON)">
                    <a-textarea
                      v-model:value="toolParamsText"
                      :rows="4"
                      placeholder='{"key": "value"}'
                      @change="markDirty"
                    />
                  </a-form-item>
                </template>

                <!-- HTTP 步骤特有字段 -->
                <template v-if="selectedStep.type === 'http'">
                  <a-form-item label="URL">
                    <a-input v-model:value="selectedStep.url" placeholder="https://..." @change="markDirty" />
                  </a-form-item>
                  <a-form-item label="Method">
                    <a-select v-model:value="selectedStep.method" @change="markDirty">
                      <a-select-option value="GET">GET</a-select-option>
                      <a-select-option value="POST">POST</a-select-option>
                      <a-select-option value="PUT">PUT</a-select-option>
                      <a-select-option value="DELETE">DELETE</a-select-option>
                    </a-select>
                  </a-form-item>
                  <a-form-item label="请求头 (JSON)">
                    <a-textarea
                      v-model:value="httpHeadersText"
                      :rows="3"
                      placeholder='{"Content-Type": "application/json", "Authorization": "Bearer ..."}'
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="请求体 (JSON)">
                    <a-textarea
                      v-model:value="httpBodyText"
                      :rows="4"
                      placeholder='{"key": "{{变量名}}"}'
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="超时（秒）">
                    <a-input-number
                      v-model:value="selectedStep.timeout"
                      :min="1"
                      :max="300"
                      placeholder="30"
                      @change="markDirty"
                    />
                  </a-form-item>
                </template>

                <!-- Condition 步骤特有字段 -->
                <template v-if="selectedStep.type === 'condition'">
                  <a-form-item label="条件表达式">
                    <a-input
                      v-model:value="selectedStep.condition"
                      placeholder="{{变量}} == 'value'"
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="为真时走步骤">
                    <a-select
                      v-model:value="selectedStep.then_step"
                      placeholder="选择条件为真时执行的步骤"
                      allowClear
                      @change="markDirty"
                    >
                      <a-select-option
                        v-for="s in steps.filter(s => s.type !== 'start' && s.type !== 'end' && s.id !== selectedStep.id)"
                        :key="s.id"
                        :value="s.id"
                      >
                        {{ s.name || s.id }}
                      </a-select-option>
                    </a-select>
                  </a-form-item>
                  <a-form-item label="为假时走步骤">
                    <a-select
                      v-model:value="selectedStep.else_step"
                      placeholder="选择条件为假时执行的步骤"
                      allowClear
                      @change="markDirty"
                    >
                      <a-select-option
                        v-for="s in steps.filter(s => s.type !== 'start' && s.type !== 'end' && s.id !== selectedStep.id)"
                        :key="s.id"
                        :value="s.id"
                      >
                        {{ s.name || s.id }}
                      </a-select-option>
                    </a-select>
                  </a-form-item>
                </template>

                <!-- Approval 步骤特有字段 -->
                <template v-if="selectedStep.type === 'approval'">
                  <a-form-item label="审批提示">
                    <a-textarea
                      v-model:value="selectedStep.approval_prompt"
                      :rows="3"
                      placeholder="展示给审批人的提示信息"
                      @change="markDirty"
                    />
                  </a-form-item>
                </template>

                <!-- Script 步骤特有字段 -->
                <template v-if="selectedStep.type === 'script'">
                  <a-form-item label="语言">
                    <a-select v-model:value="selectedStep.language" @change="markDirty" disabled>
                      <a-select-option value="python">Python</a-select-option>
                    </a-select>
                  </a-form-item>
                  <a-form-item label="脚本代码">
                    <a-textarea
                      v-model:value="selectedStep.code"
                      :rows="10"
                      placeholder="# 可用 input_data 访问上下文变量&#10;result = input_data.get('key', '')"
                      class="code-editor"
                      @change="markDirty"
                    />
                  </a-form-item>
                </template>

                <!-- Output 步骤特有字段 -->
                <template v-if="selectedStep.type === 'output'">
                  <a-form-item label="输出格式">
                    <a-select v-model:value="selectedStep.format" @change="markDirty">
                      <a-select-option value="markdown">Markdown</a-select-option>
                      <a-select-option value="html">HTML</a-select-option>
                      <a-select-option value="json">JSON</a-select-option>
                    </a-select>
                  </a-form-item>
                  <a-form-item label="模板">
                    <a-textarea
                      v-model:value="selectedStep.template"
                      :rows="6"
                      placeholder="输出模板，可使用 {{变量名}}"
                      @change="markDirty"
                    />
                  </a-form-item>
                  <a-form-item label="交付渠道">
                    <a-select
                      v-model:value="selectedStep.delivery"
                      mode="multiple"
                      placeholder="选择交付方式（可多选）"
                      allowClear
                      @change="markDirty"
                    >
                      <a-select-option value="page">页面展示</a-select-option>
                      <a-select-option value="dingtalk">钉钉</a-select-option>
                      <a-select-option value="wecom">企业微信</a-select-option>
                    </a-select>
                  </a-form-item>
                </template>

                <!-- 输出变量名（所有业务步骤通用） -->
                <a-divider>输出</a-divider>
                <a-form-item label="输出变量名 (output_key)">
                  <a-input
                    v-model:value="selectedStep.output_key"
                    placeholder="将步骤输出写入此变量名，供下游步骤引用"
                    @change="markDirty"
                  />
                </a-form-item>

                <!-- 循环配置（仅业务步骤；start/end 是边界步骤不参与循环） -->
                <template v-if="!isBoundaryNode(selectedStep.id)">
                  <a-divider>循环配置（可选）</a-divider>
                  <a-form-item label="循环回到步骤">
                    <a-select
                      :value="selectedStep.loop?.back_to"
                      placeholder="选择要回到的步骤"
                      allowClear
                      @change="(val) => { selectedStep.loop = selectedStep.loop || {}; selectedStep.loop.back_to = val; markDirty() }"
                    >
                      <a-select-option
                        v-for="s in steps.filter(s => s.id !== selectedStep.id && !isBoundaryNode(s.id))"
                        :key="s.id"
                        :value="s.id"
                      >
                        {{ s.name || s.id }}
                      </a-select-option>
                    </a-select>
                  </a-form-item>
                  <a-form-item label="最大迭代次数">
                    <a-input-number
                      :value="selectedStep.loop?.max_iterations"
                      :min="1"
                      :max="100"
                      @change="(val) => { selectedStep.loop = selectedStep.loop || {}; selectedStep.loop.max_iterations = val; markDirty() }"
                    />
                  </a-form-item>
                  <a-form-item label="退出条件">
                    <a-input
                      :value="selectedStep.loop?.exit_condition"
                      placeholder="{{变量}} contains 'done'"
                      @change="(e) => { selectedStep.loop = selectedStep.loop || {}; selectedStep.loop.exit_condition = e.target.value; markDirty() }"
                    />
                  </a-form-item>
                </template>
              </template>
            </a-form>
          </div>
        </div>
      </div>

      <!-- 底部：节点工具栏 -->
      <div class="node-palette-bar">
        <div
          v-for="(desc, type) in stepTypes"
          :key="type"
          class="palette-bar-item"
          draggable="true"
          @dragstart="(e) => onDragStart(e, type)"
        >
          <div class="palette-bar-icon">
            <component :is="getStepIcon(type)" :size="16" :stroke-width="1.5" />
          </div>
          <span class="palette-bar-label">{{ desc }}</span>
        </div>
      </div>
    </div>

    <!-- 运行弹窗 -->
    <a-modal
      v-model:open="showRunModal"
      title="运行工作流"
      @ok="handleRun"
      :confirmLoading="running"
    >
      <a-form layout="vertical">
        <a-form-item v-for="v in variables" :key="v.name" :label="v.name">
          <a-input v-model:value="runInputs[v.name]" :placeholder="v.default || ''" />
        </a-form-item>
        <div v-if="variables.length === 0">此工作流无输入变量</div>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { ArrowLeft, Play, Save, Plus, Trash2, Inbox, Settings, X, ChevronLeft, ChevronRight } from '@lucide/vue'
import { Bot, Wrench, Globe, GitBranch, UserCheck, Code2, Send } from '@lucide/vue'
import WorkflowNode from '@/components/workflow/WorkflowNode.vue'
import WorkflowEdge from '@/components/workflow/WorkflowEdge.vue'
import { workflowApi } from '@/apis/workflow_api'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const route = useRoute()
const router = useRouter()

// 固定的开始/结束步骤：真实 step（type: start/end），负责输入与输出边界，
// id 固定且唯一，画布中不可删除，由首次加载迁移逻辑补齐
const START_NODE_ID = 'start'
const END_NODE_ID = 'end'
const isBoundaryNode = (id) => id === START_NODE_ID || id === END_NODE_ID

// 状态
const workflow = ref(null)
const saving = ref(false)
const running = ref(false)
const isDirty = ref(false)
const selectedStepId = ref(null)
const showRunModal = ref(false)
const runInputs = ref({})
const showSettings = ref(false)
const stepPanelCollapsed = ref(false)

// Vue Flow 元素
const flowElements = ref([])
// useVueFlow 依赖 inject，必须在 setup 顶层同步调用，不能放在 onMounted 中
const { project, fitView, onNodesInitialized, addEdges } = useVueFlow()

// 节点尺寸测量完成后自适应视口一次，保证打开页面时整个流程可见
let hasFitted = false
onNodesInitialized(() => {
  if (hasFitted) return
  hasFitted = true
  fitView({ padding: 0.15, duration: 200 })
})

// 步骤类型
const stepTypes = {
  llm: '大模型',
  tool: '工具调用',
  http: 'HTTP 请求',
  condition: '条件分支',
  approval: '人工审批',
  script: '脚本执行',
  output: '输出'
}

const stepIcons = {
  llm: Bot,
  tool: Wrench,
  http: Globe,
  condition: GitBranch,
  approval: UserCheck,
  script: Code2,
  output: Send
}

const getStepIcon = (type) => stepIcons[type] || Bot

// 按步骤类型返回默认字段（确保 Vue 响应式能追踪到后续赋值）
function getStepDefaults(type) {
  switch (type) {
    case 'llm': return { prompt: '', agent_slug: '', model_spec: '' }
    case 'tool': return { tool_name: '', tool_params: {} }
    case 'http': return { url: '', method: 'GET', headers: {}, body: null, timeout: 30 }
    case 'condition': return { condition: '', then_step: null, else_step: null }
    case 'approval': return { approval_prompt: '' }
    case 'script': return { code: '', language: 'python' }
    case 'output': return { format: 'markdown', template: '', delivery: [] }
    default: return {}
  }
}

// 计算属性
const steps = computed(() => workflow.value?.definition?.steps || [])
const variables = computed(() => workflow.value?.definition?.variables || [])
const concurrency = computed({
  get: () => workflow.value?.definition?.concurrency || 4,
  set: (val) => {
    if (workflow.value) {
      workflow.value.definition.concurrency = val
    }
  }
})

const flowNodes = computed(() => flowElements.value.filter(e => !e.source && !e.target))
const flowEdges = computed(() => flowElements.value.filter(e => e.source && e.target))
// 空画布提示以业务步骤为准：start/end 边界步骤不算内容
const businessNodeCount = computed(() => flowNodes.value.filter(n => !isBoundaryNode(n.id)).length)

const selectedStep = computed(() => {
  if (!selectedStepId.value) return null
  return steps.value.find(s => s.id === selectedStepId.value)
})

const toolParamsText = computed({
  get: () => {
    if (!selectedStep.value?.tool_params) return '{}'
    return JSON.stringify(selectedStep.value.tool_params, null, 2)
  },
  set: (val) => {
    if (selectedStep.value) {
      try {
        selectedStep.value.tool_params = JSON.parse(val)
      } catch {
        // 忽略解析错误
      }
    }
  }
})

const httpHeadersText = computed({
  get: () => {
    const h = selectedStep.value?.headers
    if (!h || (typeof h === 'object' && Object.keys(h).length === 0)) return ''
    return typeof h === 'string' ? h : JSON.stringify(h, null, 2)
  },
  set: (val) => {
    if (selectedStep.value) {
      try {
        selectedStep.value.headers = val ? JSON.parse(val) : {}
      } catch { /* 忽略解析错误 */ }
    }
  }
})

const httpBodyText = computed({
  get: () => {
    const b = selectedStep.value?.body
    if (b === undefined || b === null) return ''
    return typeof b === 'string' ? b : JSON.stringify(b, null, 2)
  },
  set: (val) => {
    if (selectedStep.value) {
      try {
        selectedStep.value.body = val ? JSON.parse(val) : null
      } catch { /* 忽略解析错误 */ }
    }
  }
})

// 将 steps 转换为 Vue Flow 节点和边（仅初始加载时调用）
function syncFlowFromSteps() {
  if (!workflow.value?.definition?.steps) return

  const stepList = workflow.value.definition.steps

  // 按 depends_on 拓扑分层：同层并排展示并发，跨层从左到右推进
  // start 固定为最左层（level -1），end 随其依赖自然落到最右
  const stepMap = new Map(stepList.map(s => [s.id, s]))
  const levels = {}
  const getLevel = (stepId, visited = new Set()) => {
    if (levels[stepId] !== undefined) return levels[stepId]
    if (visited.has(stepId)) return 0
    visited.add(stepId)
    const step = stepMap.get(stepId)
    if (step && step.type === 'start') {
      levels[stepId] = -1
      return -1
    }
    if (!step || !step.depends_on || step.depends_on.length === 0) {
      levels[stepId] = 0
      return 0
    }
    const level = Math.max(...step.depends_on.map(depId => getLevel(depId, visited))) + 1
    levels[stepId] = level
    return level
  }
  stepList.forEach(s => getLevel(s.id))

  const columnCount = {}
  const nodes = stepList.map(step => {
    const level = levels[step.id] ?? 0
    const row = columnCount[level] ?? 0
    columnCount[level] = row + 1
    return {
      id: step.id,
      type: 'workflow',
      // 优先使用已保存的位置，否则按拓扑层级布局
      position: step.position || { x: 60 + level * 240, y: 60 + row * 130 },
      deletable: !isBoundaryNode(step.id),
      data: {
        label: step.name || step.id,
        stepType: step.type,
        selected: selectedStepId.value === step.id,
        stepId: step.id
      }
    }
  })

  const edges = []
  stepList.forEach(step => {
    if (step.depends_on && step.depends_on.length > 0) {
      step.depends_on.forEach(depId => {
        edges.push({
          id: `e-${depId}-${step.id}`,
          source: depId,
          target: step.id,
          type: 'workflow'
        })
      })
    }
  })

  flowElements.value = [...nodes, ...edges]
}

// 将 Vue Flow 节点和边转换回 steps
// 连线即真实 depends_on 数据：start→业务 与 业务→end 的边分别落在
// 业务步骤的 depends_on 与 end 的 depends_on 中，保存后持久化
function syncStepsFromFlow() {
  if (!workflow.value) return

  const nodes = flowNodes.value
  const edges = flowEdges.value

  // 更新步骤列表（位置随拖动写入 step，保存时一并持久化）
  const newSteps = nodes.map(node => {
    const existingStep = steps.value.find(s => s.id === node.id)
    return {
      ...(existingStep || { id: node.id, type: 'llm', name: node.data?.label || node.id }),
      id: node.id,
      type: node.data?.stepType || existingStep?.type || 'llm',
      name: node.data?.label || existingStep?.name || node.id,
      position: { x: node.position?.x ?? 0, y: node.position?.y ?? 0 },
      depends_on: edges
        .filter(e => e.target === node.id)
        .map(e => e.source)
    }
  })

  workflow.value.definition.steps = newSteps
}

// 画布 → steps 单向同步；不允许反向重建 flowElements，
// 否则双向 watch 会无限递归，且会重置用户手动摆放的节点位置
watch(flowElements, () => {
  syncStepsFromFlow()
}, { deep: true })

// 节点点击（start/end 是真实边界步骤，同样打开编辑面板配置输入/输出）
const onNodeClick = (event) => {
  const nodeId = event.node.id
  selectedStepId.value = nodeId
  stepPanelCollapsed.value = false
  // 更新选中状态
  flowElements.value.forEach(el => {
    if (!el.source && !el.target) {
      el.data = { ...el.data, selected: el.id === nodeId }
    }
  })
}

// 连线（拒绝自环、重复边，以及流入开始/流出结束的非法方向）
const onConnect = (params) => {
  if (params.source === params.target) return
  if (params.target === START_NODE_ID || params.source === END_NODE_ID) return
  const duplicated = flowEdges.value.some(
    e => e.source === params.source && e.target === params.target
  )
  if (duplicated) return
  // 必须走 addEdges：自动生成 edge id 并更新内部 state，手动 push 数组会因缺 id 被丢弃
  addEdges([{ ...params, type: 'workflow' }])
  markDirty()
}

// 节点位置变化
const onNodesChange = (changes) => {
  changes.forEach(change => {
    if (change.type === 'remove') {
      const nodeId = change.id
      // 同时删除相关边
      flowElements.value = flowElements.value.filter(
        e => (e.source && e.source !== nodeId && e.target !== nodeId) || (!e.source && !e.target && e.id !== nodeId)
      )
      if (selectedStepId.value === nodeId) {
        selectedStepId.value = null
      }
      markDirty()
    }
    // 拖动结束时标记（dragging=false 的是每次拖动的最终一条 change）
    if (change.type === 'position' && change.dragging === false) {
      markDirty()
    }
  })
}

const onEdgesChange = (changes) => {
  changes.forEach(change => {
    if (change.type === 'remove') {
      markDirty()
    }
  })
}

// 拖拽添加节点
const onDragStart = (event, type) => {
  event.dataTransfer.setData('application/vue-flow-node-type', type)
  event.dataTransfer.effectAllowed = 'move'
}

const onDragOver = (event) => {
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
}

const onDrop = (event) => {
  event.preventDefault()

  const type = event.dataTransfer.getData('application/vue-flow-node-type')
  if (!type) return

  const position = project({
    x: event.clientX - event.currentTarget.getBoundingClientRect().left,
    y: event.clientY - event.currentTarget.getBoundingClientRect().top
  })

  const id = `step_${Date.now()}`
  const newNode = {
    id,
    type: 'workflow',
    position,
    data: {
      label: `${stepTypes[type]} ${steps.value.length + 1}`,
      stepType: type,
      selected: false,
      stepId: id
    }
  }

  flowElements.value = [...flowElements.value, newNode]

  // 同时添加到 steps，按类型初始化默认字段
  const newStep = {
    id,
    type,
    name: newNode.data.label,
    depends_on: [],
    ...getStepDefaults(type)
  }
  workflow.value.definition.steps.push(newStep)

  selectedStepId.value = id
  markDirty()
}

// 类型变更
const onTypeChange = (newType) => {
  // 更新节点图标
  const node = flowElements.value.find(e => e.id === selectedStepId.value && !e.source && !e.target)
  if (node) {
    node.data = { ...node.data, stepType: newType }
  }
  markDirty()
}

// 名称编辑同步到画布节点（画布是主编辑入口，表单只做定点回写）
const onNameChange = () => {
  const node = flowElements.value.find(e => e.id === selectedStepId.value && !e.source && !e.target)
  if (node) {
    node.data = { ...node.data, label: selectedStep.value?.name }
  }
  markDirty()
}

// 方法
const goBack = () => {
  if (isDirty.value) {
    if (!confirm('有未保存的更改，确定离开吗？')) return
  }
  router.push('/workflows')
}

const markDirty = () => {
  isDirty.value = true
}

const loadWorkflow = async () => {
  const id = route.params.id
  try {
    const res = await workflowApi.get(id)
    workflow.value = res.data || res
    if (!workflow.value.definition) {
      workflow.value.definition = { steps: [], variables: [], concurrency: 4 }
    }
    if (!workflow.value.definition.steps) {
      workflow.value.definition.steps = []
    }
    if (!workflow.value.definition.variables) {
      workflow.value.definition.variables = []
    }
    // 旧版定义补齐 start/end 边界步骤并迁移连线；变化后提示保存固化
    if (ensureTerminalSteps()) {
      markDirty()
    }
    syncFlowFromSteps()
  } catch (error) {
    console.error('加载工作流失败:', error)
    message.error('加载工作流失败')
  }
}

// 旧版定义没有 start/end 边界步骤：补齐节点并把入口/出口步骤接入。
// 只对完全无边界步骤的旧数据一次性迁移（legacy），之后连线完全由用户管理
function ensureTerminalSteps() {
  const stepList = workflow.value.definition.steps
  const hasStart = stepList.some(s => s.type === 'start')
  const hasEnd = stepList.some(s => s.type === 'end')
  if (hasStart && hasEnd) return false

  let changed = false
  if (!hasStart) {
    stepList.unshift({ id: START_NODE_ID, type: 'start', name: '开始', depends_on: [] })
    changed = true
  }
  if (!hasEnd) {
    stepList.push({ id: END_NODE_ID, type: 'end', name: '结束', depends_on: [] })
    changed = true
  }

  if (!hasStart && !hasEnd) {
    // 入度0业务步骤挂到 start 之后，出度0业务步骤汇入 end
    const businessSteps = stepList.filter(s => s.type !== 'start' && s.type !== 'end')
    const hasSuccessor = new Set()
    businessSteps.forEach(s => (s.depends_on || []).forEach(d => hasSuccessor.add(d)))
    businessSteps.forEach(s => {
      if (!s.depends_on || s.depends_on.length === 0) {
        s.depends_on = [START_NODE_ID]
      }
    })
    stepList.find(s => s.type === 'end').depends_on = businessSteps
      .filter(s => !hasSuccessor.has(s.id))
      .map(s => s.id)
  }
  return changed
}

const saveWorkflow = async () => {
  if (!workflow.value) return
  saving.value = true
  try {
    await workflowApi.update(workflow.value.id, {
      name: workflow.value.name,
      definition: workflow.value.definition
    })
    message.success('保存成功')
    isDirty.value = false
  } catch (error) {
    console.error('保存失败:', error)
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

const addVariable = () => {
  workflow.value.definition.variables.push({ name: '', default: '' })
  markDirty()
}

const removeVariable = (idx) => {
  workflow.value.definition.variables.splice(idx, 1)
  markDirty()
}

const confirmRemoveStep = (stepId) => {
  if (isBoundaryNode(stepId)) return
  Modal.confirm({
    title: '确认删除',
    content: '确定要删除这个步骤吗？删除后不可恢复。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => removeStep(stepId),
  })
}

const removeStep = (stepId) => {
  // start/end 是流程边界步骤，不允许删除
  if (isBoundaryNode(stepId)) return

  // 从 flow 中删除节点和相关边
  flowElements.value = flowElements.value.filter(
    e => (e.source && e.source !== stepId && e.target !== stepId) || (!e.source && !e.target && e.id !== stepId)
  )

  // 从 steps 中删除
  const idx = steps.value.findIndex(s => s.id === stepId)
  if (idx >= 0) {
    workflow.value.definition.steps.splice(idx, 1)
  }

  if (selectedStepId.value === stepId) {
    selectedStepId.value = null
  }
  markDirty()
}

const getMiniMapColor = (node) => {
  const colors = {
    start: '#22c55e',
    llm: '#14b8a6',
    tool: '#f59e0b',
    http: '#3b82f6',
    condition: '#ec4899',
    approval: '#8b5cf6',
    script: '#6b7280',
    output: '#10b981',
    end: '#9ca3af'
  }
  return colors[node.data?.stepType] || '#14b8a6'
}

const handleRun = async () => {
  running.value = true
  try {
    await workflowApi.run(workflow.value.id, runInputs.value)
    message.success('工作流已提交运行')
    showRunModal.value = false
  } catch (error) {
    console.error('运行失败:', error)
    message.error('运行失败')
  } finally {
    running.value = false
  }
}

onMounted(() => {
  loadWorkflow()
})
</script>

<style scoped>
.workflow-editor {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--gray-0);
}

.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--gray-150);
  background: var(--gray-25);
  flex-shrink: 0;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toolbar-left :deep(.ant-btn),
.toolbar-right :deep(.ant-btn) {
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
}

.toolbar-left :deep(.ant-btn-icon),
.toolbar-right :deep(.ant-btn-icon) {
  display: inline-flex;
  align-items: center;
  margin-right: 6px;
  vertical-align: middle;
}

.workflow-name-input {
  width: 240px;
  font-size: 16px;
  font-weight: 600;
}

.editor-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  position: relative;
}

/* 画布占满剩余空间 */
.flow-canvas {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: #fafbfc;
  min-height: 0;
}

.flow-canvas :deep(.vue-flow) {
  width: 100%;
  height: 100%;
}

.canvas-empty-hint {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: var(--gray-400);
  pointer-events: none;
  z-index: 1;
}

.canvas-empty-hint p {
  margin-top: 12px;
  font-size: 14px;
}

/* 浮动：全局设置按钮 */
.floating-settings-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 20;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  cursor: pointer;
  color: var(--gray-600);
  transition: all 0.15s;
  box-shadow: 0 1px 4px var(--shadow-1);
}

.floating-settings-btn:hover {
  color: var(--main-600);
  border-color: var(--main-400);
  box-shadow: 0 2px 8px var(--shadow-1);
}

/* 浮动：全局设置面板 */
.floating-settings-panel {
  position: absolute;
  top: 56px;
  left: 12px;
  z-index: 30;
  width: 240px;
  background: #fff;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  box-shadow: 0 4px 16px var(--shadow-2);
  overflow: hidden;
}

.settings-content {
  padding: 12px 16px 16px;
}

.settings-row {
  margin-bottom: 12px;
}

.settings-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-700);
  margin-bottom: 6px;
}

/* 浮动：步骤编辑抽屉 */
.step-drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 10;
  width: 380px;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-left: 1px solid var(--gray-150);
  box-shadow: -2px 0 12px var(--shadow-1);
  transition: width 0.2s ease;
  overflow: hidden;
}

.step-drawer.collapsed {
  width: 44px;
}

.step-drawer.collapsed .step-form {
  display: none;
}

.step-drawer.collapsed .panel-header span {
  display: none;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--gray-150);
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-700);
  flex-shrink: 0;
}

.panel-header-left {
  display: flex;
  align-items: center;
  gap: 4px;
}

.panel-header-left span {
  display: inline;
}

.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.step-form {
  flex: 1;
  overflow: auto;
  padding: 16px;
}

.step-form :deep(.ant-form-item) {
  margin-bottom: 14px;
}

.step-form :deep(.ant-form-item-label > label) {
  font-size: 13px;
  font-weight: 500;
}

.step-form :deep(.ant-divider) {
  margin: 16px 0 12px;
  font-size: 12px;
  color: var(--gray-400);
}

/* 底部节点工具栏 */
.node-palette-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--gray-25);
  border-top: 1px solid var(--gray-150);
  flex-shrink: 0;
  overflow-x: auto;
}

.palette-bar-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #fff;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  cursor: grab;
  transition: all 0.15s;
  user-select: none;
  white-space: nowrap;
  flex-shrink: 0;
}

.palette-bar-item:hover {
  border-color: var(--main-400);
  box-shadow: 0 2px 6px var(--shadow-1);
  transform: translateY(-1px);
}

.palette-bar-item:active {
  cursor: grabbing;
}

.palette-bar-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 5px;
  background: var(--main-50);
  color: var(--main-600);
  flex-shrink: 0;
}

.palette-bar-label {
  font-size: 12px;
  color: var(--gray-700);
}

/* Start 节点面板中的变量行 */
.start-variable-item {
  display: flex;
  gap: 4px;
  margin-bottom: 6px;
  align-items: center;
}

.empty-variables {
  text-align: center;
  color: var(--gray-400);
  font-size: 12px;
  padding: 16px 0;
}

.panel-hint {
  font-size: 11px;
  color: var(--gray-400);
  line-height: 1.5;
}

/* 脚本代码编辑区 */
.code-editor :deep(textarea) {
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.5;
  tab-size: 4;
}
</style>
