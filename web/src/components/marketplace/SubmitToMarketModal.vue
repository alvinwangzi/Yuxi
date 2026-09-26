<template>
  <a-modal
    v-model:open="visible"
    title="提交到公司技能市场"
    :confirm-loading="submitting"
    @ok="handleSubmit"
    @cancel="handleCancel"
    ok-text="提交"
    cancel-text="取消"
  >
    <a-form :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
      <a-form-item label="技能名称" required>
        <a-input v-model:value="form.title" placeholder="在市场展示的名称" />
      </a-form-item>
      <a-form-item label="技能描述" required>
        <a-textarea v-model:value="form.description" :rows="3" placeholder="面向使用者的功能说明" />
      </a-form-item>
      <a-form-item label="技能分类">
        <a-select v-model:value="form.category_id" placeholder="选择分类（可选）" allow-clear>
          <a-select-option v-for="cat in categories" :key="cat.id" :value="cat.id">
            {{ cat.label }}
          </a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item label="更新类型" required>
        <a-select v-model:value="form.change_type" placeholder="选择更新类型">
          <a-select-option value="minor" :disabled="!isUpdate">新增功能（次版本号 +1）</a-select-option>
          <a-select-option value="patch" :disabled="!isUpdate">修复优化（修订号 +1）</a-select-option>
          <a-select-option value="major" :disabled="!isUpdate">不兼容变更（主版本号 +1）</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item label="提交说明">
        <a-textarea v-model:value="form.submission_note" :rows="2" placeholder="向管理员说明为什么上架或更新了什么" />
      </a-form-item>
      <a-form-item label="预览版本号">
        <a-tag color="blue">{{ previewVersion }}</a-tag>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { marketplaceApi } from '@/apis/marketplace_api'
import { categoryApi } from '@/apis/category_api'

const props = defineProps({
  skillId: { type: Number, required: true },
  skillName: { type: String, default: '' },
  skillDescription: { type: String, default: '' },
  skillCategoryId: { type: Number, default: null },
  isUpdate: { type: Boolean, default: false },
})

const emit = defineEmits(['success', 'cancel'])

const visible = ref(true)
const submitting = ref(false)
const categories = ref([])
const form = reactive({
  title: props.skillName || '',
  description: props.skillDescription || '',
  category_id: props.skillCategoryId || null,
  change_type: 'minor',
  submission_note: '',
})

// 加载分类列表
onMounted(async () => {
  try {
    const res = await categoryApi.list('skill')
    if (res.success) {
      categories.value = res.data || []
    }
  } catch {
    // 静默失败，分类为可选项
  }
})

const previewVersion = computed(() => {
  if (!props.isUpdate) return '1.0.0'
  return '（基于现有版本递增）'
})

const handleSubmit = async () => {
  if (!form.title || !form.description) {
    message.warning('请填写技能名称和描述')
    return
  }
  if (!form.change_type) {
    message.warning('请选择更新类型')
    return
  }

  submitting.value = true
  try {
    const res = await marketplaceApi.submitToMarket({
      original_skill_id: props.skillId,
      title: form.title,
      description: form.description,
      category_id: form.category_id,
      change_type: form.change_type,
      submission_note: form.submission_note,
    })
    if (res.success) {
      message.success('提交成功，等待管理员审批')
      emit('success')
    }
  } catch (err) {
    message.error(err.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

const handleCancel = () => {
  visible.value = false
  emit('cancel')
}
</script>
