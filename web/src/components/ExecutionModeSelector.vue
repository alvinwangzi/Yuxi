<template>
  <a-dropdown
    v-model:open="open"
    :trigger="['click']"
    placement="topLeft"
    overlay-class-name="execution-mode-dropdown-overlay"
  >
    <button
      ref="triggerRef"
      type="button"
      class="input-action-btn config-dropdown-trigger"
      :aria-label="currentOption.label"
      aria-haspopup="menu"
      :aria-expanded="open"
    >
      <component
        :is="currentOption.icon"
        :size="16"
        class="config-dropdown-compact-icon"
        aria-hidden="true"
      />
      <span class="hide-text config-dropdown-text">{{ currentOption.label }}</span>
      <ChevronDown :size="15" class="config-dropdown-chevron" />
    </button>

    <template #overlay>
      <div ref="panelRef" class="config-dropdown-panel" role="menu" aria-label="执行模式">
        <button
          v-for="option in options"
          :key="option.value"
          type="button"
          role="menuitemradio"
          :aria-checked="modelValue === option.value"
          class="config-dropdown-item"
          :class="{ selected: modelValue === option.value }"
          @click="selectMode(option.value)"
        >
          <component
            :is="option.icon"
            :size="15"
            class="config-dropdown-item-icon"
          />
          <div class="execution-mode-item-content">
            <span class="config-dropdown-item-label">{{ option.label }}</span>
            <span class="execution-mode-item-desc">{{ option.description }}</span>
          </div>
          <Check v-if="modelValue === option.value" :size="14" class="config-dropdown-item-check" />
        </button>
      </div>
    </template>
  </a-dropdown>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Check, ChevronDown, Gauge, Rabbit, Brain } from '@lucide/vue'
import { useOutsidePointerdown } from '@/composables/useOutsidePointerdown'

const props = defineProps({
  modelValue: { type: String, default: 'balanced' }
})

const emit = defineEmits(['update:modelValue'])
const options = [
  {
    value: 'fast',
    label: '快速',
    description: '简洁作答，适合简单问答',
    icon: Rabbit
  },
  {
    value: 'balanced',
    label: '均衡',
    description: '平衡速度与质量',
    icon: Gauge
  },
  {
    value: 'deep_think',
    label: '深度思考',
    description: '深入分析，适合复杂任务',
    icon: Brain
  }
]

const open = ref(false)
const triggerRef = ref(null)
const panelRef = ref(null)
const currentOption = computed(
  () => options.find((option) => option.value === props.modelValue) || options[1]
)

const selectMode = (mode) => {
  emit('update:modelValue', mode)
  open.value = false
}

useOutsidePointerdown(open, [triggerRef, panelRef])
</script>

<style scoped lang="less">
.config-dropdown-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  max-width: min(180px, calc(100vw - 160px));
  gap: 4px;
}

.config-dropdown-trigger :deep(svg) {
  color: currentColor;
}

.config-dropdown-text {
  min-width: 0;
  overflow: hidden;
  color: currentColor;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.config-dropdown-chevron {
  flex-shrink: 0;
  color: currentColor;
}

.config-dropdown-compact-icon {
  display: none;
  flex-shrink: 0;
}

@container (max-width: 640px) {
  .config-dropdown-trigger {
    width: 30px;
    padding-inline: 0;
  }

  .config-dropdown-compact-icon {
    display: block;
  }

  .config-dropdown-text,
  .config-dropdown-chevron {
    display: none;
  }
}

.execution-mode-item-content {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}

.execution-mode-item-desc {
  font-size: 12px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
