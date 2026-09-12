<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { RefreshCw, Trash2, User } from '@lucide/vue'

import { roleApi } from '@/apis/workflow_api'
import InfoCard from '@/components/shared/InfoCard.vue'
import ExtensionCardGrid from '@/components/extensions/ExtensionCardGrid.vue'
import { useUserStore } from '@/stores/user'
import { useCategories } from '@/composables/useCategories'

const userStore = useUserStore()

const loading = ref(false)
const refreshing = ref(false)
const searchQuery = ref('')
const panelRef = ref(null)
const selectedCategory = ref('all')
const categories = ref([])
const roles = ref([])
const importedRoleIds = ref(new Set())
const categoryCounts = ref({})

// 重新分类
const { categories: roleCategories, loadCategories: loadRoleCategories } =
  useCategories('role_template')
const recategorizeState = reactive({
  visible: false,
  roleKey: '',
  anchorEl: null,
})

const currentRole = computed(() =>
  roles.value.find((r) => r.role_key === recategorizeState.roleKey)
)

// role_key 形如 "category/role-id"，role-id 可含子目录路径
const splitRoleKey = (roleKey) => {
  const idx = roleKey.indexOf('/')
  return { category: roleKey.slice(0, idx), roleId: roleKey.slice(idx + 1) }
}

const popupStyle = computed(() => {
  if (!recategorizeState.anchorEl) return {}
  const rect = recategorizeState.anchorEl.getBoundingClientRect()
  return {
    top: `${rect.bottom + 4}px`,
    left: `${rect.left}px`,
  }
})

// 分页
const PAGE_SIZE = 50
const totalRoles = ref(0) // 全局总数（用于"全部"标签显示）
const currentTotal = ref(0) // 当前视图总数（用于判断是否还有更多）
const loadedCount = ref(0)
const loadingMore = ref(false)

const hasMore = computed(() => loadedCount.value < currentTotal.value)

const onCategoryChange = (catId) => {
  selectedCategory.value = catId
  // 切换分类时重新加载
  loadRoles()
}

// 详情抽屉
const drawerOpen = ref(false)
const selectedRole = ref(null)
const detailLoading = ref(false)

const allCategories = computed(() => [
  { id: 'all', label: '全部' },
  ...categories.value
])

const filteredRoles = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  let list = roles.value
  if (selectedCategory.value !== 'all') {
    list = list.filter((r) => r.category_id === selectedCategory.value)
  }
  if (keyword) {
    list = list.filter(
      (r) =>
        String(r.name || '').toLowerCase().includes(keyword) ||
        String(r.description || '').toLowerCase().includes(keyword)
    )
  }
  return list
})

const renderedContent = computed(() => {
  if (!selectedRole.value?.content) return ''
  let html = selectedRole.value.content
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
    .replace(/\n{2,}/g, '</p><p>')
  return `<p>${html}</p>`
})

const isRoleImported = (role) => {
  return importedRoleIds.value.has(role.role_key)
}

const loadCategories = async () => {
  try {
    const response = await roleApi.getCategories()
    categories.value = response.data || []
    // 从分类数据初始化计数（确保所有分类都有默认值，避免并行加载时计数缺失）
    const counts = {}
    for (const cat of categories.value) {
      counts[cat.id] = cat.count ?? 0
    }
    categoryCounts.value = { all: totalRoles.value, ...counts }
  } catch (error) {
    message.error(error.message || '加载分类失败')
  }
}

const loadRoles = async (append = false) => {
  if (!append) loading.value = true
  else loadingMore.value = true
  try {
    const offset = append ? loadedCount.value : 0
    const category = selectedCategory.value === 'all' ? null : selectedCategory.value
    const response = await roleApi.list(category, offset, PAGE_SIZE)
    const newRoles = response.data || []
    if (append) {
      roles.value = [...roles.value, ...newRoles]
    } else {
      roles.value = newRoles
    }
    // 当前视图总数（用于判断是否还有更多）
    currentTotal.value = response.total ?? newRoles.length
    // 仅"全部"视图时更新全局总数
    if (selectedCategory.value === 'all') {
      totalRoles.value = currentTotal.value
    }
    loadedCount.value = roles.value.length
    // 使用后端返回的分类计数（不受分页影响）
    if (response.category_counts) {
      // 后端只返回有模板的分类计数，需为其余分类补默认值 0
      const merged = { all: totalRoles.value }
      for (const cat of categories.value) {
        merged[cat.id] = 0
      }
      Object.assign(merged, response.category_counts)
      categoryCounts.value = merged
    }
    // 内容不满一屏时自动加载下一页
    checkAutoLoad()
  } catch (error) {
    message.error(error.message || '加载角色失败')
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

const refresh = async () => {
  refreshing.value = true
  try {
    await Promise.all([loadCategories(), loadRoles()])
  } finally {
    refreshing.value = false
  }
}

const openDetail = async (role) => {
  selectedRole.value = { ...role, content: '' }
  drawerOpen.value = true
  detailLoading.value = true
  try {
    const { category, roleId } = splitRoleKey(role.role_key)
    const response = await roleApi.get(category, roleId)
    selectedRole.value = { ...role, ...response.data }
  } catch {
    // 详情获取失败时保留列表中的基本信息
  } finally {
    detailLoading.value = false
  }
}

const handleImport = (role) => {
  Modal.confirm({
    title: '导入角色模板',
    content: `确认将「${role.name}」导入为你的智能体？`,
    okText: '确认导入',
    cancelText: '取消',
    async onOk() {
      try {
        const { category, roleId } = splitRoleKey(role.role_key)
        await roleApi.importAsAgent(category, roleId)
        importedRoleIds.value.add(role.role_key)
        message.success('已导入为智能体')
      } catch (error) {
        if (error?.response?.status === 409) {
          message.warning('该角色已导入为智能体')
        } else {
          message.error(error.message || '导入失败')
        }
      }
    }
  })
}

const openRecategorize = (role, event) => {
  if (!userStore.isAdmin) return
  recategorizeState.roleKey = role.role_key
  recategorizeState.visible = true
  recategorizeState.anchorEl = event.currentTarget
  loadRoleCategories()
}

const selectCategory = async (categoryId) => {
  try {
    const res = await roleApi.updateCategory(recategorizeState.roleKey, categoryId)
    if (res.success) {
      message.success('分类已更新')
      await refresh()
    }
  } catch {
    message.error('更新分类失败')
  } finally {
    recategorizeState.visible = false
  }
}

const closeRecategorize = () => {
  recategorizeState.visible = false
}

const handleRecategorizeClickOutside = (e) => {
  if (recategorizeState.visible && !e.target.closest('.recategorize-popup')) {
    closeRecategorize()
  }
}

const deleting = ref(false)

const handleDelete = (role) => {
  Modal.confirm({
    title: '删除角色模板',
    content: `确认删除「${role.name}」？删除后将不再对普通用户可见。`,
    okText: '确认删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      deleting.value = true
      try {
        const { category, roleId } = splitRoleKey(role.role_key)
        await roleApi.delete(category, roleId)
        message.success('已删除')
        drawerOpen.value = false
        refresh()
      } catch (error) {
        if (error?.response?.status === 409) {
          message.warning('该角色已被删除')
        } else if (error?.response?.status === 403) {
          message.error('无权限执行此操作')
        } else {
          message.error(error.message || '删除失败')
        }
      } finally {
        deleting.value = false
      }
    }
  })
}

const SCROLL_THRESHOLD = 200
let scrollContainer = null

const findScrollContainer = (el) => {
  if (!el) return null
  let node = el.parentElement
  while (node) {
    const style = getComputedStyle(node)
    if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
      return node
    }
    node = node.parentElement
  }
  return document.documentElement
}

onMounted(() => {
  refresh()
  // 找到实际滚动容器并监听
  scrollContainer = findScrollContainer(panelRef.value)
  if (scrollContainer) {
    scrollContainer.addEventListener('scroll', handleScroll, { passive: true })
  }
  document.addEventListener('click', handleRecategorizeClickOutside)
})

onBeforeUnmount(() => {
  if (scrollContainer) {
    scrollContainer.removeEventListener('scroll', handleScroll)
  }
  document.removeEventListener('click', handleRecategorizeClickOutside)
})

const handleScroll = () => {
  if (!hasMore.value || loadingMore.value || loading.value) return
  const el = scrollContainer
  if (!el) return
  const scrollBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  if (scrollBottom < SCROLL_THRESHOLD) {
    loadRoles(true)
  }
}

// 数据加载后检查：内容不满一屏时自动加载下一页
const checkAutoLoad = () => {
  if (!hasMore.value || loadingMore.value || loading.value) return
  const el = scrollContainer
  if (!el) return
  if (el.scrollHeight <= el.clientHeight + 1) {
    loadRoles(true)
  }
}

defineExpose({ loading })
</script>

<template>
  <div ref="panelRef" class="role-template-panel">
    <!-- 分类标签栏 -->
    <div class="category-bar">
      <div class="category-scroll">
        <button
          v-for="cat in allCategories"
          :key="cat.id"
          type="button"
          class="category-tab"
          :class="{ active: selectedCategory === cat.id }"
          @click="onCategoryChange(cat.id)"
        >
          {{ cat.label }}
          <span v-if="categoryCounts[cat.id] !== undefined" class="category-count">
            {{ categoryCounts[cat.id] }}
          </span>
        </button>
      </div>
      <button type="button" class="refresh-btn" @click="refresh" title="刷新">
        <RefreshCw :size="14" :class="{ spin: refreshing }" />
      </button>
    </div>

    <!-- 搜索框 -->
    <div class="search-bar">
      <a-input
        v-model:value="searchQuery"
        placeholder="搜索角色名称或描述..."
        allow-clear
        class="search-input"
      />
    </div>

    <!-- 角色卡片网格 -->
    <ExtensionCardGrid :items="filteredRoles" empty-text="暂无匹配的角色模板" :min-width="280">
      <InfoCard
        v-for="role in filteredRoles"
        :key="role.role_key"
        :title="role.name"
        :subtitle="role.category_name"
        :description="role.description"
        :default-icon="User"
        :action-label="isRoleImported(role) ? '已导入' : '导入'"
        :action-variant="isRoleImported(role) ? 'default' : 'primary'"
        @click="openDetail(role)"
        @action-click="handleImport(role)"
      >
        <template #tags>
          <span
            class="card-tag tag-gray category-tag"
            :class="{ clickable: userStore.isAdmin }"
            @click.stop="openRecategorize(role, $event)"
          >
            {{ role.category_name }}
          </span>
        </template>
      </InfoCard>
      <div v-if="filteredRoles.length === 0 && !loading" class="empty-state">
        <a-empty :image="false" description="暂无匹配的角色模板" />
      </div>
    </ExtensionCardGrid>

    <!-- 滚动加载提示 -->
    <div v-if="hasMore && !searchQuery" class="scroll-load-hint">
      <template v-if="loadingMore">
        <RefreshCw :size="14" class="spin" />
        <span>加载中...</span>
      </template>
      <template v-else>
        <span>向下滚动加载更多（已加载 {{ loadedCount }} / {{ currentTotal }}）</span>
      </template>
    </div>
    <div v-else-if="!hasMore && roles.length > 0 && !searchQuery" class="scroll-load-hint end">
      <span>— 已加载全部 {{ currentTotal }} 个角色 —</span>
    </div>

    <!-- 详情抽屉 -->
    <a-drawer
      v-model:open="drawerOpen"
      placement="right"
      :width="560"
      class="role-detail-drawer"
    >
      <template #title>
        <div class="drawer-title-bar">
          <span class="drawer-title-text">{{ selectedRole?.name }}</span>
          <button
            v-if="userStore.isAdmin && selectedRole"
            type="button"
            class="drawer-delete-btn"
            :disabled="deleting"
            title="删除角色模板"
            @click="handleDelete(selectedRole)"
          >
            <Trash2 :size="15" />
          </button>
        </div>
      </template>
      <template v-if="selectedRole">
        <div class="drawer-meta">
          <span class="drawer-category">{{ selectedRole.category_name }}</span>
        </div>
        <div v-if="detailLoading" class="drawer-loading">
          <a-spin />
        </div>
        <div v-else-if="selectedRole.content" class="drawer-content" v-html="renderedContent"></div>
        <div v-else class="drawer-empty">暂无详细内容</div>
      </template>
      <template #footer>
        <div class="drawer-footer">
          <a-button
            type="primary"
            :disabled="isRoleImported(selectedRole)"
            :loading="detailLoading"
            @click="selectedRole && handleImport(selectedRole)"
          >
            {{ isRoleImported(selectedRole) ? '已导入为智能体' : '导入为智能体' }}
          </a-button>
        </div>
      </template>
    </a-drawer>

    <!-- 重新分类弹窗 -->
    <Teleport to="body">
      <div v-if="recategorizeState.visible" class="recategorize-popup" :style="popupStyle">
        <div class="popup-title">选择分类</div>
        <div
          v-for="cat in roleCategories"
          :key="cat.id"
          class="popup-item"
          :class="{ active: currentRole?.category_id === cat.id }"
          @click="selectCategory(cat.id)"
        >
          {{ cat.label }}
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style lang="less" scoped>
.role-template-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.category-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 12px var(--page-padding) 0;
  flex-shrink: 0;
}

.category-scroll {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.category-tab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--gray-600);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    color 0.2s ease;
  flex-shrink: 0;

  &:hover {
    color: var(--gray-900);
    background-color: var(--gray-50);
  }

  &.active {
    color: var(--gray-2000);
    background-color: color-mix(in srgb, var(--gray-800) 6%, var(--gray-0));
    font-weight: 600;
  }
}

.category-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--gray-100);
  color: var(--gray-500);
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-500);
  cursor: pointer;
  flex-shrink: 0;
  transition:
    background-color 0.2s ease,
    color 0.2s ease;

  &:hover {
    background: var(--gray-50);
    color: var(--gray-700);
  }

  .spin {
    animation: spin 1s linear infinite;
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.search-bar {
  padding: 12px var(--page-padding);
  flex-shrink: 0;

  .search-input {
    max-width: 360px;
  }
}

.empty-state {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
}

.scroll-load-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 20px 0 8px;
  color: var(--gray-500);
  font-size: 13px;

  &.end {
    color: var(--gray-400);
  }
}

.drawer-meta {
  margin-bottom: 16px;
}

.drawer-category {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 4px;
  background: var(--gray-100);
  color: var(--gray-600);
  font-size: 12px;
  font-weight: 500;
}

.drawer-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--gray-800);

  :deep(h1) { font-size: 20px; margin: 16px 0 8px; color: var(--gray-2000); }
  :deep(h2) { font-size: 17px; margin: 14px 0 6px; color: var(--gray-2000); }
  :deep(h3) { font-size: 15px; margin: 12px 0 6px; color: var(--gray-1500); }
  :deep(ul) { padding-left: 20px; margin: 8px 0; }
  :deep(li) { margin: 4px 0; }
  :deep(strong) { color: var(--gray-1000); }
  :deep(p) { margin: 8px 0; }
}

.drawer-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 0;
}

.drawer-empty {
  color: var(--gray-500);
  font-size: 14px;
  text-align: center;
  padding: 40px 0;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
}

.drawer-title-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 12px;
}

.drawer-title-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-delete-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--gray-400);
  cursor: pointer;
  flex-shrink: 0;
  transition:
    background-color 0.18s ease,
    color 0.18s ease,
    border-color 0.18s ease;

  &:hover,
  &:focus {
    outline: none;
    background: var(--color-error-50);
    color: var(--color-error-600);
    border-color: var(--color-error-200);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.category-tag.clickable {
  cursor: pointer;
  border: 1px dashed var(--gray-300, #d9d9d9);
}

.category-tag.clickable:hover {
  border-color: var(--main-600, #1677ff);
  color: var(--main-600, #1677ff);
}
</style>

<style lang="less">
.recategorize-popup {
  position: fixed;
  z-index: 1050;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--gray-200, #f0f0f0);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  padding: 8px 0;
  min-width: 160px;
  max-height: 300px;
  overflow-y: auto;
}

.recategorize-popup .popup-title {
  padding: 4px 12px 8px;
  font-size: 12px;
  color: var(--text-secondary, #888);
  border-bottom: 1px solid var(--gray-100, #f5f5f5);
  margin-bottom: 4px;
}

.recategorize-popup .popup-item {
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.2s;
}

.recategorize-popup .popup-item:hover {
  background: var(--bg-hover, rgba(0, 0, 0, 0.04));
}

.recategorize-popup .popup-item.active {
  color: var(--main-600, #1677ff);
  font-weight: 500;
}
</style>
