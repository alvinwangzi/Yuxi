import test from 'node:test'
import assert from 'node:assert/strict'
import { connectorFieldName, validConnectorFieldName, optimizeConnectorFieldNames } from '../../src/utils/connector_field_names.js'

test('常见CRM字段自动命名，未知中文使用稳定字段ID', () => {
  assert.equal(connectorFieldName({ field_name: '客户名称', field_id: 'fldA' }, {}), 'customer_name')
  assert.equal(connectorFieldName({ field_name: '自定义中文', field_id: 'fldB' }, {}), 'field_fldB')
  assert.equal(connectorFieldName({ field_name: '自定义ABC', field_id: 'fldD' }, {}), 'field_fldD')
  assert.equal(connectorFieldName({ field_name: 'Annual Revenue', field_id: 'fldC' }, {}), 'annual_revenue')
})
test('保留已保存名称并防止重名及协议参数冲突', () => {
  const field = { field_name: '客户名称', field_id: 'fldA' }
  assert.equal(connectorFieldName(field, { legacy: 'fldA' }), 'legacy')
  assert.equal(connectorFieldName(field, { customer_name: 'fldB' }), 'customer_name_fldA')
  assert.equal(connectorFieldName({ field_name: 'record_id', field_id: 'fldC' }, {}), 'record_id_fldC')
  assert.equal(validConnectorFieldName('page_size'), false)
  assert.equal(validConnectorFieldName('__proto__'), false)
  assert.equal(validConnectorFieldName('customer_name'), true)
  assert.equal(connectorFieldName({ field_name: 'constructor', field_id: 'fldD' }, {}), 'constructor_fldD')
})

test('实际 CRM 常见字段均生成可理解的名称', () => {
  for (const name of ['客户状态', '一句话进展', '跟进记录', '客户标签', '所属行业', '客户联系人',
    '客户人员规模', '客户所属区域', '销售订单', '客户基本信息', '商机描述', '商机金额', '优先级',
    '赢率预测', '实际成交', '客户', '丢单原因']) {
    assert.ok(!connectorFieldName({ field_name: name, field_id: 'fldTest' }, {}).startsWith('field_'), name)
  }
})

test('批量优化保留自定义名称、字段类型和业务键，重复优化保持稳定', () => {
  const directory = [{ field_name: '客户状态', field_id: 'fldA' }, { field_name: '商机金额', field_id: 'fldB' }]
  const config = { customer_fields: { field_fldA: 'fldA', custom_amount: 'fldB' },
    customer_field_types: { field_fldA: 3, custom_amount: 2 }, customer_business_key_field: 'field_fldA' }
  const result = optimizeConnectorFieldNames(config, 'customer', directory)
  assert.deepEqual(result.customer_fields, { customer_status: 'fldA', custom_amount: 'fldB' })
  assert.deepEqual(result.customer_field_types, { customer_status: 3, custom_amount: 2 })
  assert.equal(result.customer_business_key_field, 'customer_status')
  assert.deepEqual(optimizeConnectorFieldNames(result, 'customer', directory), result)
  assert.ok(config.customer_fields.field_fldA)
})
