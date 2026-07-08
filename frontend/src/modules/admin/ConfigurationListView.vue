<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'

type ConfigurationDefinition = {
  definition_code: string
  name: string
  description: string
}

const definitions = ref<ConfigurationDefinition[]>([])
const loading = ref(false)
const errorText = ref('')

async function load(): Promise<void> {
  loading.value = true
  errorText.value = ''
  try {
    definitions.value = await apiFetch<ConfigurationDefinition[]>(
      '/api/v1/configurations/definitions',
    )
  } catch (err: unknown) {
    definitions.value = []
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载配置定义失败'
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="config">
    <div class="config__header">
      <h2>配置发布管理</h2>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="config__error"
    />

    <el-empty v-else-if="!loading && definitions.length === 0" description="暂无配置定义" />

    <el-table v-else v-loading="loading" :data="definitions" style="width: 100%">
      <el-table-column prop="definition_code" label="配置编码" width="240" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="description" label="描述" />
    </el-table>
  </div>
</template>

<style scoped>
.config__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.config__error {
  margin-bottom: 1rem;
}
</style>
