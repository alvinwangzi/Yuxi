<template>
  <div class="design-settings">
    <div class="header-section">
      <div class="header-content">
        <div class="section-title">分类设置</div>
        <p class="section-description">管理智能体、技能和角色模板的分类标签，可拖动调整顺序或点击名称编辑。</p>
      </div>
    </div>

    <a-tabs v-model:activeKey="activeTab" class="category-tabs">
      <a-tab-pane key="agent" tab="智能体分类">
        <CategoryPanel
          :categories="agentCategories"
          v-model:new-slug="newAgentSlug"
          v-model:new-label="newAgentLabel"
          entity-type="agent"
          @save-edit="handleSaveEdit"
          @add="handleAdd"
          @delete="handleDelete"
          @reorder="handleReorder"
        />
      </a-tab-pane>

      <a-tab-pane key="skill" tab="技能分类">
        <CategoryPanel
          :categories="skillCategories"
          v-model:new-slug="newSkillSlug"
          v-model:new-label="newSkillLabel"
          entity-type="skill"
          @save-edit="handleSaveEdit"
          @add="handleAdd"
          @delete="handleDelete"
          @reorder="handleReorder"
        />
      </a-tab-pane>

      <a-tab-pane key="role_template" tab="角色模板分类">
        <CategoryPanel
          :categories="roleCategories"
          v-model:new-slug="newRoleSlug"
          v-model:new-label="newRoleLabel"
          entity-type="role_template"
          @save-edit="handleSaveEdit"
          @add="handleAdd"
          @delete="handleDelete"
          @reorder="handleReorder"
        />
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useCategories } from '@/composables/useCategories'
import CategoryPanel from './CategoryPanel.vue'

const activeTab = ref('agent')

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

// ── 编辑 ──
function getUpdater(entityType) {
  return { agent: updateAgent, skill: updateSkill, role_template: updateRole }[entityType]
}

async function handleSaveEdit(entityType, id, data) {
  const updater = getUpdater(entityType)
  await updater(id, data)
}

// ── 新增 ──
function getCreator(entityType) {
  return { agent: createAgent, skill: createSkill, role_template: createRole }[entityType]
}

const newAgentSlug = ref('')
const newAgentLabel = ref('')
const newSkillSlug = ref('')
const newSkillLabel = ref('')
const newRoleSlug = ref('')
const newRoleLabel = ref('')

function getNewSlug(entityType) {
  return { agent: newAgentSlug, skill: newSkillSlug, role_template: newRoleSlug }[entityType]
}

function getNewLabel(entityType) {
  return { agent: newAgentLabel, skill: newSkillLabel, role_template: newRoleLabel }[entityType]
}

async function handleAdd(entityType) {
  const slug = getNewSlug(entityType).value.trim()
  const label = getNewLabel(entityType).value.trim()
  if (!slug || !label) return
  const result = await getCreator(entityType)({ slug, label })
  if (result) {
    getNewSlug(entityType).value = ''
    getNewLabel(entityType).value = ''
  }
}

// ── 删除 ──
function getDeleter(entityType) {
  return { agent: deleteAgent, skill: deleteSkill, role_template: deleteRole }[entityType]
}

async function handleDelete(entityType, id) {
  await getDeleter(entityType)(id)
}

// ── 排序 ──
function getList(entityType) {
  return { agent: agentCategories, skill: skillCategories, role_template: roleCategories }[entityType]
}

function getReorderer(entityType) {
  return { agent: reorderAgent, skill: reorderSkill, role_template: reorderRole }[entityType]
}

async function handleReorder(entityType, fromIndex, toIndex) {
  const list = [...getList(entityType).value]
  const [moved] = list.splice(fromIndex, 1)
  list.splice(toIndex, 0, moved)
  const items = list.map((c, i) => ({ id: c.id, sort_order: i }))
  await getReorderer(entityType)(items)
}

onMounted(async () => {
  await Promise.all([loadAgent(), loadSkill(), loadRole()])
})
</script>

<style lang="less" scoped>
.design-settings {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.category-tabs {
  :deep(.ant-tabs-nav) {
    margin-bottom: 12px;
  }
}
</style>
