import test from 'node:test'
import assert from 'node:assert/strict'
import { connectorPayload, operationPayload, prepareWorkflowDefinition } from '../../src/utils/connector_forms.js'

test('编辑连接器输出真实 config、scope 和 revision，保留未展示的 provider 设置', () => {
  const payload = connectorPayload({ name: 'CRM', slug: 'crm', connector_type: 'generic_rest', enabled: true,
    auth_type: 'bearer', base_url: 'https://example.com', allowed_origins_text: 'https://example.com\n',
    allowed_private_cidrs_text: '', config_json: '{"timeout_seconds":12}',
    read_scope_json: '{"access_level":"global"}', write_scope_json: '{"access_level":"deny"}' }, { revision: 4 })
  assert.deepEqual(payload.config, { timeout_seconds: 12, auth_type: 'bearer', base_url: 'https://example.com',
    allowed_origins: ['https://example.com'], allowed_private_cidrs: [] })
  assert.equal(payload.expected_revision, 4)
  assert.deepEqual(payload.write_scope, { access_level: 'deny' })
  assert.equal(payload.auth_type, undefined)
})

test('操作使用后端契约字段并提交 query/body 参数模板', () => {
  const payload = operationPayload({ name: 'Update', slug: 'update', operation_type: 'write', http_method: 'POST',
    endpoint_template: '/record/{{id}}', approval_policy: 'required', response_type: 'json',
    request_schema_json: '{"type":"object"}', body_template_json: '{"name":"{{name}}"}',
    query_template_json: '', response_mapping_json: '', retry_policy_json: '{"max_attempts":1}', remote_idempotency_json: '{"header_name":"Idempotency-Key"}' }, { revision: 3 })
  assert.equal(payload.operation_type, 'write')
  assert.equal(payload.http_method, 'POST')
  assert.equal(payload.expected_revision, 3)
  assert.deepEqual(payload.body_template, { name: '{{name}}' })
  assert.equal(payload.category, undefined)
  assert.equal(payload.query_template, null)
  assert.deepEqual(payload.retry_policy, { max_attempts: 1 })
  assert.deepEqual(payload.remote_idempotency, { header_name: 'Idempotency-Key' })
})

test('工作流参数草稿必须成为真实 params，非法 JSON 阻止保存且不破坏草稿', () => {
  const definition = { steps: [{ id: 'crm', type: 'connector', params: {}, _params_json: '{"id":"{{customer}}"}' }] }
  const serialized = prepareWorkflowDefinition(definition)
  assert.deepEqual(serialized.steps[0].params, { id: '{{customer}}' })
  assert.equal(serialized.steps[0]._params_json, undefined)
  assert.equal(definition.steps[0]._params_json, '{"id":"{{customer}}"}')
  for (const value of ['{bad', '[]', 'null']) {
    assert.throws(() => prepareWorkflowDefinition({ steps: [{ id: 'crm', type: 'connector', _params_json: value }] }), /crm.*参数/)
  }
})
