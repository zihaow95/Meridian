<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useProjectStore, type ProjectListItem } from '@/modules/projects/store'

const router = useRouter()
const projects = useProjectStore()

const errorText = ref('')
const statusFilter = ref('')

async function load(page = projects.page): Promise<void> {
  errorText.value = ''
  try {
    await projects.fetchProjects({
      status: statusFilter.value || undefined,
      page,
    })
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载项目看板失败'
    }
  }
}

onMounted(() => load())

watch(statusFilter, () => {
  load(1)
})

function onPageChange(page: number): void {
  load(page)
}

function onRowClick(row: ProjectListItem): void {
  router.push(`/projects/${row.public_id}`)
}
</script>

<template>
  <div class="lifecycle-board" data-test="project-lifecycle-board">
    <div class="lifecycle-board__header">
      <div>
        <h2>项目生命周期看板</h2>
        <p class="lifecycle-board__hint">按权限展示可访问的执行中项目。</p>
      </div>
      <el-button :loading="projects.loading" @click="load()">刷新</el-button>
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
      <el-select v-model="statusFilter" clearable placeholder="项目状态" data-test="filter-status">
        <el-option label="执行中" value="EXECUTING" />
        <el-option label="运营中" value="OPERATING" />
        <el-option label="待修复发布" value="PUBLISH_PENDING_REPAIR" />
      </el-select>
    </div>

    <el-empty
      v-if="!projects.loading && projects.items.length === 0"
      description="暂无可访问项目"
    />

    <el-table
      v-else
      v-loading="projects.loading"
      :data="projects.items"
      style="width: 100%"
      @row-click="onRowClick"
    >
      <el-table-column prop="business_no" label="编号" width="140" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="status" label="状态" width="180" />
      <el-table-column prop="current_stage_code" label="当前阶段" width="120" />
    </el-table>

    <el-pagination
      v-if="projects.totalCount > projects.pageSize"
      class="lifecycle-board__pagination"
      layout="prev, pager, next"
      :total="projects.totalCount"
      :current-page="projects.page"
      :page-size="projects.pageSize"
      @current-change="onPageChange"
    />
  </div>
</template>

<style scoped>
.lifecycle-board__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.lifecycle-board__hint {
  margin: 0.25rem 0 0;
  color: var(--el-text-color-secondary);
}

.lifecycle-board__filters {
  margin-bottom: 1rem;
}

.lifecycle-board__alert {
  margin-bottom: 1rem;
}

.lifecycle-board__pagination {
  margin-top: 1rem;
  justify-content: flex-end;
}
</style>
