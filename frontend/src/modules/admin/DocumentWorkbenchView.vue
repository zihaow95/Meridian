<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'

type DocumentVersionRow = {
  public_id: string
  version_number: number
  status: string
  original_filename: string
}

const documentId = ref('')
const versions = ref<DocumentVersionRow[]>([])
const loading = ref(false)
const errorText = ref('')

async function loadVersions(): Promise<void> {
  if (!documentId.value) {
    errorText.value = '请输入文档 ID'
    return
  }
  loading.value = true
  errorText.value = ''
  try {
    versions.value = await apiFetch<DocumentVersionRow[]>(
      `/api/v1/documents/${documentId.value}/versions`,
    )
  } catch (err: unknown) {
    versions.value = []
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载文档版本失败'
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  // No document selected by default; user provides an id to query versions.
})
</script>

<template>
  <div class="docs">
    <div class="docs__header">
      <h2>文件工作台</h2>
    </div>

    <div class="docs__query">
      <el-input v-model="documentId" placeholder="文档 public_id" />
      <el-button type="primary" :loading="loading" @click="loadVersions">查询版本</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="docs__error"
    />

    <el-empty
      v-else-if="!loading && versions.length === 0"
      description="输入文档 ID 查询受控版本"
    />

    <el-table v-else v-loading="loading" :data="versions" style="width: 100%">
      <el-table-column prop="version_number" label="版本" width="100" />
      <el-table-column prop="original_filename" label="文件名" />
      <el-table-column prop="status" label="状态" width="160" />
    </el-table>
  </div>
</template>

<style scoped>
.docs__header {
  margin-bottom: 1rem;
}

.docs__query {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.docs__error {
  margin-bottom: 1rem;
}
</style>
