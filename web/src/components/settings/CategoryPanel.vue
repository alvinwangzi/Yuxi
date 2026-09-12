<template>
  <div class="category-panel">
    <div class="category-list">
      <div
        v-for="(cat, index) in categories"
        :key="cat.id"
        class="category-item"
        :class="{ 'is-dragging': dragIndex === index, 'is-drag-over': dragOverIndex === index }"
        draggable="true"
        @dragstart="onDragStart(index, $event)"
        @dragover.prevent="onDragOver(index)"
        @dragleave="dragOverIndex = null"
        @drop="onDrop(index, $event)"
        @dragend="onDragEnd"
      >
        <span class="drag-handle" aria-hidden="true">≡</span>

        <!-- 编辑模式 -->
        <template v-if="editingIndex === index">
          <input
            ref="labelInputRef"
            v-model="draftLabel"
            class="inline-edit"
            placeholder="名称"
            @keydown.enter="saveEdit(cat)"
            @keydown.esc="cancelEdit"
            @blur="onEditBlur(cat)"
          />
          <input
            ref="slugInputRef"
            v-model="draftSlug"
            class="inline-edit slug-edit"
            placeholder="标识"
            @keydown.enter="saveEdit(cat)"
            @keydown.esc="cancelEdit"
            @blur="onEditBlur(cat)"
          />
        </template>

        <!-- 显示模式 -->
        <template v-else>
          <span class="category-label" @click="startEdit(index, cat)">{{ cat.label }}</span>
          <span class="slug-text" @click="startEdit(index, cat)">{{ cat.slug }}</span>
        </template>

        <div class="order-btns">
          <a-button
            type="text"
            size="small"
            :disabled="index === 0"
            class="order-btn"
            @click="moveByIndex(index, index - 1)"
          >
            ↑
          </a-button>
          <a-button
            type="text"
            size="small"
            :disabled="index === categories.length - 1"
            class="order-btn"
            @click="moveByIndex(index, index + 1)"
          >
            ↓
          </a-button>
        </div>
        <a-popconfirm
          title="确定删除此分类？"
          ok-text="确定"
          cancel-text="取消"
          @confirm="$emit('delete', entityType, cat.id)"
        >
          <a-button type="text" size="small" danger class="delete-btn">×</a-button>
        </a-popconfirm>
      </div>
      <div v-if="categories.length === 0" class="empty-tip">暂无分类，请在下方添加。</div>
    </div>

    <div class="add-row">
      <a-input
        :value="newLabel"
        @update:value="$emit('update:newLabel', $event)"
        placeholder="名称"
        size="small"
        style="width: 140px"
      />
      <a-input
        :value="newSlug"
        @update:value="$emit('update:newSlug', $event)"
        placeholder="标识（英文）"
        size="small"
        style="width: 140px"
      />
      <a-button size="small" type="primary" @click="$emit('add', entityType)">添加</a-button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({
  categories: { type: Array, required: true },
  newSlug: { type: String, default: '' },
  newLabel: { type: String, default: '' },
  entityType: { type: String, required: true }
})

const emit = defineEmits([
  'save-edit',
  'add',
  'delete',
  'reorder',
  'update:newSlug',
  'update:newLabel'
])

// ── 编辑状态（子组件自管理） ──
const editingIndex = ref(-1)
const draftLabel = ref('')
const draftSlug = ref('')
const labelInputRef = ref(null)
const slugInputRef = ref(null)

function startEdit(index, cat) {
  editingIndex.value = index
  draftLabel.value = cat.label
  draftSlug.value = cat.slug
  nextTick(() => {
    labelInputRef.value?.focus?.()
  })
}

function cancelEdit() {
  editingIndex.value = -1
}

function onEditBlur(cat) {
  // 延迟保存，让 ESC/Enter 先处理
  setTimeout(() => {
    if (editingIndex.value >= 0) {
      saveEdit(cat)
    }
  }, 150)
}

function saveEdit(cat) {
  if (editingIndex.value < 0) return
  const label = draftLabel.value.trim()
  const slug = draftSlug.value.trim()
  if (!label || !slug) {
    cancelEdit()
    return
  }
  const changed = label !== cat.label || slug !== cat.slug
  if (changed) {
    emit('save-edit', cat.entity_type, cat.id, { label, slug })
  }
  editingIndex.value = -1
}

// ── 拖动排序 ──
const dragIndex = ref(null)
const dragOverIndex = ref(null)

function onDragStart(index, e) {
  dragIndex.value = index
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(index))
}

function onDragOver(index) {
  if (dragIndex.value === null || dragIndex.value === index) return
  dragOverIndex.value = index
}

function onDrop(targetIndex) {
  if (dragIndex.value === null || dragIndex.value === targetIndex) return
  emit('reorder', props.entityType, dragIndex.value, targetIndex)
}

function onDragEnd() {
  dragIndex.value = null
  dragOverIndex.value = null
}

// ── 按钮排序 ──
function moveByIndex(fromIndex, toIndex) {
  emit('reorder', props.entityType, fromIndex, toIndex)
}
</script>

<style lang="less" scoped>
.category-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.category-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  transition: background 0.2s;

  &:hover {
    background: var(--gray-50);

    .delete-btn {
      opacity: 1;
    }
  }

  &.is-dragging {
    opacity: 0.4;
  }

  &.is-drag-over {
    border-top: 2px solid var(--main-color);
  }
}

.drag-handle {
  cursor: grab;
  color: var(--gray-400, #bbb);
  font-size: 14px;
  user-select: none;
}

.inline-edit {
  flex: 1;
  min-width: 0;
  padding: 2px 6px;
  border: 1px solid var(--gray-300);
  border-radius: 4px;
  font-size: 13px;
  outline: none;
  background: var(--gray-0);
  color: var(--gray-800);

  &:focus {
    border-color: var(--main-color);
    box-shadow: 0 0 0 2px var(--main-10);
  }
}

.slug-edit {
  max-width: 140px;
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 12px;
  color: var(--gray-600);
}

.category-label {
  flex: 1;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
  color: var(--gray-800);

  &:hover {
    background: var(--gray-100);
  }
}

.slug-text {
  cursor: pointer;
  font-size: 12px;
  color: var(--gray-500);
  font-family: 'Monaco', 'Consolas', monospace;
  flex-shrink: 0;
  padding: 2px 4px;
  border-radius: 4px;

  &:hover {
    background: var(--gray-100);
    color: var(--gray-700);
  }
}

.order-btns {
  display: flex;
  gap: 2px;
  align-items: center;

  .order-btn {
    padding: 0 4px;
    font-size: 12px;
    color: var(--gray-600);

    &:hover:not(:disabled) {
      color: var(--main-700);
      background: var(--main-10);
    }

    &:disabled {
      color: var(--gray-300, #ddd);
      cursor: not-allowed;
    }
  }
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
}

.empty-tip {
  padding: 16px 0;
  text-align: center;
  color: var(--gray-500);
  font-size: 13px;
}

.add-row {
  display: flex;
  gap: 8px;
  align-items: center;
  padding-top: 4px;
}
</style>
