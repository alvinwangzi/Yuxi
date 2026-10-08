export function parseObject(text, label, nullable = false) {
  if (!text?.trim()) return nullable ? null : {}
  let value
  try { value = JSON.parse(text) } catch { throw new Error(`${label}必须是有效 JSON 对象`) }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label}必须是 JSON 对象`)
  return value
}

export function connectorPayload(form, existing = null) {
  const config = { ...parseObject(form.config_json, '附加配置'), base_url: form.base_url.trim(),
    allowed_origins: lines(form.allowed_origins_text), allowed_private_cidrs: lines(form.allowed_private_cidrs_text) }
  if (form.connector_type === 'generic_rest') config.auth_type = form.auth_type
  return { name: form.name, description: form.description || '', enabled: form.enabled, config,
    read_scope: parseObject(form.read_scope_json, '读取范围'), write_scope: parseObject(form.write_scope_json, '写入范围'),
    ...(existing ? { expected_revision: existing.revision } : { slug: form.slug, connector_type: form.connector_type }) }
}

export function operationPayload(form, existing = null) {
  return { name: form.name, slug: form.slug, description: form.description || '', operation_type: form.operation_type,
    http_method: form.http_method, endpoint_template: form.endpoint_template, approval_policy: form.approval_policy,
    response_type: form.response_type, request_schema: parseObject(form.request_schema_json, '参数 Schema', true),
    body_template: parseObject(form.body_template_json, '请求正文模板', true),
    query_template: parseObject(form.query_template_json, '查询模板', true),
    response_mapping: parseObject(form.response_mapping_json, '响应映射', true),
    retry_policy: parseObject(form.retry_policy_json, '重试策略', true),
    remote_idempotency: parseObject(form.remote_idempotency_json, '远端幂等策略', true),
    ...(existing ? { expected_revision: existing.revision } : {}) }
}

export function prepareWorkflowDefinition(definition) {
  const serialized = JSON.parse(JSON.stringify(definition))
  for (const step of serialized.steps || []) {
    if (step.type !== 'connector') continue
    if (step._params_json !== undefined) step.params = parseObject(step._params_json, `${step.id} 调用参数`)
    delete step._params_json
  }
  return serialized
}

function lines(text) {
  return (text || '').split(/\r?\n/).map(value => value.trim()).filter(Boolean)
}
