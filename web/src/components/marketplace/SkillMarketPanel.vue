<template>
  <div class="skill-market-panel">
    <!-- 页面头部 -->
    <div class="panel-header">
      <div class="header-left">
        <h2 class="panel-title">技能市场</h2>
        <p class="panel-description">浏览和安装系统内置技能与公司精选技能</p>
      </div>
      <div class="header-right">
        <a-input-search
          v-model:value="searchQuery"
          placeholder="搜索技能..."
          style="width: 250px"
          @search="handleSearch"
        />
      </div>
    </div>

    <!-- 分类筛选 -->
    <div class="category-filter">
      <a-tabs v-model:activeKey="activeSourceType" @change="handleSourceTypeChange">
        <a-tab-pane key="all" tab="全部" />
        <a-tab-pane key="builtin" tab="系统内置" />
        <a-tab-pane key="company" tab="公司精选" />
      </a-tabs>
    </div>

    <!-- 技能列表 -->
    <a-spin :spinning="loading">
      <div class="skill-grid" v-if="filteredEntries.length > 0">
        <div
          v-for="entry in filteredEntries"
          :key="entry.id"
          class="skill-card"
          @click="showDetail(entry)"
        >
          <div class="card-header">
            <div class="card-title">
              <span class="skill-icon">🔧</span>
              <span class="skill-name">{{ entry.title }}</span>
            </div>
            <a-tag v-if="entry.source_type === 'builtin'" color="blue">内置</a-tag>
            <a-tag v-else color="green">公司</a-tag>
          </div>
          <div class="card-body">
            <p class="skill-description">{{ entry.description }}</p>
          </div>
          <div class="card-footer">
            <div class="skill-meta">
              <span class="meta-item">
                <UserOutlined />
                {{ entry.author_uid || '未知' }}
              </span>
              <span class="meta-item">
                <DownloadOutlined />
                {{ entry.install_count }}
              </span>
            </div>
            <a-button
              type="primary"
              size="small"
              :loading="installingSlug === entry.slug"
              @click.stop="handleInstall(entry)"
            >
              安装
            </a-button>
          </div>
        </div>
      </div>
      <a-empty v-else description="暂无技能" />
    </a-spin>

    <!-- 详情抽屉 -->
    <a-drawer
      v-model:open="detailVisible"
      :title="selectedEntry?.title"
      width="600"
      :body-style="{ paddingBottom: '80px' }"
    >
      <template v-if="selectedEntry">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="描述">{{ selectedEntry.description }}</a-descriptions-item>
          <a-descriptions-item label="来源">
            <a-tag v-if="selectedEntry.source_type === 'builtin'" color="blue">系统内置</a-tag>
            <a-tag v-else color="green">公司精选</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="贡献者">{{ selectedEntry.author_uid || '未知' }}</a-descriptions-item>
          <a-descriptions-item label="安装次数">{{ selectedEntry.install_count }}</a-descriptions-item>
        </a-descriptions>

        <div class="detail-actions" style="margin-top: 24px">
          <a-button
            type="primary"
            :loading="installingSlug === selectedEntry.slug"
            @click="handleInstall(selectedEntry)"
          >
            安装到个人技能
          </a-button>
        </div>

        <a-divider>版本历史</a-divider>
        <a-timeline>
          <a-timeline-item
            v-for="version in selectedEntry.versions"
            :key="version.id"
            :color="version.is_latest ? 'green' : 'gray'"
          >
            <div class="version-item">
              <div class="version-header">
                <strong>v{{ version.version }}</strong>
                <a-tag v-if="version.is_latest" color="green">最新</a-tag>
                <a-tag>{{ version.change_type }}</a-tag>
              </div>
              <p class="version-notes">{{ version.release_notes || '无说明' }}</p>
              <div class="version-meta">
                <span>{{ version.submitted_by }}</span>
                <span>{{ formatDate(version.submitted_at) }}</span>
              </div>
            </div>
          </a-timeline-item>
        </a-timeline>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { UserOutlined, DownloadOutlined } from '@ant-design/icons-vue'
import { marketplaceApi } from '@/apis/marketplace_api'

const loading = ref(false)
const entries = ref([])
const searchQuery = ref('')
const activeSourceType = ref('all')
const detailVisible = ref(false)
const selectedEntry = ref(null)
const installingSlug = ref(null)

const filteredEntries = computed(() => {
  let result = entries.value
  if (activeSourceType.value !== 'all') {
    result = result.filter(e => e.source_type === activeSourceType.value)
  }
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    result = result.filter(e =>
      e.title.toLowerCase().includes(query) ||
      e.description.toLowerCase().includes(query)
    )
  }
  return result
})

const loadEntries = async () => {
  loading.value = true
  try {
    const res = await marketplaceApi.listEntries({ page_size: 100 })
    if (res.success) {
      entries.value = res.items
    }
  } catch (err) {
    message.error('加载技能列表失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  // 搜索通过 computed 自动过滤
}

const handleSourceTypeChange = () => {
  // 切换通过 computed 自动过滤
}

const showDetail = async (entry) => {
  try {
    const res = await marketplaceApi.getEntryDetail(entry.slug)
    if (res.success) {
      selectedEntry.value = res.data
      detailVisible.value = true
    }
  } catch (err) {
    message.error('加载详情失败')
  }
}

const handleInstall = async (entry) => {
  installingSlug.value = entry.slug
  try {
    const res = await marketplaceApi.installSkill(entry.slug)
    if (res.success) {
      const statusMap = {
        installed: '安装成功',
        already_installed: '已安装最新版本',
        updated: '更新成功',
      }
      message.success(statusMap[res.data.status] || '操作成功')
      // 刷新列表以更新安装次数
      await loadEntries()
    }
  } catch (err) {
    message.error(err.response?.data?.detail || '安装失败')
  } finally {
    installingSlug.value = null
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN')
}

onMounted(() => {
  loadEntries()
})
</script>

<style scoped>
.skill-market-panel {
  padding: 24px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.panel-title {
  margin: 0 0 8px 0;
  font-size: 24px;
  font-weight: 600;
}

.panel-description {
  margin: 0;
  color: #666;
  font-size: 14px;
}

.category-filter {
  margin-bottom: 24px;
}

.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.skill-card {
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.3s;
  background: #fff;
}

.skill-card:hover {
  border-color: #1890ff;
  box-shadow: 0 2px 8px rgba(24, 144, 255, 0.15);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skill-icon {
  font-size: 20px;
}

.skill-name {
  font-weight: 600;
  font-size: 16px;
}

.card-body {
  margin-bottom: 12px;
}

.skill-description {
  margin: 0;
  color: #666;
  font-size: 14px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.skill-meta {
  display: flex;
  gap: 16px;
  color: #999;
  font-size: 12px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.version-item {
  padding: 8px 0;
}

.version-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.version-notes {
  margin: 8px 0;
  color: #666;
  font-size: 14px;
}

.version-meta {
  display: flex;
  justify-content: space-between;
  color: #999;
  font-size: 12px;
}
</style>
