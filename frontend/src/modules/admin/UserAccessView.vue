<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'

type Role = {
  public_id: string
  role_code: string
  name: string
  role_type: string
  is_critical: boolean
}

const roles = ref<Role[]>([])
const loading = ref(false)
const errorText = ref('')

async function load(): Promise<void> {
  loading.value = true
  errorText.value = ''
  try {
    roles.value = await apiFetch<Role[]>('/api/v1/authorization/roles')
  } catch (err: unknown) {
    roles.value = []
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载角色目录失败'
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="access">
    <div class="access__header">
      <h2>用户权限管理</h2>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="access__error"
    />

    <el-empty v-else-if="!loading && roles.length === 0" description="暂无角色" />

    <el-table v-else v-loading="loading" :data="roles" style="width: 100%">
      <el-table-column prop="role_code" label="角色编码" width="220" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="role_type" label="类型" width="140" />
      <el-table-column label="关键角色" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.is_critical" type="danger">关键</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.access__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.access__error {
  margin-bottom: 1rem;
}
</style>
