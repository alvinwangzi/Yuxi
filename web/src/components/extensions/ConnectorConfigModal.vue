<template>
  <a-modal
    :open="open"
    :title="isEdit ? `编辑连接器 — ${connector?.name}` : '添加连接器'"
    :width="640"
    :destroy-on-close="true"
    :confirm-loading="saving"
    @ok="handleSave"
    @cancel="handleClose"
  >
    <a-form layout="vertical" class="connector-config-form">
      <a-form-item label="名称" required>
        <a-input v-model:value="form.name" placeholder="连接器显示名称" />
      </a-form-item>

      <a-form-item v-if="!isEdit" label="标识 (slug)" required>
        <a-input
          v-model:value="form.slug"
          placeholder="英文标识，如 salesforce_prod"
          :disabled="isEdit"
        />
      </a-form-item>

      <a-form-item label="类型" required>
        <a-select v-model:value="form.connector_type" placeholder="选择连接器类型">
          <a-select-option v-for="t in connectorTypes" :key="t.type" :value="t.type">
            {{ TYPE_LABELS[t.type] || t.type }}
          </a-select-option>
        </a-select>
      </a-form-item>

      <a-form-item label="描述">
        <a-textarea v-model:value="form.description" :rows="2" placeholder="连接器用途说明" />
      </a-form-item>

      <a-form-item label="启用状态">
        <a-switch v-model:checked="form.enabled" />
      </a-form-item>

      <a-divider>认证配置</a-divider>

      <a-form-item label="认证方式">
        <a-select v-model:value="form.auth_type" placeholder="选择认证方式">
          <a-select-option value="none">无</a-select-option>
          <a-select-option value="bearer_token">Bearer Token</a-select-option>
          <a-select-option value="basic_auth">Basic Auth</a-select-option>
          <a-select-option value="oauth2_client">OAuth2 Client Credentials</a-select-option>
          <a-select-option value="api_key">API Key</a-select-option>
        </a-select>
      </a-form-item>

      <template v-if="form.auth_type === 'bearer_token'">
        <a-form-item label="Token">
          <a-input-password
            v-model:value="credentialValues.token"
            placeholder="输入 Bearer Token（留空保持不变）"
          />
          <div v-if="isEdit && hasExistingCredential('token')" class="credential-hint">
            已配置，留空保持当前值
          </div>
        </a-form-item>
      </template>

      <template v-if="form.auth_type === 'basic_auth'">
        <a-form-item label="用户名">
          <a-input v-model:value="credentialValues.username" placeholder="用户名" />
        </a-form-item>
        <a-form-item label="密码">
          <a-input-password
            v-model:value="credentialValues.password"
            placeholder="输入密码（留空保持不变）"
          />
        </a-form-item>
      </template>

      <template v-if="form.auth_type === 'oauth2_client'">
        <a-form-item label="Token URL">
          <a-input v-model:value="credentialValues.token_url" placeholder="https://..." />
        </a-form-item>
        <a-form-item label="Client ID">
          <a-input v-model:value="credentialValues.client_id" placeholder="Client ID" />
        </a-form-item>
        <a-form-item label="Client Secret">
          <a-input-password
            v-model:value="credentialValues.client_secret"
            placeholder="输入 Client Secret（留空保持不变）"
          />
        </a-form-item>
        <a-form-item label="Scope（可选）">
          <a-input v-model:value="credentialValues.scope" placeholder="space-separated scopes" />
        </a-form-item>
      </template>

      <template v-if="form.auth_type === 'api_key'">
        <a-form-item label="Header 名称">
          <a-input v-model:value="credentialValues.api_key_header" placeholder="X-API-Key" />
        </a-form-item>
        <a-form-item label="API Key">
          <a-input-password
            v-model:value="credentialValues.api_key_value"
            placeholder="输入 API Key（留空保持不变）"
          />
        </a-form-item>
      </template>

      <a-divider>目标地址</a-divider>

      <a-form-item label="Base URL">
        <a-input v-model:value="form.base_url" placeholder="https://api.example.com" />
      </a-form-item>

      <a-form-item label="标签">
        <a-select
          v-model:value="form.tags"
          mode="tags"
          placeholder="输入标签后回车"
        />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  createConnector,
  updateConnector,
  patchCredentials,
} from '@/apis/connector_api'

const TYPE_LABELS = {
  generic_rest: '通用 REST',
  salesforce: 'Salesforce',
  feishu_bitable_crm: '飞书多维表格',
}

const props = defineProps({
  open: Boolean,
  connector: Object,
  connectorTypes: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:open', 'saved'])

const isEdit = computed(() => !!props.connector?.slug)
const saving = ref(false)

const form = reactive({
  name: '',
  slug: '',
  connector_type: '',
  description: '',
  enabled: true,
  auth_type: 'none',
  base_url: '',
  tags: [],
})

const credentialValues = reactive({
  token: '',
  username: '',
  password: '',
  token_url: '',
  client_id: '',
  client_secret: '',
  scope: '',
  api_key_header: 'X-API-Key',
  api_key_value: '',
})

const existingCredentials = computed(() => {
  if (!props.connector?.credential_keys) return []
  return props.connector.credential_keys
})

function hasExistingCredential(key) {
  return existingCredentials.value.includes(key)
}

watch(
  () => props.open,
  (val) => {
    if (val && props.connector) {
      form.name = props.connector.name || ''
      form.slug = props.connector.slug || ''
      form.connector_type = props.connector.connector_type || ''
      form.description = props.connector.description || ''
      form.enabled = props.connector.enabled !== false
      form.auth_type = props.connector.auth_type || 'none'
      form.base_url = props.connector.base_url || ''
      form.tags = props.connector.tags || []
      // 清空凭据输入
      Object.keys(credentialValues).forEach((k) => { credentialValues[k] = '' })
    } else if (val) {
      Object.assign(form, {
        name: '', slug: '', connector_type: '', description: '',
        enabled: true, auth_type: 'none', base_url: '', tags: [],
      })
      Object.keys(credentialValues).forEach((k) => { credentialValues[k] = '' })
    }
  },
)

function handleClose() {
  emit('update:open', false)
}

async function handleSave() {
  if (!form.name || !form.slug || !form.connector_type) {
    message.warning('请填写名称、标识和类型')
    return
  }
  if (!isEdit.value && !/^[a-z0-9_-]+$/.test(form.slug)) {
    message.warning('标识只能包含小写字母、数字、下划线和连字符')
    return
  }

  saving.value = true
  try {
    const payload = {
      name: form.name,
      slug: form.slug,
      connector_type: form.connector_type,
      description: form.description,
      enabled: form.enabled,
      auth_type: form.auth_type,
      base_url: form.base_url,
      tags: form.tags,
    }

    let result
    if (isEdit.value) {
      result = await updateConnector(props.connector.slug, payload)
    } else {
      result = await createConnector(payload)
    }

    if (!result.success) {
      message.error(result.message || '保存失败')
      return
    }

    // 保存凭据（如果有填写）
    const credPayload = buildCredentialPayload()
    if (Object.keys(credPayload).length > 0) {
      const credResult = await patchCredentials(form.slug, credPayload)
      if (!credResult.success) {
        message.warning('连接器已保存，但凭据更新失败：' + (credResult.message || ''))
        emit('saved')
        return
      }
    }

    message.success(isEdit.value ? '连接器已更新' : '连接器已创建')
    emit('saved')
  } catch (err) {
    message.error(err.message || '保存失败')
  } finally {
    saving.value = false
  }
}

function buildCredentialPayload() {
  const cred = {}
  switch (form.auth_type) {
    case 'bearer_token':
      if (credentialValues.token) cred.token = credentialValues.token
      break
    case 'basic_auth':
      if (credentialValues.username) cred.username = credentialValues.username
      if (credentialValues.password) cred.password = credentialValues.password
      break
    case 'oauth2_client':
      if (credentialValues.token_url) cred.token_url = credentialValues.token_url
      if (credentialValues.client_id) cred.client_id = credentialValues.client_id
      if (credentialValues.client_secret) cred.client_secret = credentialValues.client_secret
      if (credentialValues.scope) cred.scope = credentialValues.scope
      break
    case 'api_key':
      if (credentialValues.api_key_header) cred.api_key_header = credentialValues.api_key_header
      if (credentialValues.api_key_value) cred.api_key_value = credentialValues.api_key_value
      break
  }
  return cred
}
</script>

<style lang="less" scoped>
.connector-config-form {
  max-height: 60vh;
  overflow-y: auto;
  padding-right: 4px;
}

.credential-hint {
  margin-top: 4px;
  color: var(--gray-500);
  font-size: 12px;
}
</style>
