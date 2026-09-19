import { apiGet, apiPost, apiPut } from './base'

export const marketplaceApi = {
  // 获取市场条目列表
  listEntries(params = {}) {
    const query = new URLSearchParams()
    if (params.source_type) query.set('source_type', params.source_type)
    if (params.category_id) query.set('category_id', params.category_id)
    if (params.page) query.set('page', params.page)
    if (params.page_size) query.set('page_size', params.page_size)
    const qs = query.toString()
    return apiGet(`/api/marketplace/entries${qs ? `?${qs}` : ''}`)
  },

  // 获取市场条目详情
  getEntryDetail(slug) {
    return apiGet(`/api/marketplace/entries/${slug}`)
  },

  // 安装市场技能
  installSkill(slug) {
    return apiPost(`/api/marketplace/entries/${slug}/install`, {})
  },

  // 获取待审批列表
  listPendingSubmissions() {
    return apiGet('/api/marketplace/submissions/pending')
  },

  // 提交技能到市场
  submitToMarket(data) {
    return apiPost('/api/marketplace/submissions', data)
  },

  // 审批通过
  approveSubmission(submissionId, data) {
    return apiPost(`/api/marketplace/submissions/${submissionId}/approve`, data)
  },

  // 审批驳回
  rejectSubmission(submissionId, data) {
    return apiPost(`/api/marketplace/submissions/${submissionId}/reject`, data)
  },

  // 下架技能
  unpublishEntry(slug) {
    return apiPut(`/api/marketplace/admin/entries/${slug}/unpublish`, {})
  },
}
