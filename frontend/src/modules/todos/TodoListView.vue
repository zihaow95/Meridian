<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { resolveInternalDeepLink } from '@/modules/todos/deepLink'
import { useTodoStore } from '@/modules/todos/store'

const router = useRouter()
const todos = useTodoStore()
const errorText = ref('')

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await todos.fetchMyTodos()
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载待办失败'
    }
  }
}

onMounted(load)

function openLink(link: string): void {
  const decision = resolveInternalDeepLink(link)
  if (!decision.ok) {
    errorText.value = '无权访问或内容不存在'
    return
  }
  void router.push(decision.path)
}
</script>

<template>
  <div class="todos">
    <div class="todos__header">
      <h2>我的待办</h2>
      <div class="todos__actions">
        <el-button data-test="open-notifications" @click="router.push('/notifications')">
          站内通知
        </el-button>
        <el-button :loading="todos.loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="todos__error"
      data-test="todo-error"
    />

    <el-empty v-else-if="!todos.loading && todos.items.length === 0" description="暂无待办" />

    <el-table v-else v-loading="todos.loading" :data="todos.items" style="width: 100%">
      <el-table-column prop="title" label="标题" />
      <el-table-column prop="category" label="类别" width="140" />
      <el-table-column prop="level" label="等级" width="110" />
      <el-table-column prop="due_at" label="到期" width="180" />
      <el-table-column prop="status" label="状态" width="120" />
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button link type="primary" data-test="open-todo" @click="openLink(row.deep_link)">
            打开
          </el-button>
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

.todos__actions {
  display: flex;
  gap: 0.75rem;
}

.todos__error {
  margin-bottom: 1rem;
}
</style>
