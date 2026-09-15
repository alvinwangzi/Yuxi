<template>
  <BaseEdge :id="id" :path="bezier.path" :style="edgeStyle" />
  <EdgeLabelRenderer>
    <div
      v-if="branchLabel"
      class="workflow-edge-label"
      :style="{
        transform: `translate(-50%, -50%) translate(${labelPos.x}px, ${labelPos.y}px)`,
        color: branchColor,
        borderColor: branchColor,
        background: branchBg
      }"
    >
      {{ branchLabel }}
    </div>
    <button
      v-if="deletable"
      class="workflow-edge-delete"
      :style="{ transform: `translate(-50%, -50%) translate(${bezier.labelX}px, ${bezier.labelY}px)` }"
      title="删除连线"
      @click.stop="onDelete"
    >
      <X :size="10" :stroke-width="2.5" />
    </button>
  </EdgeLabelRenderer>
</template>

<script setup>
import { computed } from 'vue'
import { BaseEdge, EdgeLabelRenderer, getBezierPath, useVueFlow } from '@vue-flow/core'
import { X } from '@lucide/vue'

// 分支颜色调色板（与 WorkflowNode.vue / WorkflowEditorView.vue 保持一致）
const BRANCH_COLORS = [
  '#10b981', '#f59e0b', '#3b82f6', '#ef4444',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'
]

// 自定义连线：贝塞尔圆弧避免折线在垂直段视觉重叠；中点常驻删除按钮解决“连错无法删”
const props = defineProps({
  id: { type: String, required: true },
  sourceX: { type: Number, required: true },
  sourceY: { type: Number, required: true },
  targetX: { type: Number, required: true },
  targetY: { type: Number, required: true },
  sourcePosition: { type: String, default: 'right' },
  targetPosition: { type: String, default: 'left' },
  selected: { type: Boolean, default: false },
  // 来源 handle id：条件节点连线时为分支 id（如 "b1"、"b2"）
  sourceHandle: { type: String, default: undefined },
  // 派生的 Start/End 锚点连线不可删除（由依赖关系唯一决定）
  deletable: { type: Boolean, default: true }
})

const { removeEdges, getNodes } = useVueFlow()

// 必须保持响应式：节点拖动时 sourceX/Y 会持续变化
const bezier = computed(() => {
  const [path, labelX, labelY] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition
  })
  return { path, labelX, labelY }
})

const edgeStyle = computed(() => ({
  stroke: props.selected ? '#0d9488' : (branchColor.value || '#14b8a6'),
  strokeWidth: props.selected ? 2.5 : 2
}))

// 条件分支连线：从源节点的 branches 数据动态解析标签和颜色
const sourceBranch = computed(() => {
  if (!props.sourceHandle) return null
  const sourceNode = getNodes.value.find(n => n.id === props.source)
  const branches = sourceNode?.data?.branches
  if (!branches) return null
  return branches.find(b => b.id === props.sourceHandle) || null
})

const sourceBranchIndex = computed(() => {
  if (!sourceBranch.value) return -1
  const sourceNode = getNodes.value.find(n => n.id === props.source)
  const branches = sourceNode?.data?.branches || []
  return branches.indexOf(sourceBranch.value)
})

const branchLabel = computed(() => sourceBranch.value?.label || '')

const branchColor = computed(() => {
  const idx = sourceBranchIndex.value
  return idx >= 0 ? BRANCH_COLORS[idx % BRANCH_COLORS.length] : ''
})

const branchBg = computed(() => {
  const idx = sourceBranchIndex.value
  if (idx < 0) return '#fff'
  const hex = BRANCH_COLORS[idx % BRANCH_COLORS.length]
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, 0.08)`
})

// 分支标签放在连线 1/4 处（靠近源端），避免与中点删除按钮重叠
const labelPos = computed(() => {
  const [,, lx, ly] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
    curvature: 0.25
  })
  return { x: lx, y: ly }
})

// removeEdges 内部会派发 edgesChange(remove)，编辑器据此 markDirty 并同步 steps
const onDelete = () => {
  removeEdges([props.id])
}
</script>

<style scoped>
.workflow-edge-label {
  position: absolute;
  z-index: 10;
  font-size: 10px;
  font-weight: 600;
  pointer-events: none;
  user-select: none;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid;
  line-height: 1.4;
}

.workflow-edge-delete {
  position: absolute;
  z-index: 10;
  width: 16px;
  height: 16px;
  padding: 0;
  border-radius: 50%;
  border: 1.5px solid #14b8a6;
  background: #fff;
  color: #14b8a6;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  pointer-events: all;
  opacity: 0.45;
  transition: opacity 0.15s, border-color 0.15s;
}

.workflow-edge-delete:hover {
  opacity: 1;
  border-color: #dc2626;
  color: #dc2626;
}
</style>
