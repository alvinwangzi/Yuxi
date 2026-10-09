const crmNames = {
  客户名称: 'customer_name', 客户名: 'customer_name', 行业: 'industry', 规模: 'company_size',
  联系方式: 'contact', 电话: 'phone', 手机号: 'mobile', 邮箱: 'email', 负责人: 'owner', 状态: 'status',
  商机名称: 'opportunity_name', 金额: 'amount', 阶段: 'stage', 关联客户: 'customer',
  预计成交日期: 'expected_close_date', 客户状态: 'customer_status', 所属行业: 'industry',
  客户人员规模: 'company_size', 客户规模: 'company_size', 客户标签: 'customer_tags',
  客户联系人: 'customer_contact', 联系人: 'contact', 客户所属区域: 'customer_region',
  客户区域: 'customer_region', 客户地址: 'customer_address', 客户基本信息: 'customer_info',
  销售负责人: 'sales_owner', 一句话进展: 'progress_summary', 跟进记录: 'follow_up_records',
  最后跟进日期: 'last_follow_up_date', 商机: 'opportunities', 销售订单: 'sales_orders',
  商机描述: 'opportunity_description', 商机阶段: 'stage', 商机金额: 'amount',
  优先级: 'priority', 赢率预测: 'win_probability', 实际成交金额: 'actual_amount',
  实际成交: 'actual_amount', 实际成交日期: 'actual_close_date', 实际成交月份: 'actual_close_month',
  客户: 'customer', 丢单原因: 'loss_reason', 创建人: 'created_by', 创建时间: 'created_at',
  跟进记录信息: 'follow_up_info', 商机跟进记录信息: 'opportunity_follow_up_info',
  预测商机金额: 'forecast_amount', 最后跟进日期加15天: 'follow_up_due_date'
}
const reservedNames = new Set(['runtime', 'record_id', 'page_size', 'page_token', '__proto__', 'constructor', 'prototype'])

/** 保留已有映射；新字段自动命名，重名用稳定的字段 ID 区分。 */
export function connectorFieldName(field, mapping) {
  const existing = Object.entries(mapping).find(([, id]) => id === field.field_id || id === field.field_name)
  if (existing) return existing[0]
  const english = field.field_name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  const known = Object.hasOwn(crmNames, field.field_name.trim()) ? crmNames[field.field_name.trim()] : null
  const base = known || (/^[\x20-\x7e]+$/.test(field.field_name) && /^[a-z][a-z0-9_]*$/.test(english) ? english : `field_${field.field_id}`)
  const used = name => reservedNames.has(name) || Object.hasOwn(mapping, name)
  if (!used(base)) return base
  const unique = `${base}_${field.field_id}`
  let candidate = unique
  let suffix = 2
  while (used(candidate)) candidate = `${unique}_${suffix++}`
  return candidate
}

/** 手动名称不能覆盖调用协议保留字段或已有映射。 */
export function validConnectorFieldName(name) {
  return /^[a-zA-Z][a-zA-Z0-9_]*$/.test(name) && !reservedNames.has(name)
}

/** 仅优化历史自动生成的 ID 名称，保留自定义名称与字段类型。 */
export function optimizeConnectorFieldNames(config, kind, directory) {
  const fields = { ...(config[kind + '_fields'] || {}) }
  const types = { ...(config[kind + '_field_types'] || {}) }
  let businessKey = config[kind + '_business_key_field']
  for (const field of directory) {
    const old = Object.keys(fields).find(name => fields[name] === field.field_id || fields[name] === field.field_name)
    if (old !== field.field_id && old !== `field_${field.field_id}`) continue
    const type = types[old]
    delete fields[old]
    delete types[old]
    const name = connectorFieldName(field, fields)
    fields[name] = field.field_id
    if (type !== undefined) types[name] = type
    if (businessKey === old) businessKey = name
  }
  return { ...config, [kind + '_fields']: fields, [kind + '_field_types']: types,
    ...(businessKey === undefined ? {} : { [kind + '_business_key_field']: businessKey }) }
}
