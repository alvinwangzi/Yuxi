import { apiGet, apiPost, apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

const ADMIN_BASE = '/api/system/connectors'
const USER_BASE = '/api/connectors'

export const getConnectorTypes = async () => {
  return apiAdminGet(`${ADMIN_BASE}/types`)
}

export const getConnectors = async (params = {}) => {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  if (params.connector_type) query.set('connector_type', params.connector_type)
  if (params.enabled !== undefined) query.set('enabled', String(params.enabled))
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))
  const qs = query.toString()
  return apiAdminGet(`${ADMIN_BASE}${qs ? '?' + qs : ''}`)
}

export const getConnector = async (slug) => {
  return apiAdminGet(`${ADMIN_BASE}/${encodeURIComponent(slug)}`)
}

export const createConnector = async (data) => {
  return apiAdminPost(ADMIN_BASE, data)
}

export const updateConnector = async (slug, data) => {
  return apiAdminPut(`${ADMIN_BASE}/${encodeURIComponent(slug)}`, data)
}

export const deleteConnector = async (slug) => {
  return apiAdminDelete(`${ADMIN_BASE}/${encodeURIComponent(slug)}`)
}

export const patchCredentials = async (slug, data) => {
  return apiAdminPut(`${ADMIN_BASE}/${encodeURIComponent(slug)}/credentials`, data)
}

export const testConnector = async (slug) => {
  return apiAdminPost(`${ADMIN_BASE}/${encodeURIComponent(slug)}/test`)
}

export const getConnectorOperations = async (slug) => {
  return apiAdminGet(`${ADMIN_BASE}/${encodeURIComponent(slug)}/operations`)
}

export const createConnectorOperation = async (slug, data) => {
  return apiAdminPost(`${ADMIN_BASE}/${encodeURIComponent(slug)}/operations`, data)
}

export const updateConnectorOperation = async (slug, operationSlug, data) => {
  return apiAdminPut(
    `${ADMIN_BASE}/${encodeURIComponent(slug)}/operations/${encodeURIComponent(operationSlug)}`,
    data,
  )
}

export const deleteConnectorOperation = async (slug, operationSlug) => {
  return apiAdminDelete(
    `${ADMIN_BASE}/${encodeURIComponent(slug)}/operations/${encodeURIComponent(operationSlug)}`,
  )
}

export const testConnectorOperation = async (slug, operationSlug, data = {}) => {
  return apiAdminPost(
    `${ADMIN_BASE}/${encodeURIComponent(slug)}/operations/${encodeURIComponent(operationSlug)}/test`,
    data,
  )
}

export const getConnectorUsage = async (slug, params = {}) => {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.actor_uid) query.set('actor_uid', params.actor_uid)
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))
  const qs = query.toString()
  return apiAdminGet(
    `${ADMIN_BASE}/${encodeURIComponent(slug)}/usage${qs ? '?' + qs : ''}`,
  )
}

export const reconcileInvocation = async (invocationId, data) => {
  return apiAdminPost(`${ADMIN_BASE}/invocations/${encodeURIComponent(invocationId)}/reconcile`, data)
}

export const getUserConnectors = async () => {
  return apiGet(USER_BASE)
}

export const getUserOperations = async (slug) => {
  return apiGet(`${USER_BASE}/${encodeURIComponent(slug)}/operations`)
}

export const getInvocation = async (invocationId) => {
  return apiGet(`${USER_BASE}/invocations/${encodeURIComponent(invocationId)}`)
}

export const submitDecision = async (invocationId, data) => {
  return apiPost(`${USER_BASE}/invocations/${encodeURIComponent(invocationId)}/decision`, data)
}

export const connectorApi = {
  getConnectorTypes,
  getConnectors,
  getConnector,
  createConnector,
  updateConnector,
  deleteConnector,
  patchCredentials,
  testConnector,
  getConnectorOperations,
  createConnectorOperation,
  updateConnectorOperation,
  deleteConnectorOperation,
  testConnectorOperation,
  getConnectorUsage,
  reconcileInvocation,
  getUserConnectors,
  getUserOperations,
  getInvocation,
  submitDecision,
}

export default connectorApi
