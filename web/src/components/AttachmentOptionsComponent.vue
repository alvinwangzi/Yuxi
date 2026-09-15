<template>
  <div
    class="config-dropdown-panel attachment-options-panel"
    :class="{ 'is-workspace-browsing': activeResourceType === 'workspace' }"
    role="menu"
    :aria-label="activeResourceType ? `${activeResourceLabel}选择` : '添加内容'"
    @click.stop
  >
    <template v-if="!activeResourceType">
      <template v-if="fileUploadEnabled">
        <button
          type="button"
          role="menuitem"
          class="config-dropdown-item"
          :class="{ disabled }"
          :disabled="disabled"
          title="支持任意文件格式 ≤ 5 MB"
          @click="handleAttachmentClick"
        >
          <FileText :size="15" class="config-dropdown-item-icon" />
          <span class="config-dropdown-item-label">添加附件</span>
        </button>

        <button
          type="button"
          role="menuitem"
          class="config-dropdown-item"
          :class="{ disabled }"
          :disabled="disabled"
          title="支持 jpg/jpeg/png/gif，≤ 5 MB"
          @click="handleImageUpload"
        >
          <Image :size="15" class="config-dropdown-item-icon" />
          <span class="config-dropdown-item-label">上传图片</span>
        </button>
      </template>

      <div v-if="fileUploadEnabled && hasMentionResources" class="config-dropdown-divider"></div>

      <button
        v-for="group in visibleResourceGroups"
        :key="group.key"
        type="button"
        role="menuitem"
        class="config-dropdown-item"
        :disabled="disabled"
        :class="{ disabled }"
        @click="activeResourceType = group.key"
      >
        <component :is="group.icon" :size="15" class="config-dropdown-item-icon" />
        <span class="config-dropdown-item-label">{{ group.label }}</span>
        <ChevronRight :size="14" class="attachment-options-chevron" />
      </button>
    </template>

    <template v-else-if="activeResourceType === 'workspace'">
      <button
        type="button"
        class="attachment-options-back"
        aria-label="返回添加内容菜单"
        @click="closeWorkspaceBrowser"
      >
        <ArrowLeft :size="15" />
        <span>{{ activeResourceLabel }}</span>
      </button>

      <div class="config-dropdown-divider"></div>

      <!-- 面包屑导航 -->
      <div class="workspace-breadcrumb" v-if="workspacePath !== '/'">
        <button
          type="button"
          class="breadcrumb-item breadcrumb-root"
          @click="navigateToPath('/')"
          title="根目录"
        >
          <HardDrive :size="13" />
        </button>
        <template v-for="(segment, idx) in breadcrumbSegments" :key="idx">
          <ChevronRight :size="12" class="breadcrumb-separator" />
          <button
            type="button"
            class="breadcrumb-item"
            :class="{ 'breadcrumb-current': idx === breadcrumbSegments.length - 1 }"
            @click="navigateToBreadcrumb(idx)"
            :title="segment"
          >
            {{ segment }}
          </button>
        </template>
      </div>

      <!-- 文件/文件夹列表 -->
      <div class="workspace-file-list">
        <div v-if="workspaceLoading" class="workspace-empty">
          <span class="workspace-loading-spinner"></span>
          <span>加载中...</span>
        </div>
        <div v-else-if="workspaceError" class="workspace-empty error-state">
          <span>{{ workspaceError }}</span>
          <a-button type="link" size="small" @click="loadWorkspaceEntries">重试</a-button>
        </div>
        <div v-else-if="!workspaceEntries.length" class="workspace-empty">
          <span>目录为空</span>
        </div>
        <template v-else>
          <button
            v-for="entry in sortedWorkspaceEntries"
            :key="entry.path"
            type="button"
            role="menuitem"
            class="config-dropdown-item workspace-entry-item"
            :class="{ 'is-dir': entry.is_dir }"
            @click="handleWorkspaceEntryClick(entry)"
          >
            <FileTypeIcon
              :name="entry.path"
              :is-dir="entry.is_dir"
              :size="15"
              class="config-dropdown-item-icon"
            />
            <span class="config-dropdown-item-label workspace-entry-name" :title="entry.name">
              {{ entry.name }}
            </span>
            <ChevronRight v-if="entry.is_dir" :size="13" class="attachment-options-chevron" />
          </button>
        </template>
      </div>
    </template>

    <template v-else>
      <button
        type="button"
        class="attachment-options-back"
        aria-label="返回添加内容菜单"
        @click="activeResourceType = ''"
      >
        <ArrowLeft :size="15" />
        <span>{{ activeResourceLabel }}</span>
      </button>

      <div class="config-dropdown-divider"></div>

      <div class="attachment-resource-list">
        <button
          v-for="item in activeResourceItems"
          :key="`${item.type}-${item.value}`"
          type="button"
          role="menuitem"
          class="config-dropdown-item attachment-resource-item"
          :title="item.description || item.label"
          @click="selectMention(item)"
        >
          <component
            :is="getMentionIconComponent(item.type, item.value)"
            :size="15"
            class="config-dropdown-item-icon"
          />
          <span class="attachment-resource-content">
            <span class="config-dropdown-item-label">{{ item.label }}</span>
            <span class="attachment-resource-description">
              {{ item.description || '暂无描述' }}
            </span>
          </span>
        </button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowLeft, ChevronRight, Database, FileText, HardDrive, Image, WandSparkles } from '@lucide/vue'
import { message } from 'ant-design-vue'
import { uploadMultimodalImage } from '@/utils/multimodal_image_upload'
import { getMentionIconComponent } from '@/utils/mention_icon_utils'
import { buildMentionResourceItems } from '@/utils/mention_resource_items'
import { formatMentionToken } from '@/utils/mention_token'
import { getWorkspaceTree } from '@/apis/workspace_api'
import FileTypeIcon from '@/components/common/FileTypeIcon.vue'

const VIRTUAL_PATH_PREFIX = '/home/gem/user-data'

const RESOURCE_GROUPS = [
  { key: 'knowledgeBases', label: '知识库', icon: Database },
  { key: 'skills', label: '技能', icon: WandSparkles },
  { key: 'workspace', label: '个人空间', icon: HardDrive }
]

const props = defineProps({
  disabled: {
    type: Boolean,
    default: false
  },
  fileUploadEnabled: {
    type: Boolean,
    default: false
  },
  mention: {
    type: Object,
    default: () => null
  }
})

const emit = defineEmits(['upload', 'upload-image', 'upload-image-success', 'select-mention'])
const activeResourceType = ref('')
const resourceItems = computed(() => buildMentionResourceItems(props.mention || {}))
const visibleResourceGroups = computed(() =>
  RESOURCE_GROUPS.filter((group) => {
    if (group.key === 'workspace') return true
    return resourceItems.value[group.key].length
  })
)
const hasMentionResources = computed(() => visibleResourceGroups.value.length > 0)
const activeResourceItems = computed(() => resourceItems.value[activeResourceType.value] || [])
const activeResourceLabel = computed(
  () => RESOURCE_GROUPS.find((group) => group.key === activeResourceType.value)?.label ?? ''
)

// 个人空间浏览器状态
const workspacePath = ref('/')
const workspaceEntries = ref([])
const workspaceLoading = ref(false)
const workspaceError = ref('')

const workspaceToRuntimePath = (workspacePath) => {
  const clean = String(workspacePath || '/').replace(/^\/+/, '/')
  if (clean === '/') return VIRTUAL_PATH_PREFIX
  return `${VIRTUAL_PATH_PREFIX}${clean}`
}

const extractFileName = (path) => {
  const clean = String(path || '').replace(/\/$/, '')
  const lastSlash = clean.lastIndexOf('/')
  return lastSlash >= 0 ? clean.substring(lastSlash + 1) : clean
}

const breadcrumbSegments = computed(() => {
  if (workspacePath.value === '/') return []
  return workspacePath.value.split('/').filter(Boolean)
})

const sortedWorkspaceEntries = computed(() => {
  return [...workspaceEntries.value].sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1
    return a.name.localeCompare(b.name, 'zh-Hans-CN')
  })
})

const loadWorkspaceEntries = async () => {
  workspaceLoading.value = true
  workspaceError.value = ''
  try {
    const res = await getWorkspaceTree(workspacePath.value)
    workspaceEntries.value = (res?.entries || []).map((entry) => ({
      path: entry.path,
      name: extractFileName(entry.path),
      is_dir: Boolean(entry.is_dir)
    }))
  } catch (error) {
    workspaceError.value = error?.message || '加载失败'
    console.error('加载个人空间目录失败:', error)
  } finally {
    workspaceLoading.value = false
  }
}

const navigateToPath = (path) => {
  workspacePath.value = path
  void loadWorkspaceEntries()
}

const navigateToBreadcrumb = (index) => {
  const target = '/' + breadcrumbSegments.value.slice(0, index + 1).join('/')
  navigateToPath(target)
}

const handleWorkspaceEntryClick = (entry) => {
  if (entry.is_dir) {
    navigateToPath(entry.path)
  } else {
    const runtimePath = workspaceToRuntimePath(entry.path)
    const fileName = entry.name
    selectMention({
      value: runtimePath,
      label: fileName,
      type: 'file',
      insertValue: runtimePath,
      tokenLabel: formatMentionToken('file', fileName),
      description: runtimePath
    })
  }
}

const closeWorkspaceBrowser = () => {
  activeResourceType.value = ''
  workspacePath.value = '/'
  workspaceEntries.value = []
}

watch(activeResourceType, (newType) => {
  if (newType === 'workspace') {
    void loadWorkspaceEntries()
  }
})

const handleAttachmentClick = () => {
  if (props.disabled) return
  emit('upload')
}

// 处理图片上传
const handleImageUpload = () => {
  if (props.disabled) return

  // 创建隐藏的文件输入
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.multiple = false
  input.style.display = 'none'

  input.onchange = async (event) => {
    const file = event.target.files[0]
    if (file) {
      await processImageUpload(file)
    }
    document.body.removeChild(input)
  }

  document.body.appendChild(input)
  input.click()

  emit('upload-image')
}

const selectMention = (item) => {
  if (props.disabled) return
  emit('select-mention', item)
  activeResourceType.value = ''
}

// 处理图片上传逻辑
const processImageUpload = async (file) => {
  try {
    const imageData = await uploadMultimodalImage(file)
    if (!imageData) return

    // 发出上传成功事件，包含处理后的图片数据
    emit('upload-image', imageData)

    // 发出上传成功通知事件，用于关闭选项面板
    emit('upload-image-success')
  } catch (error) {
    console.error('图片上传失败:', error)
    message.error({
      content: `图片上传失败: ${error.message || '未知错误'}`,
      key: 'image-upload'
    })
  }
}
</script>

<style lang="less" scoped>
.attachment-options-panel {
  width: 240px;

  &.is-workspace-browsing {
    width: 300px;
  }
}

.attachment-options-chevron {
  flex-shrink: 0;
  color: var(--gray-400);
}

.attachment-options-back {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  border-radius: 6px;
  color: var(--gray-800);
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  transition: background-color 0.15s ease;

  &:hover,
  &:focus-visible {
    background: var(--gray-50);
  }
}

.attachment-resource-list {
  max-height: min(320px, calc(100vh - 180px));
  overflow-y: auto;
}

.attachment-options-panel .attachment-resource-item {
  gap: 10px;
}

.attachment-resource-content {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.attachment-resource-description {
  overflow: hidden;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-file-list {
  max-height: min(360px, calc(100vh - 200px));
  overflow-y: auto;
}

.workspace-entry-item {
  gap: 8px;

  &.is-dir {
    .workspace-entry-name {
      font-weight: 500;
    }
  }
}

.workspace-entry-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.workspace-breadcrumb {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 8px;
  font-size: 12px;
  flex-wrap: wrap;
  min-height: 28px;
}

.breadcrumb-item {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--gray-500);
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: all 0.15s ease;

  &:hover {
    background: var(--gray-100);
    color: var(--gray-800);
  }

  &.breadcrumb-root {
    padding: 2px 4px;
    color: var(--main-500);

    &:hover {
      color: var(--main-600);
    }
  }

  &.breadcrumb-current {
    color: var(--gray-800);
    font-weight: 500;
    cursor: default;

    &:hover {
      background: transparent;
    }
  }
}

.breadcrumb-separator {
  color: var(--gray-300);
  flex-shrink: 0;
}

.workspace-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 20px 12px;
  color: var(--gray-400);
  font-size: 13px;

  &.error-state {
    flex-direction: column;
    gap: 4px;
  }
}

.workspace-loading-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--gray-200);
  border-top-color: var(--main-500);
  border-radius: 50%;
  animation: workspace-loading-spin 0.8s linear infinite;
}

@keyframes workspace-loading-spin {
  to {
    transform: rotate(360deg);
  }
}

:deep(.config-dropdown-item:focus-visible) {
  outline: 2px solid var(--main-300);
  outline-offset: -2px;
}
</style>
