<script setup lang="ts">
import { onMounted } from 'vue'

import { useTodoStore } from '@/modules/todos/store'

const todos = useTodoStore()

onMounted(async () => {
  await todos.fetchMyTodos()
})

function openLink(link: string): void {
  window.location.assign(link)
}
</script>

<template>
  <div class="todos">
    <div class="todos__header">
      <h2>我的待办</h2>
      <el-button :loading="todos.loading" @click="todos.fetchMyTodos">刷新</el-button>
    </div>

    <el-table v-loading="todos.loading" :data="todos.items" style="width: 100%">
      <el-table-column prop="title" label="标题" />
      <el-table-column prop="status" label="状态" width="140" />
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="openLink(row.deep_link)">打开</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.todos__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
</style>
