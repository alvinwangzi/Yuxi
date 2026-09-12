<template>
  <BaseEdge :id="id" :path="bezier.path" :style="edgeStyle" />
  <EdgeLabelRenderer>
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

// 自定义连线：贝塞尔圆弧避免折线在垂直段视觉重叠；中点常驻删除按钮解决"连错无法删"
const props = defineProps({
  id: { type: String, required: true },
  sourceX: { type: Number, required: true },
  sourceY: { type: Number, required: true },
  targetX: { type: Number, required: true },
  targetY: { type: Number, required: true },
  sourcePosition: { type: String, default: 'right' },
  targetPosition: { type: String, default: 'left' },
  selected: { type: Boolean, default: false },
  // 派生的 Start/End 锚点连线不可删除（由依赖关系唯一决定）
  deletable: { type: Boolean, default: true }
})

const { removeEdges } = useVueFlow()

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
  stroke: props.selected ? '#0d9488' : '#14b8a6',
  strokeWidth: props.selected ? 2.5 : 2
}))

// removeEdges 内部会派发 edgesChange(remove)，编辑器据此 markDirty 并同步 steps
const onDelete = () => {
  removeEdges([props.id])
}
</script>

<style scoped>
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
