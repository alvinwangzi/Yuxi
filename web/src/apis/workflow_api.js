/**
 * 工作流与角色模板 API 客户端。
 */

import { apiGet, apiPost, apiPut, apiDelete, apiAdminPut, buildQuery } from './base'

const WORKFLOWS_URL = '/api/workflows'
const ROLES_URL = '/api/roles'

// ── 工作流 ──

export const workflowApi = {
  /** 获取工作流列表 */
  list(params = {}) {
    const query = buildQuery(params)
    return apiGet(`${WORKFLOWS_URL}${query ? '?' + query : ''}`)
  },

  /** 获取工作流详情 */
  get(id) {
    return apiGet(`${WORKFLOWS_URL}/${id}`)
  },

  /** 创建工作流 */
  create(data) {
    return apiPost(WORKFLOWS_URL, data)
  },

  /** 更新工作流 */
  update(id, data) {
    return apiPut(`${WORKFLOWS_URL}/${id}`, data)
  },

  /** 删除工作流 */
  delete(id) {
    return apiDelete(`${WORKFLOWS_URL}/${id}`)
  },

  /** 触发工作流执行 */
  run(id, inputVariables = {}) {
    return apiPost(`${WORKFLOWS_URL}/${id}/run`, { input_variables: inputVariables })
  },

  /** 获取运行详情 */
  getRun(runId) {
    return apiGet(`${WORKFLOWS_URL}/runs/${runId}`)
  },

  /** 获取步骤类型列表 */
  getStepTypes() {
    return apiGet(`${WORKFLOWS_URL}/meta/step-types`)
  }
}

// ── 角色模板 ──

export const roleApi = {
  /** 获取角色列表（支持分页，category_id 为分类 ID） */
  list(categoryId = null, offset = 0, limit = 50) {
    const params = { offset, limit }
    if (categoryId) params.category_id = categoryId
    return apiGet(`${ROLES_URL}?${buildQuery(params)}`)
  },

  /** 获取角色分类 */
  getCategories() {
    return apiGet(`${ROLES_URL}/categories`)
  },

  /** 获取角色详情 */
  get(category, roleId) {
    return apiGet(`${ROLES_URL}/${category}/${roleId}`)
  },

  /** 导入角色为 Agent */
  importAsAgent(category, roleId) {
    return apiPost(`${ROLES_URL}/${category}/${roleId}/import`)
  },

  /** 删除角色模板（仅管理员，逻辑删除） */
  delete(category, roleId) {
    return apiDelete(`${ROLES_URL}/${category}/${roleId}`)
  },

  /** 更新角色分类 */
  updateCategory(roleKey, categoryId) {
    return apiAdminPut(`/api/roles/${roleKey}/category`, { category_id: categoryId })
  },
}
