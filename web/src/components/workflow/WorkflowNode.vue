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
    <!-- 输出端口（右侧）；结束节点没有出口 -->
    <Handle
      v-if="data.stepType !== 'end'"
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

.node-handle:hover {
  transform: scale(1.3);
}

.node-handle-target {
  left: -6px !important;
}

.node-handle-source {
  right: -6px !important;
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
