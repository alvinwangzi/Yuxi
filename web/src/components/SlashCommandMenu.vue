<template>
  <div v-if="visible" class="slash-command-menu" role="listbox" aria-label="技能命令">
    <button
      v-for="(skill, index) in filteredSkills"
      :key="skill.slug"
      type="button"
      role="option"
      class="slash-command-item"
      :class="{ selected: index === selectedIndex }"
      @click="selectSkill(skill)"
      @mouseenter="selectedIndex = index"
    >
      <span class="slash-command-item-slug">/{{ skill.slug }}</span>
      <span class="slash-command-item-name">{{ skill.name }}</span>
      <span v-if="skill.description" class="slash-command-item-desc">{{ skill.description }}</span>
    </button>
    <div v-if="!filteredSkills.length" class="slash-command-empty">
      没有匹配的技能
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  skills: { type: Array, default: () => [] },
  filterText: { type: String, default: '' },
  visible: { type: Boolean, default: false }
})

const emit = defineEmits(['select', 'close', 'update:selectedIndex'])

const selectedIndex = ref(0)

const filteredSkills = computed(() => {
  const query = props.filterText.toLowerCase().trim()
  const list = props.skills || []
  if (!query) return list.slice(0, 10)
  return list
    .filter((s) => {
      const slug = (s.slug || '').toLowerCase()
      const name = (s.name || '').toLowerCase()
      const desc = (s.description || '').toLowerCase()
      return slug.includes(query) || name.includes(query) || desc.includes(query)
    })
    .slice(0, 10)
})

watch(() => props.visible, () => {
  if (props.visible) selectedIndex.value = 0
})

watch(() => props.filterText, () => {
  selectedIndex.value = 0
})

const selectSkill = (skill) => {
  emit('select', skill)
}

defineExpose({ selectedIndex, filteredSkills })
</script>

<style scoped lang="less">
.slash-command-menu {
  position: absolute;
  bottom: 100%;
  left: 12px;
  right: 12px;
  max-height: 280px;
  overflow-y: auto;
  background: var(--color-bg-elevated, #fff);
  border: 1px solid var(--color-border-secondary, #e5e5e5);
  border-radius: 10px;
  box-shadow: 0 -4px 16px rgb(0 0 0 / 8%);
  padding: 4px;
  z-index: 100;
  margin-bottom: 4px;
}

.slash-command-item {
  display: flex;
  align-items: baseline;
  width: 100%;
  padding: 8px 10px;
  border: none;
  background: none;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  gap: 8px;
  font-size: 13px;
  color: var(--color-text-primary, #1a1a1a);

  &:hover,
  &.selected {
    background: var(--color-bg-hover, #f5f5f5);
  }
}

.slash-command-item-slug {
  font-family: var(--font-mono, monospace);
  font-weight: 600;
  color: var(--color-primary-600, #1677ff);
  white-space: nowrap;
  flex-shrink: 0;
}

.slash-command-item-name {
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.slash-command-item-desc {
  color: var(--color-text-tertiary, #999);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.slash-command-empty {
  padding: 12px;
  text-align: center;
  color: var(--color-text-tertiary, #999);
  font-size: 13px;
}
</style>
