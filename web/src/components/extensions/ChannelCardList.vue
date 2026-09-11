<template>
  <div class="channel-cards-page extension-page-root">
    <!-- 支持的渠道 -->
    <div class="channel-section">
      <div class="channel-section-header">
        <span class="channel-section-title">支持的渠道</span>
        <a-tooltip title="刷新" placement="bottom">
          <button
            type="button"
            class="channel-section-action"
            :disabled="loading"
            @click="fetchChannels"
          >
            <RefreshCw :size="14" />
          </button>
        </a-tooltip>
      </div>
      <div v-if="loading" class="extension-card-grid-empty-state">
        <a-spin />
      </div>
      <div v-else class="supported-channel-grid">
        <div
          v-for="ct in supportedChannelTypes"
          :key="ct.type"
          class="supported-channel-card"
          :class="{ 'has-instances': ct.count > 0 }"
          @click="handleAddForType(ct.type)"
        >
          <div class="supported-channel-icon">
            <img :src="ct.icon" :alt="ct.label" class="channel-icon-img" />
          </div>
          <div class="supported-channel-info">
            <span class="supported-channel-name">{{ ct.label }}</span>
            <span class="supported-channel-desc">{{ ct.description }}</span>
          </div>
          <div class="supported-channel-status">
            <span
              v-if="ct.count > 0"
              class="supported-channel-count"
              :class="ct.runningCount > 0 ? 'running' : 'configured'"
            >
              <span class="count-dot" />
              {{ ct.runningCount > 0 ? `${ct.runningCount} 运行中` : `已配置 ${ct.count}` }}
            </span>
            <span v-else class="supported-channel-count unconfigured">未配置</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 已添加的频道 -->
    <div class="channel-section">
      <div class="channel-section-header">
        <span class="channel-section-title">已添加的频道</span>
        <a-dropdown :trigger="['click']">
          <a-button type="primary" size="small" class="lucide-icon-btn">
            <BookOpen :size="14" />
            <span>添加频道</span>
          </a-button>
          <template #overlay>
            <a-menu @click="handleAddFromMenu">
              <a-menu-item key="feishu"><img src="/icons/feishu.png" alt="飞书" class="menu-icon-img" /> 飞书</a-menu-item>
              <a-menu-item key="dingtalk"><img src="/icons/dingtalk.png" alt="钉钉" class="menu-icon-img" /> 钉钉</a-menu-item>
              <a-menu-item key="wecom"><img src="/icons/wecom.png" alt="企业微信" class="menu-icon-img" /> 企业微信</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </div>

      <div
        v-if="!loading && !channels.length"
        class="extension-card-grid-empty-state"
      >
        <a-empty
          :image="false"
          description="暂无已添加的频道，点击上方按钮或上方渠道卡片添加"
        />
      </div>

      <ExtensionCardGrid v-else :min-width="300">
        <InfoCard
          v-for="ch in channels"
          :key="ch.slug"
          variant="mini"
          :title="ch.slug"
          :description="channelTypeLabel(ch.channel_type)"
          @click="handleEditChannel(ch)"
        >
          <template #icon>
            <img :src="channelTypeIcon(ch.channel_type)" :alt="channelTypeLabel(ch.channel_type)" class="info-card-channel-icon" />
          </template>
          <template #tags>
            <a-tag :color="ch.enabled ? 'green' : 'default'">
              {{ ch.enabled ? (ch.is_running ? '运行中' : '已启用') : '已禁用' }}
            </a-tag>
            <a-tag v-if="ch.agent_slug">{{ ch.agent_slug }}</a-tag>
          </template>
          <template #action>
            <button
              type="button"
              class="mcp-card-action mcp-card-action-danger"
              :aria-label="'删除频道'"
              @click.stop="handleDeleteChannel(ch)"
            >
              <Trash2 :size="15" class="action-icon action-icon-trash" />
            </button>
          </template>
        </InfoCard>
      </ExtensionCardGrid>
    </div>

    <!-- 创建/编辑弹窗 -->
    <a-modal
      v-model:open="showCreateModal"
      :title="editingChannel ? `编辑频道: ${editingChannel.slug}` : `添加频道 · ${channelTypeLabel(formState.channel_type)}`"
      :confirm-loading="submitLoading"
      @ok="handleSubmit"
      @cancel="resetForm"
      :width="520"
    >
      <a-form :model="formState" layout="vertical" class="channel-form">
        <a-form-item label="频道名称" required>
          <a-input
            v-model:value="formState.slug"
            placeholder="如: feishu-bot，用于唯一标识此频道"
            :disabled="!!editingChannel"
          />
        </a-form-item>
        <a-form-item label="目标 Agent">
          <a-select
            v-model:value="formState.agent_slug"
            placeholder="可选，默认 Agent"
            allow-clear
            show-search
            :filter-option="filterAgentOption"
            :options="agentOptions"
          />
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="formState.enabled" />
        </a-form-item>

        <a-divider>凭据配置</a-divider>
        <div class="channel-setup-guide">
          <BookOpen :size="14" class="channel-setup-guide-icon" />
          <div class="channel-setup-guide-body">
            <span>{{ CHANNEL_SETUP_GUIDES[formState.channel_type]?.hint }}</span>
            <a :href="CHANNEL_SETUP_GUIDES[formState.channel_type]?.url" target="_blank" rel="noopener noreferrer">查看官方配置指南 →</a>
          </div>
        </div>
        <!-- 飞书凭据 -->
        <template v-if="formState.channel_type === 'feishu'">
          <a-form-item label="App ID">
            <a-input v-model:value="formState.credentials.app_id" placeholder="飞书应用 App ID" />
          </a-form-item>
          <a-form-item label="App Secret">
            <a-input-password v-model:value="formState.credentials.app_secret" placeholder="飞书应用 App Secret" />
          </a-form-item>
          <a-form-item label="Verification Token">
            <a-input v-model:value="formState.credentials.verification_token" placeholder="事件订阅 Verification Token（可选）" />
          </a-form-item>
        </template>
        <!-- 钉钉凭据 -->
        <template v-if="formState.channel_type === 'dingtalk'">
          <a-form-item label="AppKey">
            <a-input v-model:value="formState.credentials.app_key" placeholder="钉钉应用 AppKey" />
          </a-form-item>
          <a-form-item label="AppSecret">
            <a-input-password v-model:value="formState.credentials.app_secret" placeholder="钉钉应用 AppSecret" />
          </a-form-item>
          <a-form-item label="AgentId">
            <a-input v-model:value="formState.credentials.agent_id" placeholder="应用 AgentId（工作通知必填）" />
          </a-form-item>
          <a-form-item label="群机器人 Webhook">
            <a-input v-model:value="formState.credentials.robot_webhook" placeholder="可选，群机器人发送模式" />
          </a-form-item>
          <a-form-item v-if="formState.credentials.robot_webhook" label="机器人签名密钥">
            <a-input-password v-model:value="formState.credentials.robot_secret" placeholder="可选" />
          </a-form-item>
        </template>
        <!-- 企业微信凭据 -->
        <template v-if="formState.channel_type === 'wecom'">
          <a-form-item label="CorpID">
            <a-input v-model:value="formState.credentials.corp_id" placeholder="企业微信 CorpID" />
          </a-form-item>
          <a-form-item label="CorpSecret">
            <a-input-password v-model:value="formState.credentials.corp_secret" placeholder="应用 Secret" />
          </a-form-item>
          <a-form-item label="AgentId">
            <a-input v-model:value="formState.credentials.agent_id" placeholder="应用 AgentId" />
          </a-form-item>
          <a-form-item label="回调 Token">
            <a-input v-model:value="formState.credentials.token" placeholder="回调配置 Token" />
          </a-form-item>
        </template>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { message } from 'ant-design-vue'
import { BookOpen, RefreshCw, Trash2 } from '@lucide/vue'
import ExtensionCardGrid from './ExtensionCardGrid.vue'
import InfoCard from '@/components/shared/InfoCard.vue'
import { channelApi } from '@/apis/channel_api'
import { agentApi } from '@/apis/agent_api'

const loading = ref(false)
const submitLoading = ref(false)
const channels = ref([])
const showCreateModal = ref(false)
const editingChannel = ref(null)
const agentOptions = ref([])

const formState = reactive({
  slug: '',
  channel_type: 'feishu',
  enabled: true,
  agent_slug: '',
  credentials: {}
})

const CHANNEL_TYPE_META = {
  feishu: { label: '飞书', icon: '/icons/feishu.png', description: 'Lark / 飞书开放平台' },
  dingtalk: { label: '钉钉', icon: '/icons/dingtalk.png', description: '钉钉开放平台' },
  wecom: { label: '企业微信', icon: '/icons/wecom.png', description: '企业微信 API' }
}

const CHANNEL_SETUP_GUIDES = {
  feishu: {
    hint: '在飞书开放平台创建企业自建应用，开启机器人能力，获取 App ID 和 App Secret。',
    url: 'https://open.feishu.cn/document/uQjL24SN/uk0Mz4jL5UDNzQnL5MDN'
  },
  dingtalk: {
    hint: '在钉钉开发者后台创建企业内部应用，添加机器人能力，获取 AppKey 和 AppSecret。',
    url: 'https://open.dingtalk.com/document/orgapp/the-creation-and-installation-of-the-application-robot-in-the'
  },
  wecom: {
    hint: '在企业微信管理后台创建自建应用，获取 CorpID、Secret 并配置接收消息回调。',
    url: 'https://developer.work.weixin.qq.com/document/path/90238'
  }
}

const channelTypeLabel = (type) => CHANNEL_TYPE_META[type]?.label || type
const channelTypeIcon = (type) => CHANNEL_TYPE_META[type]?.icon || '📡'

const fetchAgentOptions = async () => {
  try {
    const res = await agentApi.getAgents()
    agentOptions.value = (res.agents || []).map((agent) => ({
      label: agent.name || agent.slug,
      value: agent.slug
    }))
  } catch {
    agentOptions.value = []
  }
}

const filterAgentOption = (input, option) => {
  return option.label.toLowerCase().includes(input.toLowerCase())
}

const supportedChannelTypes = computed(() => {
  return Object.entries(CHANNEL_TYPE_META).map(([type, meta]) => {
    const instances = channels.value.filter((ch) => ch.channel_type === type)
    const runningCount = instances.filter((ch) => ch.enabled && ch.is_running).length
    return {
      type,
      label: meta.label,
      icon: meta.icon,
      description: meta.description,
      count: instances.length,
      runningCount
    }
  })
})

const fetchChannels = async () => {
  loading.value = true
  try {
    const res = await channelApi.listChannels()
    channels.value = res.data || []
  } catch (e) {
    message.error('加载频道列表失败')
  } finally {
    loading.value = false
  }
}

const handleAddFromMenu = ({ key }) => {
  handleAddForType(key)
}

const handleAddForType = (type) => {
  editingChannel.value = null
  formState.slug = ''
  formState.channel_type = type
  formState.enabled = true
  formState.agent_slug = ''
  formState.credentials = {}
  showCreateModal.value = true
  void fetchAgentOptions()
}

const handleEditChannel = (ch) => {
  editingChannel.value = ch
  formState.slug = ch.slug
  formState.channel_type = ch.channel_type
  formState.enabled = ch.enabled
  formState.agent_slug = ch.agent_slug || ''
  formState.credentials = {}
  showCreateModal.value = true
  void fetchAgentOptions()
}

const handleDeleteChannel = async (ch) => {
  try {
    await channelApi.deleteChannel(ch.slug)
    message.success(`频道 ${ch.slug} 已删除`)
    await fetchChannels()
  } catch (e) {
    message.error('删除频道失败')
  }
}

const handleSubmit = async () => {
  if (!formState.slug || !formState.channel_type) {
    message.warning('请填写频道名称')
    return
  }
  submitLoading.value = true
  try {
    const payload = {
      slug: formState.slug,
      channel_type: formState.channel_type,
      enabled: formState.enabled,
      agent_slug: formState.agent_slug || null,
      credentials: { ...formState.credentials }
    }
    if (editingChannel.value) {
      await channelApi.updateChannel(editingChannel.value.slug, {
        enabled: payload.enabled,
        credentials: Object.keys(payload.credentials).length ? payload.credentials : undefined,
        agent_slug: payload.agent_slug
      })
      message.success('频道已更新')
    } else {
      await channelApi.createChannel(payload)
      message.success('频道已创建')
    }
    showCreateModal.value = false
    resetForm()
    await fetchChannels()
  } catch (e) {
    message.error(editingChannel.value ? '更新频道失败' : '创建频道失败')
  } finally {
    submitLoading.value = false
  }
}

const resetForm = () => {
  editingChannel.value = null
  formState.slug = ''
  formState.channel_type = 'feishu'
  formState.enabled = true
  formState.agent_slug = ''
  formState.credentials = {}
}

onMounted(() => {
  fetchChannels()
})
</script>

<style scoped lang="less">
@import '@/assets/css/extensions.less';

.channel-section {
  &:not(:first-child) {
    margin-top: 8px;
    border-top: 1px solid var(--gray-100);
    padding-top: 16px;
  }
}

.channel-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--page-padding) 12px;
}

.channel-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--gray-500);
  letter-spacing: 0.4px;
  text-transform: uppercase;
}

.channel-section-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-500);
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover:not(:disabled) {
    border-color: var(--gray-200);
    color: var(--gray-700);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.supported-channel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  padding: 0 var(--page-padding) 16px;
}

.supported-channel-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  cursor: pointer;
  transition: all 0.2s ease;

  &:hover {
    border-color: var(--main-200);
    background: var(--main-10);
  }

  &.has-instances {
    border-color: var(--gray-200);
  }
}

.supported-channel-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--gray-50);
  overflow: hidden;
}

.channel-icon-img {
  width: 28px;
  height: 28px;
  object-fit: contain;
}

.info-card-channel-icon {
  width: 20px;
  height: 20px;
  object-fit: contain;
}

.menu-icon-img {
  width: 16px;
  height: 16px;
  object-fit: contain;
  vertical-align: middle;
  margin-right: 4px;
}

.supported-channel-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.supported-channel-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-900);
}

.supported-channel-desc {
  font-size: 12px;
  color: var(--gray-500);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.supported-channel-status {
  flex-shrink: 0;
}

.supported-channel-count {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 999px;

  .count-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    display: inline-block;
  }

  &.running {
    background: var(--color-success-50);
    color: var(--color-success-700);

    .count-dot {
      background: var(--color-success-500);
    }
  }

  &.configured {
    background: var(--color-info-50, var(--gray-100));
    color: var(--color-info-700, var(--gray-600));

    .count-dot {
      background: var(--gray-400);
    }
  }

  &.unconfigured {
    background: var(--gray-50);
    color: var(--gray-400);
  }
}

.channel-form {
  padding-top: 8px;
}

.channel-setup-guide {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  margin-bottom: 16px;
  border-radius: 8px;
  background: var(--color-info-50, #f0f5ff);
  border: 1px solid var(--color-info-100, #d6e4ff);
  font-size: 13px;
  color: var(--gray-700);
  line-height: 1.5;

  a {
    color: var(--main-600);
    text-decoration: none;
    white-space: nowrap;

    &:hover {
      text-decoration: underline;
    }
  }
}

.channel-setup-guide-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--main-500, #1677ff);
}

.channel-setup-guide-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
