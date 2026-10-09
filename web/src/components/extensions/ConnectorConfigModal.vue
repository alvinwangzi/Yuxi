<template>
  <a-modal :open="open" :title="isEdit ? `编辑连接器 — ${connector?.name}` : '添加连接器'"
    :width="720" :destroy-on-close="true" :confirm-loading="saving" @ok="handleSave" @cancel="handleClose">
    <a-form layout="vertical" class="connector-config-form">
      <a-form-item label="名称" required><a-input v-model:value="form.name" placeholder="连接器显示名称" /></a-form-item>
      <a-form-item label="标识 (slug)" required><a-input v-model:value="form.slug" :disabled="isEdit" placeholder="salesforce_prod" /></a-form-item>
      <a-form-item label="类型" required>
        <a-select v-model:value="form.connector_type" :disabled="isEdit" placeholder="选择连接器类型">
          <a-select-option v-for="type in connectorTypes" :key="type.type" :value="type.type">{{ TYPE_LABELS[type.type] || type.type }}</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item label="描述"><a-textarea v-model:value="form.description" :rows="2" /></a-form-item>
      <details v-if="form.connector_type === 'feishu_bitable_crm'" class="connector-guide">
        <summary>飞书 CRM 配置与测试指南</summary>
        <ol>
          <li>在飞书开放平台创建企业自建应用，获取 App ID、App Secret；开通多维表格读写 API 权限并发布应用。随后在 CRM 多维表格的“添加文档应用”中添加该应用，授予相应阅读或编辑权限。</li>
          <li>Base URL 和允许的来源地址均填写 <code>https://open.feishu.cn</code>，内网 CIDR 留空。应用凭据只填下方认证密码框，不放进附加配置。</li>
          <li>从 <code>/base/表格标识?table=数据表标识</code> 链接获取 app_token，附加配置填写 <code>{"app_token":"表格标识"}</code>。若链接为 /wiki/，需通过飞书知识库节点接口获取实际表格标识，不能直接使用节点标识。</li>
          <li>首次保存前关闭“启用状态”，先保存草稿。重新编辑，点击“读取表和字段目录”，选择客户表和商机表并保存，再读取目录、勾选字段。调用参数名自动生成，历史默认 ID 名称可批量优化。</li>
          <li>测试账号 UID 位于左下角头像菜单的“ID”。读取范围可填写 <code>{"access_level":"user","user_uids":["测试账号ID"]}</code>；写入范围先保持 <code>{"access_level":"deny"}</code>。完成表和字段配置后启用并保存。</li>
          <li>在测试 Agent 的资源配置中选择此连接器，先查询前 5 条客户记录，与飞书核对。需要写入测试时再配置指定用户的写入范围，使用测试记录并完成调用审批。</li>
        </ol>
        <p>若保存提示校验失败，先检查 app_token 是否只填标识，以及启用时客户表、商机表是否都已配置。读取目录无权限时，检查应用 API 权限是否已发布，以及目标表格是否已添加文档应用。</p>
        <a href="https://open.feishu.cn/app" target="_blank" rel="noopener noreferrer">飞书开放平台</a>
      </details>
      <a-form-item label="启用状态"><a-switch v-model:checked="form.enabled" /></a-form-item>
      <a-divider>目标与权限</a-divider>
      <a-form-item label="Base URL" required><a-input v-model:value="form.base_url" placeholder="https://api.example.com" /></a-form-item>
      <a-form-item label="允许的来源地址（每行一个，含端口）"><a-textarea v-model:value="form.allowed_origins_text" :rows="2" placeholder="https://api.example.com" /></a-form-item>
      <a-form-item label="允许的内网 CIDR（每行一个，可留空）"><a-textarea v-model:value="form.allowed_private_cidrs_text" :rows="2" placeholder="10.20.0.0/24" /></a-form-item>
      <a-form-item label="读取范围 (JSON)" required><a-textarea v-model:value="form.read_scope_json" :rows="3" /></a-form-item>
      <a-form-item label="写入范围 (JSON)" required><a-textarea v-model:value="form.write_scope_json" :rows="3" /></a-form-item>
      <a-form-item label="附加配置 (JSON)"><a-textarea v-model:value="form.config_json" :rows="5" placeholder="provider 字段映射、超时和并发限制" /></a-form-item>
      <template v-if="form.connector_type === 'feishu_bitable_crm'">
        <a-alert type="info" message="先保存停用草稿、Base 标识和完整应用凭据，再读取表目录；选择表并保存后，可读取字段并配置调用参数名。" />
        <a-button :disabled="!isEdit" :loading="metadataLoading" @click="loadMetadata">读取表和字段目录</a-button>
        <a-alert v-if="metadataError" type="error" :message="metadataError" />
        <p class="credential-hint">勾选字段后自动生成调用参数名，无需逐项填写。已有名称保持不变。</p>
        <a-checkbox v-model:checked="showAdvancedNames">高级：手动修改调用参数名</a-checkbox>
        <a-button v-if="Object.keys(metadataFields).length" @click="optimizeDefaultNames">优化默认参数名</a-button>
        <p v-if="Object.keys(metadataFields).length" class="credential-hint">将已选字段的默认 ID 名称批量改为常见 CRM 名称，保留手工名称；点击确定后保存。</p>
        <template v-for="kind in ['customer', 'opportunity']" :key="kind">
          <a-form-item v-if="metadataTables.length" :label="kind === 'customer' ? '客户表' : '商机表'">
            <a-select :value="metadataConfig[kind + '_table_id']" :options="metadataTables.map(table => ({ value: table.table_id, label: table.name }))" @change="selectMetadataTable(kind, $event)" />
          </a-form-item>
          <div v-for="field in metadataFields[metadataConfig[kind + '_table_id']] || []" :key="kind + field.field_id" class="metadata-field-row">
            <a-checkbox :checked="selectedField(kind, field)" :disabled="!supportedFieldTypes.includes(field.type)" @change="toggleField(kind, field, $event.target.checked)">
              {{ field.field_name }}（{{ fieldTypeLabels[field.type] || '不支持写入' }}）
            </a-checkbox>
            <a-input v-if="selectedField(kind, field) && showAdvancedNames" :value="logicalFieldName(kind, field)" placeholder="调用参数名" @change="renameField(kind, field, $event.target.value)" />
            <span v-else-if="selectedField(kind, field)" class="credential-hint">{{ logicalFieldName(kind, field) }}</span>
          </div>
        </template>
      </template>
      <a-divider>认证配置</a-divider>
      <a-form-item v-if="form.connector_type === 'generic_rest'" label="认证方式">
        <a-select v-model:value="form.auth_type">
          <a-select-option value="none">无</a-select-option><a-select-option value="bearer">Bearer Token</a-select-option>
          <a-select-option value="basic">Basic Auth</a-select-option><a-select-option value="api_key">API Key</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item v-for="key in credentialKeys" :key="key" :label="key">
        <a-input-password v-model:value="credentialValues[key]" placeholder="留空保持原值；新值只写入加密凭据" />
        <div v-if="existingKeys.includes(key)" class="credential-hint">已配置，留空保持当前值</div>
      </a-form-item>
      <a-form-item v-if="existingKeys.length" label="删除已有凭据">
        <a-checkbox-group v-model:value="deleteKeys" :options="existingKeys" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import { createConnector, updateConnector, discoverConnectorMetadata } from '@/apis/connector_api'
import { connectorPayload, parseObject } from '@/utils/connector_forms'
import { connectorFieldName, validConnectorFieldName, optimizeConnectorFieldNames } from '@/utils/connector_field_names'
const TYPE_LABELS = { generic_rest: '通用 REST', salesforce: 'Salesforce', feishu_bitable_crm: '飞书多维表格' }
const props = defineProps({ open: Boolean, connector: Object, connectorTypes: { type: Array, default: () => [] } })
const emit = defineEmits(['update:open', 'saved'])
const isEdit = computed(() => !!props.connector?.slug)
const saving = ref(false)
const revision = ref(null)
const deleteKeys = ref([])
const metadataLoading = ref(false)
const metadataError = ref('')
const showAdvancedNames = ref(false)
const metadataTables = ref([])
const metadataFields = ref({})
let metadataGeneration = 0
const supportedFieldTypes = [1, 2, 3, 4, 5, 7, 18, 21]
const fieldTypeLabels = { 1: '文本', 2: '数字', 3: '单选', 4: '多选', 5: '日期', 7: '复选框', 18: '关联', 21: '双向关联' }
const credentialValues = reactive({})
const form = reactive({ name: '', slug: '', connector_type: '', description: '', enabled: true,
  auth_type: 'none', base_url: '', config_json: '{}', allowed_origins_text: '', allowed_private_cidrs_text: '',
  read_scope_json: '{"access_level":"deny"}', write_scope_json: '{"access_level":"deny"}' })
const metadataConfig = computed(() => { try { return parseObject(form.config_json, '附加配置') } catch { return {} } })
const existingKeys = computed(() => (props.connector?.credential_keys || []).map(item => typeof item === 'string' ? item : item.key))
const credentialKeys = computed(() => {
  if (form.connector_type === 'generic_rest') return { none: [], bearer: ['token'], basic: ['username', 'password'], api_key: ['api_key'] }[form.auth_type] || []
  return props.connectorTypes.find(type => type.type === form.connector_type)?.credential_keys || []
})
watch(() => props.open, value => {
  metadataGeneration++
  metadataLoading.value = false
  if (!value) return
  showAdvancedNames.value = false
  const connector = props.connector || {}
  const { base_url = '', auth_type = 'none', allowed_origins = [], allowed_private_cidrs = [], ...extra } = connector.config || {}
  Object.assign(form, { name: connector.name || '', slug: connector.slug || '', connector_type: connector.connector_type || '',
    description: connector.description || '', enabled: connector.enabled !== false, base_url, auth_type,
    allowed_origins_text: allowed_origins.join('\n'), allowed_private_cidrs_text: allowed_private_cidrs.join('\n'),
    config_json: JSON.stringify(extra, null, 2), read_scope_json: JSON.stringify(connector.read_scope || { access_level: 'deny' }, null, 2),
    write_scope_json: JSON.stringify(connector.write_scope || { access_level: 'deny' }, null, 2) })
  revision.value = connector.revision
  metadataTables.value = []
  metadataFields.value = {}
  metadataError.value = ''
  clearCredentials()
})
function clearCredentials() { for (const key of Object.keys(credentialValues)) delete credentialValues[key]; deleteKeys.value = [] }
function handleClose() { metadataGeneration++; clearCredentials(); emit('update:open', false) }
async function loadMetadata() {
  const saved = props.connector?.config || {}
  const draft = metadataConfig.value
  if (['app_token', 'customer_table_id', 'opportunity_table_id'].some(key => draft[key] !== saved[key]) || Object.values(credentialValues).some(Boolean)) {
    message.warning('请先保存 Base、所选表和凭据，再读取目录'); return
  }
  metadataLoading.value = true
  const generation = ++metadataGeneration
  metadataError.value = ''
  try {
    const response = await discoverConnectorMetadata(props.connector.slug)
    if (generation !== metadataGeneration) return
    metadataTables.value = response.data.tables
    metadataFields.value = response.data.fields
  } catch (error) { if (generation === metadataGeneration) metadataError.value = error.message || '读取目录失败，请检查凭据和应用访问权限' }
  finally { if (generation === metadataGeneration) metadataLoading.value = false }
}
function selectMetadataTable(kind, id) {
  metadataGeneration++
  metadataLoading.value = false
  const config = { ...metadataConfig.value, [kind + '_table_id']: id, [kind + '_fields']: {}, [kind + '_field_types']: {} }
  form.config_json = JSON.stringify(config, null, 2)
  metadataFields.value = {}
}
function logicalFieldName(kind, field) {
  return connectorFieldName(field, metadataConfig.value[kind + '_fields'] || {})
}
function optimizeDefaultNames() {
  let config = { ...metadataConfig.value }
  for (const kind of ['customer', 'opportunity']) {
    config = optimizeConnectorFieldNames(config, kind, metadataFields.value[config[kind + '_table_id']] || [])
  }
  form.config_json = JSON.stringify(config, null, 2)
  message.success('默认参数名已优化，请保存配置')
}
function selectedField(kind, field) {
  return Object.values(metadataConfig.value[kind + '_fields'] || {}).some(id => id === field.field_id || id === field.field_name)
}
function toggleField(kind, field, checked) {
  const config = { ...metadataConfig.value }
  const fields = { ...(config[kind + '_fields'] || {}) }
  const types = { ...(config[kind + '_field_types'] || {}) }
  const name = logicalFieldName(kind, field)
  if (checked) { fields[name] = field.field_id; types[name] = field.type }
  else { delete fields[name]; delete types[name] }
  form.config_json = JSON.stringify({ ...config, [kind + '_fields']: fields, [kind + '_field_types']: types }, null, 2)
}
function renameField(kind, field, name) {
  if (!validConnectorFieldName(name)) { message.warning('调用参数名须以英文字母开头，仅含字母、数字和下划线，且不能使用保留名称'); return }
  const config = { ...metadataConfig.value }
  const fields = { ...(config[kind + '_fields'] || {}) }
  const types = { ...(config[kind + '_field_types'] || {}) }
  const old = logicalFieldName(kind, field)
  if (name !== old && Object.hasOwn(fields, name)) { message.warning('调用参数名已存在'); return }
  delete fields[old]; delete types[old]
  fields[name] = field.field_id; types[name] = field.type
  form.config_json = JSON.stringify({ ...config, [kind + '_fields']: fields, [kind + '_field_types']: types }, null, 2)
}
async function handleSave() {
  if (!form.name || !form.slug || !form.connector_type || !form.base_url) { message.warning('请填写名称、标识、类型和 Base URL'); return }
  let payload
  try { payload = connectorPayload(form, isEdit.value ? { revision: revision.value } : null) } catch (error) { message.error(error.message); return }
  const upsert = Object.fromEntries(Object.entries(credentialValues).filter(([key, value]) => credentialKeys.value.includes(key) && value))
  saving.value = true
  try {
    if (!isEdit.value) payload.credentials = upsert
    else if (Object.keys(upsert).length || deleteKeys.value.length) payload.credential_patch = { upsert, delete_keys: deleteKeys.value }
    const result = isEdit.value ? await updateConnector(form.slug, payload) : await createConnector(payload)
    revision.value = result.data.revision
    clearCredentials()
    message.success(isEdit.value ? '连接器已更新' : '连接器已创建')
    emit('saved')
  } catch (error) { message.error(error.message || '保存失败') } finally { saving.value = false }
}
</script>

<style scoped>
.connector-config-form { max-height: 68vh; overflow-y: auto; padding-right: 8px; }
.credential-hint { margin-top: 4px; color: var(--gray-500); font-size: 12px; }
.connector-guide { margin-bottom: 16px; padding: 12px; border: 1px solid var(--gray-150); border-radius: 8px; }
.connector-guide summary { cursor: pointer; color: var(--main-color); }
.connector-guide li { margin: 8px 0; }
.connector-guide code { overflow-wrap: anywhere; }
.metadata-field-row { display: flex; align-items: center; gap: 12px; margin: 8px 0; }
.metadata-field-row .ant-input { max-width: 180px; }
@media (max-width: 600px) { .metadata-field-row { flex-wrap: wrap; } }
</style>
