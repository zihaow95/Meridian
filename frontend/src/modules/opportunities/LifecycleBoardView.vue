<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useOpportunityStore, type LifecycleBoardItem } from '@/modules/opportunities/store'

const router = useRouter()
const opportunities = useOpportunityStore()

const errorText = ref('')
const lifecycleStage = ref('')
const status = ref('')
const owner = ref('')

const items = computed(() => opportunities.lifecycleBoard)

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await opportunities.fetchLifecycleBoard({
      lifecycle_stage: lifecycleStage.value || undefined,
      status: status.value || undefined,
      owner: owner.value || undefined,
    })
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载生命周期看板失败'
    }
  }
}

onMounted(load)

function onRowClick(row: LifecycleBoardItem): void {
  if (row.item_type === 'PROJECT') {
    router.push(`/opportunities/${row.candidate_public_id ?? row.public_id}`)
    return
  }
  router.push(`/opportunities/${row.public_id}`)
}
</script>

<template>
  <div class="lifecycle-board" data-test="lifecycle-board">
    <div class="lifecycle-board__header">
      <div>
        <h2>生命周期看板</h2>
        <p class="lifecycle-board__hint">统一展示立项前机会与已创建项目。</p>
      </div>
      <el-button :loading="opportunities.loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="lifecycle-board__alert"
    />

    <div class="lifecycle-board__filters">
      <el-select
        v-model="lifecycleStage"
        clearable
        placeholder="阶段"
        data-test="filter-stage"
        @change="load"
      >
        <el-option label="提案" value="PROPOSAL" />
        <el-option label="立案" value="CASE" />
        <el-option label="项目" value="PROJECT" />
        <el-option label="暂缓" value="DEFERRED" />
        <el-option label="Pass" value="PASSED" />
      </el-select>
      <el-input
        v-model="status"
        clearable
        placeholder="状态"
        data-test="filter-status"
        @change="load"
      />
      <el-input
        v-model="owner"
        clearable
        placeholder="负责人 public_id"
        data-test="filter-owner"
        @change="load"
      />
    </div>

    <el-empty v-if="!opportunities.loading && items.length === 0" description="暂无可见条目" />

    <el-table
      v-else
      v-loading="opportunities.loading"
      :data="items"
      style="width: 100%"
      data-test="lifecycle-board-table"
      @row-click="onRowClick"
    >
      <el-table-column prop="item_type" label="类型" width="120" />
      <el-table-column prop="business_no" label="编号" width="140" />
      <el-table-column prop="title" label="名称" />
      <el-table-column prop="lifecycle_stage" label="阶段" width="120" />
      <el-table-column prop="status" label="状态" width="160" />
      <el-table-column prop="owner_display_name" label="负责人" width="160" />
      <el-table-column prop="updated_at" label="更新时间" width="200" />
    </el-table>
  </div>
</template>

<style scoped>
.lifecycle-board__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.lifecycle-board__hint {
  color: #666;
  margin: 0.25rem 0 0;
}

.lifecycle-board__alert {
  margin-bottom: 1rem;
}

.lifecycle-board__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
</style>
