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

  /** 获取工作流统计数据 */
  getStats() {
    return apiGet(`${WORKFLOWS_URL}/stats`)
  },

  /** 获取平台工作流库 */
  listPlatform(params = {}) {
    const query = buildQuery(params)
    return apiGet(`${WORKFLOWS_URL}/platform${query ? '?' + query : ''}`)
  },

  /** 从平台工作流库导入 */
  importWorkflow(workflowId) {
    return apiPost(`${WORKFLOWS_URL}/import`, { workflow_id: workflowId })
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

  /** 更新工作流分类 */
  updateCategory(id, categoryId) {
    return apiAdminPut(`${WORKFLOWS_URL}/${id}/category`, { category_id: categoryId })
  },

  /** 触发工作流执行 */
  run(id, inputVariables = {}) {
    return apiPost(`${WORKFLOWS_URL}/${id}/run`, { input_variables: inputVariables })
  },

  /** 获取运行详情 */
  getRun(runId) {
    return apiGet(`${WORKFLOWS_URL}/runs/${runId}`)
  },

  /** 获取工作流运行历史 */
  listRuns(workflowId) {
    return apiGet(`${WORKFLOWS_URL}/${workflowId}/runs`)
  },

  /** 强制终止工作流运行 */
  cancelRun(runId) {
    return apiPost(`${WORKFLOWS_URL}/runs/${runId}/cancel`)
  },

  /** 获取步骤类型列表 */
  getStepTypes() {
    return apiGet(`${WORKFLOWS_URL}/meta/step-types`)
  },

  /** 测试运行脚本（沙盒执行，不持久化） */
  testScript(code, language, testContext = {}) {
    return apiPost(`${WORKFLOWS_URL}/test-script`, {
      code,
      language,
      test_context: testContext,
    })
  },

  /** 检查工作流定义中引用的 Agent 是否存在 */
  checkAgents(definition) {
    return apiPost(`${WORKFLOWS_URL}/check-agents`, { definition })
  },

  /** 批量创建工作流中缺失的 Agent */
  createMissingAgents(definition, agentSlugs) {
    return apiPost(`${WORKFLOWS_URL}/create-missing-agents`, { definition, agent_slugs: agentSlugs })
  },
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
