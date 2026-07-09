<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useOpportunityStore } from '@/modules/opportunities/store'

const router = useRouter()
const opportunities = useOpportunityStore()

const errorText = ref('')
const statusFilter = ref<'ALL' | 'DEFERRED' | 'PASSED'>('ALL')
const keyword = ref('')

const filteredItems = computed(() => {
  return opportunities.poolItems.filter((item) => {
    const statusOk = statusFilter.value === 'ALL' || item.proposal_status === statusFilter.value
    const keywordOk =
      keyword.value.trim() === '' ||
      item.title.toLowerCase().includes(keyword.value.trim().toLowerCase())
    return statusOk && keywordOk
  })
})

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await opportunities.fetchOpportunityPool()
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载候选机会池失败'
    }
  }
}

onMounted(load)
</script>

<template>
  <div class="pool">
    <div class="pool__header">
      <div>
        <h2>候选机会池</h2>
        <p class="pool__hint">暂缓与 Pass 的机会；可按状态与标题筛选。</p>
      </div>
      <el-button :loading="opportunities.loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="pool__error"
    />

    <div class="pool__filters">
      <el-select v-model="statusFilter" style="width: 160px">
        <el-option label="全部" value="ALL" />
        <el-option label="暂缓" value="DEFERRED" />
        <el-option label="Pass" value="PASSED" />
      </el-select>
      <el-input v-model="keyword" placeholder="按标题搜索" clearable />
    </div>

    <el-empty v-if="!opportunities.loading && filteredItems.length === 0" description="暂无记录" />

    <el-table v-else v-loading="opportunities.loading" :data="filteredItems" style="width: 100%">
      <el-table-column prop="title" label="标题" />
      <el-table-column prop="proposal_status" label="停留状态" width="120" />
      <el-table-column prop="updated_at" label="最近更新" width="200" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/opportunities/${row.public_id}`)">
            打开
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.pool__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.pool__hint {
  color: #666;
  margin: 0.25rem 0 0;
}

.pool__error {
  margin-bottom: 1rem;
}

.pool__filters {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
</style>
