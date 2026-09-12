<template>
  <div class="design-settings">
    <!-- 智能体分类 -->
    <div class="category-section">
      <div class="section-title">智能体分类</div>
      <p class="section-desc">管理智能体的分类标签。可通过上移/下移按钮调整显示顺序。</p>
      <div class="category-list">
        <div
          v-for="(cat, index) in agentCategories"
          :key="cat.id"
          class="category-item"
        >
          <span class="drag-handle" aria-hidden="true">≡</span>
          <a-input
            v-if="editingId === cat.id"
            v-model:value="editValue"
            size="small"
            class="edit-input"
            @pressEnter="saveEdit(cat)"
            @blur="saveEdit(cat)"
          />
          <span v-else class="category-label" @click="startEdit(cat)">{{ cat.label }}</span>
          <div class="order-btns">
            <a-button
              type="text"
              size="small"
              :disabled="index === 0"
              class="order-btn"
              @click="handleMoveUp('agent', index)"
            >
              ↑
            </a-button>
            <a-button
              type="text"
              size="small"
              :disabled="index === agentCategories.length - 1"
              class="order-btn"
              @click="handleMoveDown('agent', index)"
            >
              ↓
            </a-button>
          </div>
          <a-popconfirm
            title="确定删除此分类？"
            ok-text="确定"
            cancel-text="取消"
            @confirm="handleDelete('agent', cat.id)"
          >
            <a-button type="text" size="small" danger class="delete-btn">×</a-button>
          </a-popconfirm>
        </div>
      </div>
      <div class="add-row">
        <a-input
          v-model:value="newAgentSlug"
          placeholder="标识（英文）"
          size="small"
          style="width: 120px"
        />
        <a-input
          v-model:value="newAgentLabel"
          placeholder="名称"
          size="small"
          style="width: 120px"
        />
        <a-button size="small" type="primary" @click="handleAdd('agent')">添加</a-button>
      </div>
    </div>

    <!-- 技能分类 -->
    <div class="category-section">
      <div class="section-title">技能分类</div>
      <p class="section-desc">管理技能的分类标签。可通过上移/下移按钮调整显示顺序。</p>
      <div class="category-list">
        <div
          v-for="(cat, index) in skillCategories"
          :key="cat.id"
          class="category-item"
        >
          <span class="drag-handle" aria-hidden="true">≡</span>
          <a-input
            v-if="editingId === cat.id"
            v-model:value="editValue"
            size="small"
            class="edit-input"
            @pressEnter="saveEdit(cat)"
            @blur="saveEdit(cat)"
          />
          <span v-else class="category-label" @click="startEdit(cat)">{{ cat.label }}</span>
          <div class="order-btns">
            <a-button
              type="text"
              size="small"
              :disabled="index === 0"
              class="order-btn"
              @click="handleMoveUp('skill', index)"
            >
              ↑
            </a-button>
            <a-button
              type="text"
              size="small"
              :disabled="index === skillCategories.length - 1"
              class="order-btn"
              @click="handleMoveDown('skill', index)"
            >
              ↓
            </a-button>
          </div>
          <a-popconfirm
            title="确定删除此分类？"
            ok-text="确定"
            cancel-text="取消"
            @confirm="handleDelete('skill', cat.id)"
          >
            <a-button type="text" size="small" danger class="delete-btn">×</a-button>
          </a-popconfirm>
        </div>
      </div>
      <div class="add-row">
        <a-input
          v-model:value="newSkillSlug"
          placeholder="标识（英文）"
          size="small"
          style="width: 120px"
        />
        <a-input
          v-model:value="newSkillLabel"
          placeholder="名称"
          size="small"
          style="width: 120px"
        />
        <a-button size="small" type="primary" @click="handleAdd('skill')">添加</a-button>
      </div>
    </div>

    <!-- 角色模板分类 -->
    <div class="category-section">
      <div class="section-title">角色模板分类</div>
      <p class="section-desc">管理角色模板的分类标签。可通过上移/下移按钮调整显示顺序。</p>
      <div class="category-list">
        <div
          v-for="(cat, index) in roleCategories"
          :key="cat.id"
          class="category-item"
        >
          <span class="drag-handle" aria-hidden="true">≡</span>
          <a-input
            v-if="editingId === cat.id"
            v-model:value="editValue"
            size="small"
            class="edit-input"
            @pressEnter="saveEdit(cat)"
            @blur="saveEdit(cat)"
          />
          <span v-else class="category-label" @click="startEdit(cat)">{{ cat.label }}</span>
          <div class="order-btns">
            <a-button
              type="text"
              size="small"
              :disabled="index === 0"
              class="order-btn"
              @click="handleMoveUp('role_template', index)"
            >
              ↑
            </a-button>
            <a-button
              type="text"
              size="small"
              :disabled="index === roleCategories.length - 1"
              class="order-btn"
              @click="handleMoveDown('role_template', index)"
            >
              ↓
            </a-button>
          </div>
          <a-popconfirm
            title="确定删除此分类？"
            ok-text="确定"
            cancel-text="取消"
            @confirm="handleDelete('role_template', cat.id)"
          >
            <a-button type="text" size="small" danger class="delete-btn">×</a-button>
          </a-popconfirm>
        </div>
      </div>
      <div class="add-row">
        <a-input
          v-model:value="newRoleSlug"
          placeholder="标识（英文）"
          size="small"
          style="width: 120px"
        />
        <a-input
          v-model:value="newRoleLabel"
          placeholder="名称"
          size="small"
          style="width: 120px"
        />
        <a-button size="small" type="primary" @click="handleAdd('role_template')">添加</a-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useCategories } from '@/composables/useCategories'

const {
  categories: agentCategories,
  loadCategories: loadAgent,
  createCategory: createAgent,
  updateCategory: updateAgent,
  deleteCategory: deleteAgent,
  reorderCategories: reorderAgent,
} = useCategories('agent')

const {
  categories: skillCategories,
  loadCategories: loadSkill,
  createCategory: createSkill,
  updateCategory: updateSkill,
  deleteCategory: deleteSkill,
  reorderCategories: reorderSkill,
} = useCategories('skill')

const {
  categories: roleCategories,
  loadCategories: loadRole,
  createCategory: createRole,
  updateCategory: updateRole,
  deleteCategory: deleteRole,
  reorderCategories: reorderRole,
} = useCategories('role_template')

// Editing state
const editingId = ref(null)
const editValue = ref('')

function startEdit(cat) {
  editingId.value = cat.id
  editValue.value = cat.label
}

async function saveEdit(cat) {
  if (!editingId.value) return
  const newLabel = editValue.value.trim()
  if (newLabel && newLabel !== cat.label) {
    const updater = getUpdater(cat.entity_type)
    await updater(cat.id, { label: newLabel })
  }
  editingId.value = null
}

function getUpdater(entityType) {
  const map = { agent: updateAgent, skill: updateSkill, role_template: updateRole }
  return map[entityType]
}

function getCreator(entityType) {
  const map = { agent: createAgent, skill: createSkill, role_template: createRole }
  return map[entityType]
}

function getDeleter(entityType) {
  const map = { agent: deleteAgent, skill: deleteSkill, role_template: deleteRole }
  return map[entityType]
}

function getList(entityType) {
  const map = { agent: agentCategories, skill: skillCategories, role_template: roleCategories }
  return map[entityType]
}

function getReorderer(entityType) {
  const map = { agent: reorderAgent, skill: reorderSkill, role_template: reorderRole }
  return map[entityType]
}

// New category state
const newAgentSlug = ref('')
const newAgentLabel = ref('')
const newSkillSlug = ref('')
const newSkillLabel = ref('')
const newRoleSlug = ref('')
const newRoleLabel = ref('')

function getNewSlug(entityType) {
  const map = { agent: newAgentSlug, skill: newSkillSlug, role_template: newRoleSlug }
  return map[entityType]
}

function getNewLabel(entityType) {
  const map = { agent: newAgentLabel, skill: newSkillLabel, role_template: newRoleLabel }
  return map[entityType]
}

async function handleAdd(entityType) {
  const slug = getNewSlug(entityType).value.trim()
  const label = getNewLabel(entityType).value.trim()
  if (!slug || !label) return
  const creator = getCreator(entityType)
  const result = await creator({ slug, label })
  if (result) {
    getNewSlug(entityType).value = ''
    getNewLabel(entityType).value = ''
  }
}

async function handleDelete(entityType, id) {
  const deleter = getDeleter(entityType)
  await deleter(id)
}

async function handleMoveUp(entityType, index) {
  if (index === 0) return
  const list = getList(entityType).value
  const reordered = [...list]
  const tmp = reordered[index]
  reordered[index] = reordered[index - 1]
  reordered[index - 1] = tmp
  const items = reordered.map((c) => ({ id: c.id, sort_order: reordered.indexOf(c) }))
  const reorderer = getReorderer(entityType)
  await reorderer(items)
}

async function handleMoveDown(entityType, index) {
  const list = getList(entityType).value
  if (index >= list.length - 1) return
  const reordered = [...list]
  const tmp = reordered[index]
  reordered[index] = reordered[index + 1]
  reordered[index + 1] = tmp
  const items = reordered.map((c) => ({ id: c.id, sort_order: reordered.indexOf(c) }))
  const reorderer = getReorderer(entityType)
  await reorderer(items)
}

onMounted(async () => {
  await Promise.all([loadAgent(), loadSkill(), loadRole()])
})
</script>

<style lang="less" scoped>
.design-settings {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.category-section {
  .section-title {
    margin: 0 0 4px;
    color: var(--gray-900);
    font-size: 15px;
    font-weight: 600;
  }
}

.section-desc {
  margin: 0 0 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
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
}

.drag-handle {
  cursor: grab;
  color: var(--gray-400, #bbb);
  font-size: 14px;
  user-select: none;
}

.edit-input {
  flex: 1;
  min-width: 0;
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

  &:hover {
    background: var(--gray-100);
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

.add-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
