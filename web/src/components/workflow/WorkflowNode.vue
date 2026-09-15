<template>
  <div class="workflow-node" :class="[`node-${data.stepType}`, { selected: data.selected }]">
    <div class="node-header">
      <div class="node-icon">
        <component :is="getIcon(data.stepType)" :size="16" :stroke-width="1.5" />
      </div>
      <div class="node-title">{{ data.label || '未命名' }}</div>
    </div>
    <div class="node-type" v-if="!isTerminal">{{ stepTypeLabels[data.stepType] || data.stepType }}</div>
    <!-- 输入端口（左侧）；开始节点没有入口 -->
    <Handle
      v-if="data.stepType !== 'start'"
      type="target"
      :position="Position.Left"
      class="node-handle node-handle-target"
    />
    <!-- 条件节点：多分支输出端口（动态） -->
    <template v-if="data.stepType === 'condition' && conditionBranches.length > 0">
      <Handle
        v-for="(branch, idx) in conditionBranches"
        :key="branch.id"
        type="source"
        :position="Position.Right"
        :id="branch.id"
        class="node-handle node-handle-source node-handle-branch"
        :style="{
          top: branchTopPosition(idx) + '%',
          borderColor: branchColorFor(idx) + ' !important'
        }"
      >
        <span
          class="branch-handle-label"
          :style="{ color: branchColorFor(idx), background: branchBgFor(idx) }"
        >{{ branch.label }}</span>
      </Handle>
    </template>
    <!-- 条件节点无分支时的占位 -->
    <template v-else-if="data.stepType === 'condition'">
      <Handle
        type="source"
        :position="Position.Right"
        class="node-handle node-handle-source"
      />
    </template>
    <!-- 普通节点：单输出端口（右侧）；结束节点没有出口 -->
    <Handle
      v-else-if="data.stepType !== 'end'"
      type="source"
      :position="Position.Right"
      class="node-handle node-handle-source"
    />
  </div>
</template>

<script setup>
import { Handle, Position } from '@vue-flow/core'
import { Bot, Wrench, Globe, GitBranch, UserCheck, Code2, Send, Play, Flag } from '@lucide/vue'
import { computed } from 'vue'

// 分支颜色调色板（8 色循环）
const BRANCH_COLORS = [
  '#10b981', // emerald
  '#f59e0b', // amber
  '#3b82f6', // blue
  '#ef4444', // red
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#84cc16'  // lime
]

const stepTypeLabels = {
  start: '开始',
  llm: '大模型',
  tool: '工具调用',
  http: 'HTTP 请求',
  condition: '条件分支',
  approval: '人工审批',
  script: '脚本执行',
  output: '输出',
  end: '结束'
}

const iconMap = {
  start: Play,
  llm: Bot,
  tool: Wrench,
  http: Globe,
  condition: GitBranch,
  approval: UserCheck,
  script: Code2,
  output: Send,
  end: Flag
}

const getIcon = (type) => iconMap[type] || Bot

const props = defineProps({
  data: { type: Object, required: true }
})

// 开始/结束节点是固定锚点：隐藏类型副标题，只保留必要端口
const isTerminal = computed(() => ['start', 'end'].includes(props.data?.stepType))

// 条件节点的分支列表（从节点 data 中读取）
const conditionBranches = computed(() => props.data?.branches || [])

// 计算分支 handle 的垂直位置百分比（均匀分布在 15%~85% 之间）
const branchTopPosition = (idx) => {
  const n = conditionBranches.value.length
  if (n <= 1) return 50
  return Math.round(15 + idx * 70 / (n - 1))
}

const branchColorFor = (idx) => BRANCH_COLORS[idx % BRANCH_COLORS.length]

const branchBgFor = (idx) => {
  const hex = BRANCH_COLORS[idx % BRANCH_COLORS.length]
  // 将 hex 转为 rgba 10% 透明度
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, 0.1)`
}
</script>

<style scoped>
.workflow-node {
  background: #fff;
  border: 1.5px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 14px;
  min-width: 140px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  transition: box-shadow 0.15s, border-color 0.15s;
  cursor: grab;
}

.workflow-node:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  border-color: #d1d5db;
}

.workflow-node.selected {
  border-color: #14b8a6;
  box-shadow: 0 0 0 2px rgba(20, 184, 166, 0.15);
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.node-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: #f0fdfa;
  color: #0d9488;
  flex-shrink: 0;
}

.node-title {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.node-type {
  font-size: 11px;
  color: #9ca3af;
  padding-left: 36px;
}

.node-handle {
  width: 10px !important;
  height: 10px !important;
  border: 2px solid #14b8a6 !important;
  background: #fff !important;
  border-radius: 50% !important;
  transition: transform 0.15s;
}

/* 扩大连线感应区域：透明扩展层 + 提升 VueFlow connection-radius 配合 */
.node-handle::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: transparent;
}

.node-handle:hover {
  transform: scale(1.3);
}

.node-handle-target {
  left: -6px !important;
}

.node-handle-source {
  right: -6px !important;
}

/* 条件节点分支端口：垂直分布 + 分支标签 */
.node-handle-branch {
  transition: transform 0.15s;
}

.branch-handle-label {
  position: absolute;
  right: 18px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
  pointer-events: none;
  user-select: none;
  line-height: 1;
  padding: 1px 5px;
  border-radius: 3px;
}

/* 不同类型节点的颜色 */
.node-start, .node-end {
  min-width: 0;
  padding: 8px 18px;
  border-radius: 999px;
}
.node-start { border-color: #86efac; }
.node-end { border-color: #d1d5db; }
.node-llm .node-icon { background: #f0fdfa; color: #0d9488; }
.node-tool .node-icon { background: #fef3c7; color: #d97706; }
.node-http .node-icon { background: #dbeafe; color: #2563eb; }
.node-condition .node-icon { background: #fce7f3; color: #db2777; }
.node-approval .node-icon { background: #ede9fe; color: #7c3aed; }
.node-script .node-icon { background: #f3f4f6; color: #4b5563; }
.node-output .node-icon { background: #ecfdf5; color: #059669; }
.node-start .node-icon { background: #dcfce7; color: #16a34a; }
.node-end .node-icon { background: #f3f4f6; color: #6b7280; }
</style>
