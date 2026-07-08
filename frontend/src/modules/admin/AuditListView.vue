<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'

type AuditEvent = {
  event_id: string
  occurred_at: string
  action_code: string
  resource_type: string
  resource_public_id: string | null
  result: string
}

const events = ref<AuditEvent[]>([])
const loading = ref(false)
const errorText = ref('')

async function load(): Promise<void> {
  loading.value = true
  errorText.value = ''
  try {
    events.value = await apiFetch<AuditEvent[]>('/api/v1/audit/events')
  } catch (err: unknown) {
    events.value = []
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载审计事件失败'
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="audit">
    <div class="audit__header">
      <h2>审计查询</h2>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="audit__error"
    />

    <el-empty v-else-if="!loading && events.length === 0" description="暂无审计事件" />

    <el-table v-else v-loading="loading" :data="events" style="width: 100%">
      <el-table-column prop="occurred_at" label="时间" width="220" />
      <el-table-column prop="action_code" label="动作" />
      <el-table-column prop="resource_type" label="资源类型" />
      <el-table-column prop="result" label="结果" width="120" />
    </el-table>
  </div>
</template>

<style scoped>
.audit__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.audit__error {
  margin-bottom: 1rem;
}
</style>
