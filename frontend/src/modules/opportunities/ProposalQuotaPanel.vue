<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { ApiError } from '@/api/client'
import { useOpportunityStore, type ProposalQuota } from '@/modules/opportunities/store'

defineProps<{
  compact?: boolean
}>()

const opportunities = useOpportunityStore()
const quota = ref<ProposalQuota | null>(null)
const errorText = ref('')

const alertType = computed(() => {
  if (!quota.value) return 'info'
  return quota.value.is_below_minimum ? 'warning' : 'success'
})

const description = computed(() => {
  if (!quota.value) {
    return '正在加载本季度额度…'
  }
  const base = `${quota.value.quarter} 已提交 ${quota.value.counted_submissions} / 最低 ${quota.value.minimum_count} 个提案。`
  if (!quota.value.is_below_minimum) {
    return `${base} 当前已满足季度额度要求。`
  }
  if (quota.value.enforcement_mode === 'BLOCK') {
    return `${base} 未达最低额度时将阻止正式提交。`
  }
  return `${base} 未达最低额度时仅提醒，不阻止保存草稿。`
})

onMounted(async () => {
  errorText.value = ''
  try {
    quota.value = await opportunities.fetchCurrentQuota()
  } catch (err: unknown) {
    quota.value = null
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载季度额度失败'
    }
  }
})
</script>

<template>
  <el-alert
    :type="alertType"
    :closable="false"
    show-icon
    title="季度额度"
    :description="errorText || description"
    :class="compact ? 'quota-panel quota-panel--compact' : 'quota-panel'"
    data-test="proposal-quota-panel"
  />
</template>

<style scoped>
.quota-panel {
  margin-bottom: 1rem;
}

.quota-panel--compact {
  margin-bottom: 0.75rem;
}
</style>
