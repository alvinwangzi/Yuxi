import { ref, reactive } from 'vue'
import { message } from 'ant-design-vue'
import { categoryApi } from '@/apis/category_api'

// 全局缓存：每种实体类型只请求一次
const cache = reactive({})

/**
 * 分类管理 composable
 * @param {string} entityType - agent | skill | role_template
 */
export function useCategories(entityType) {
  const categories = ref(cache[entityType] || [])
  const isLoading = ref(false)

  async function loadCategories(force = false) {
    if (!force && cache[entityType]) {
      categories.value = cache[entityType]
      return categories.value
    }
    isLoading.value = true
    try {
      const res = await categoryApi.list(entityType)
      if (res.code === 0) {
        categories.value = res.data || []
        cache[entityType] = categories.value
      }
    } catch {
      console.error('Failed to load categories')
      message.error('加载分类失败')
    } finally {
      isLoading.value = false
    }
    return categories.value
  }

  async function createCategory(data) {
    try {
      const res = await categoryApi.create({ ...data, entity_type: entityType })
      if (res.code === 0) {
        message.success('分类创建成功')
        await loadCategories(true)
        return res.data
      } else {
        message.error(res.message || '创建失败')
        return null
      }
    } catch {
      message.error('创建分类失败')
      return null
    }
  }

  async function updateCategory(id, data) {
    try {
      const res = await categoryApi.update(id, data)
      if (res.code === 0) {
        message.success('分类更新成功')
        await loadCategories(true)
        return res.data
      } else {
        message.error(res.message || '更新失败')
        return null
      }
    } catch {
      message.error('更新分类失败')
      return null
    }
  }

  async function deleteCategory(id) {
    try {
      const res = await categoryApi.delete(id)
      if (res.code === 0) {
        message.success('分类已删除')
        await loadCategories(true)
        return true
      } else {
        message.error(res.message || '删除失败')
        return false
      }
    } catch {
      message.error('删除分类失败')
      return false
    }
  }

  async function reorderCategories(items) {
    try {
      const res = await categoryApi.reorder(items)
      if (res.code === 0) {
        await loadCategories(true)
        return true
      } else {
        message.error(res.message || '排序更新失败')
        return false
      }
    } catch {
      message.error('排序更新失败')
      return false
    }
  }

  function clearCache() {
    delete cache[entityType]
  }

  return {
    categories,
    isLoading,
    loadCategories,
    createCategory,
    updateCategory,
    deleteCategory,
    reorderCategories,
    clearCache,
  }
}
