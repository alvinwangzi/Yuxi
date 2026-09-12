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

    <!-- 已添加的渠道 -->
    <div class="channel-section">
      <div class="channel-section-header">
        <span class="channel-section-title">已添加的渠道</span>
        <a-dropdown :trigger="['click']">
          <a-button type="primary" size="small" class="lucide-icon-btn">
            <BookOpen :size="14" />
            <span>添加渠道</span>
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
          description="暂无已添加的渠道，点击上方按钮或上方渠道卡片添加"
        />
      </div>

      <ExtensionCardGrid v-else :min-width="300">
        <InfoCard
          v-for="ch in channels"
          :key="ch.slug"
          variant="mini"
          :title="ch.name || ch.slug"
          :description="channelCardDescription(ch)"
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
              :aria-label="'删除渠道'"
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
      :title="editingChannel ? `编辑渠道: ${editingChannel.name || editingChannel.slug}` : `添加渠道 · ${channelTypeLabel(formState.channel_type)}`"
      :confirm-loading="submitLoading"
      @ok="handleSubmit"
      @cancel="resetForm"
      :width="560"
    >
      <a-form :model="formState" layout="vertical" class="channel-form">
        <a-form-item label="渠道名称" required>
          <a-input
            v-model:value="formState.name"
            placeholder="如: 飞书客服机器人，用于显示"
          />
        </a-form-item>
        <a-form-item label="渠道标识" :required="!editingChannel">
          <a-input
            v-model:value="formState.slug"
            placeholder="如: feishu-bot，用于唯一标识（创建后不可修改）"
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
          <a-segmented
            v-if="!editingChannel"
            v-model:value="feishuConfigMode"
            :options="feishuConfigModeOptions"
            class="feishu-mode-segmented"
          />
          <!-- 一键扫码创建 -->
          <div v-if="feishuConfigMode === 'qrcode' && !editingChannel" class="feishu-qrcode-section">
            <div v-if="feishuRegLoading" class="feishu-qrcode-loading">
              <a-spin :size="'small'" />
              <span>正在获取二维码…</span>
            </div>
            <div v-else-if="feishuRegError" class="feishu-qrcode-error">
              <span>{{ feishuRegError }}</span>
              <a-button type="link" size="small" @click="startFeishuRegistration">重试</a-button>
            </div>
            <template v-else-if="feishuRegId">
              <div class="feishu-qrcode-wrapper">
                <img :src="feishuQrImgUrl" alt="飞书扫码二维码" class="feishu-qrcode-img" />
              </div>
              <p class="feishu-qrcode-hint">
                <template v-if="feishuRegStatus === 'completed'">
                  <span class="feishu-reg-success">
                    <a-spin v-if="submitLoading" :size="'small'" style="margin-right: 6px" />
                    ✓ 应用创建成功，正在自动创建渠道…
                  </span>
                </template>
                <template v-else>
                  使用飞书扫描上方二维码，一键创建应用并自动获取凭据
                </template>
              </p>
              <p v-if="feishuRegStatus === 'polling'" class="feishu-qrcode-polling">
                <a-spin :size="'small'" /> 等待扫码确认…
              </p>
            </template>
          </div>
          <!-- 手动填写 -->
          <template v-if="feishuConfigMode === 'manual' || editingChannel">
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
import { ref, reactive, onMounted, onUnmounted, computed, watch } from 'vue'
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

// ── 飞书一键扫码注册 ──────────────────────────────────
const feishuConfigMode = ref('qrcode')
const feishuConfigModeOptions = [
  { label: '扫码一键创建', value: 'qrcode' },
  { label: '手动填写', value: 'manual' }
]
const feishuRegId = ref('')
const feishuRegStatus = ref('') // init | qr_ready | polling | completed | error
const feishuRegLoading = ref(false)
const feishuRegError = ref('')
const feishuQrUrl = ref('')
const feishuRegExpireIn = ref(0)
let feishuPollTimer = null

const formState = reactive({
  slug: '',
  name: '',
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
    hint: '推荐使用「扫码一键创建」自动获取凭据；也可手动在飞书开放平台创建应用后填写凭据。',
    url: 'https://open.feishu.cn/document/mcp_open_tools/integrating-agents-with-feishu/overview'
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

/** 智能体 slug → 中文名映射 */
const agentNameMap = computed(() => {
  const map = {}
  for (const opt of agentOptions.value) {
    map[opt.value] = opt.label
  }
  return map
})

/** 获取渠道卡片描述：优先显示智能体中文名，其次渠道类型 */
const channelCardDescription = (ch) => {
  if (ch.agent_slug) {
    return agentNameMap.value[ch.agent_slug] || ch.agent_slug
  }
  return channelTypeLabel(ch.channel_type)
}

const filterAgentOption = (input, option) => {
  return option.label.toLowerCase().includes(input.toLowerCase())
}

/** 将飞书二维码 URL 转为可嵌入的 img 地址（使用公共 QR 生成服务）。 */
const feishuQrImgUrl = computed(() => {
  if (!feishuQrUrl.value) return ''
  const data = encodeURIComponent(feishuQrUrl.value)
  return `https://api.qrserver.com/v1/create-qr-code/?data=${data}&size=200x200&margin=8`
})

/** 发起飞书一键注册，获取二维码。 */
const startFeishuRegistration = async () => {
  feishuRegLoading.value = true
  feishuRegError.value = ''
  feishuRegId.value = ''
  feishuQrUrl.value = ''
  feishuRegStatus.value = ''
  stopFeishuPolling()
  try {
    const res = await channelApi.startFeishuRegistration()
    feishuRegId.value = res.registration_id
    feishuQrUrl.value = res.qr_url || ''
    feishuRegExpireIn.value = res.expire_in || 600
    feishuRegStatus.value = res.status || 'qr_ready'
    if (res.status === 'qr_ready' || res.status === 'polling') {
      startFeishuPolling()
    }
  } catch (e) {
    feishuRegError.value = e?.response?.data?.detail || '获取二维码失败，请重试'
  } finally {
    feishuRegLoading.value = false
  }
}

/** 轮询注册状态，直到完成或出错。 */
const startFeishuPolling = () => {
  stopFeishuPolling()
  feishuPollTimer = setInterval(async () => {
    if (!feishuRegId.value) {
      stopFeishuPolling()
      return
    }
    try {
      const res = await channelApi.getFeishuRegistrationStatus(feishuRegId.value)
      feishuRegStatus.value = res.status
      if (res.status === 'completed') {
        stopFeishuPolling()
        // 自动填入凭据
        formState.credentials.app_id = res.app_id
        formState.credentials.app_secret = res.app_secret
        // 自动生成渠道标识和名称（如果用户还没有填写）
        if (!formState.slug) {
          const suffix = (res.app_id || '').replace(/^cli_/, '').slice(0, 8) || Date.now().toString(36)
          formState.slug = `feishu-${suffix}`
        }
        if (!formState.name) {
          formState.name = `飞书渠道-${(res.app_id || '').replace(/^cli_/, '').slice(0, 6) || suffix}`
        }
        message.success('飞书应用创建成功，正在自动创建渠道…')
        // 自动提交表单，完成一键创建
        await handleSubmit()
      } else if (res.status === 'error') {
        stopFeishuPolling()
        feishuRegError.value = res.error || '注册失败'
      }
    } catch {
      // 网络错误时继续轮询
    }
  }, 2000)
}

const stopFeishuPolling = () => {
  if (feishuPollTimer) {
    clearInterval(feishuPollTimer)
    feishuPollTimer = null
  }
}

/** 切换到飞书扫码模式时自动发起注册。 */
watch(feishuConfigMode, (mode) => {
  if (mode === 'qrcode' && !feishuRegId.value && !feishuRegLoading.value) {
    void startFeishuRegistration()
  }
})

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
    channels.value = Array.isArray(res) ? res : (res?.data || [])
  } catch {
    message.error('加载渠道列表失败')
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
  formState.name = ''
  formState.channel_type = type
  formState.enabled = true
  formState.agent_slug = ''
  formState.credentials = {}
  // 重置飞书一键注册状态
  resetFeishuRegistration()
  showCreateModal.value = true
  void fetchAgentOptions()
  // 飞书默认扫码模式，自动发起注册
  if (type === 'feishu') {
    feishuConfigMode.value = 'qrcode'
    void startFeishuRegistration()
  } else {
    feishuConfigMode.value = 'qrcode'
  }
}

const handleEditChannel = (ch) => {
  editingChannel.value = ch
  formState.slug = ch.slug
  formState.name = ch.name || ''
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
    message.success(`渠道 ${ch.slug} 已删除`)
    await fetchChannels()
  } catch {
    message.error('删除渠道失败')
  }
}

const handleSubmit = async () => {
  if (!formState.slug || !formState.channel_type) {
    message.warning('请填写渠道标识')
    return
  }
  submitLoading.value = true
  try {
    const payload = {
      slug: formState.slug,
      name: formState.name || null,
      channel_type: formState.channel_type,
      enabled: formState.enabled,
      agent_slug: formState.agent_slug || null,
      credentials: { ...formState.credentials }
    }
    if (editingChannel.value) {
      await channelApi.updateChannel(editingChannel.value.slug, {
        name: payload.name,
        enabled: payload.enabled,
        credentials: Object.keys(payload.credentials).length ? payload.credentials : undefined,
        agent_slug: payload.agent_slug
      })
      message.success('渠道已更新')
    } else {
      await channelApi.createChannel(payload)
      message.success('渠道已创建')
    }
    showCreateModal.value = false
    resetForm()
    await fetchChannels()
  } catch {
    message.error(editingChannel.value ? '更新渠道失败' : '创建渠道失败')
  } finally {
    submitLoading.value = false
  }
}

const resetFeishuRegistration = () => {
  stopFeishuPolling()
  feishuRegId.value = ''
  feishuRegStatus.value = ''
  feishuRegLoading.value = false
  feishuRegError.value = ''
  feishuQrUrl.value = ''
  feishuRegExpireIn.value = 0
}

const resetForm = () => {
  editingChannel.value = null
  formState.slug = ''
  formState.name = ''
  formState.channel_type = 'feishu'
  formState.enabled = true
  formState.agent_slug = ''
  formState.credentials = {}
  resetFeishuRegistration()
  feishuConfigMode.value = 'qrcode'
}

onMounted(() => {
  fetchChannels()
})

onUnmounted(() => {
  stopFeishuPolling()
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

.feishu-mode-segmented {
  margin-bottom: 16px;
  width: 100%;
}

.feishu-qrcode-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0 4px;
}

.feishu-qrcode-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 24px 0;
  color: var(--gray-500);
  font-size: 13px;
}

.feishu-qrcode-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 16px 0;
  color: var(--color-danger-600, var(--gray-600));
  font-size: 13px;
}

.feishu-qrcode-wrapper {
  display: flex;
  justify-content: center;
  padding: 8px;
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  background: var(--gray-0);
}

.feishu-qrcode-img {
  width: 200px;
  height: 200px;
  display: block;
}

.feishu-qrcode-hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--gray-500);
  text-align: center;
  line-height: 1.5;
}

.feishu-qrcode-polling {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--main-500);
}

.feishu-reg-success {
  color: var(--color-success-600);
  font-weight: 500;
}
</style>
