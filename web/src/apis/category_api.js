import { apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

export const categoryApi = {
  /**
   * 列出指定实体类型的分类
   * @param {string} entityType - agent | skill | role_template
   */
  list(entityType) {
    return apiAdminGet(`/api/admin/categories?entity_type=${entityType}`)
  },

  /**
   * 创建分类
   */
  create(data) {
    return apiAdminPost('/api/admin/categories', data)
  },

  /**
   * 更新分类
   */
  update(id, data) {
    return apiAdminPut(`/api/admin/categories/${id}`, data)
  },

  /**
   * 删除分类
   */
  delete(id) {
    return apiAdminDelete(`/api/admin/categories/${id}`)
  },

  /**
   * 批量更新排序
   * @param {Array} items - [{id, sort_order}, ...]
   */
  reorder(items) {
    return apiAdminPut('/api/admin/categories/reorder', { items })
  },
}
