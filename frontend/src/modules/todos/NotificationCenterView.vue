<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { resolveInternalDeepLink } from '@/modules/todos/deepLink'
import { useTodoStore } from '@/modules/todos/store'

const router = useRouter()
const todos = useTodoStore()
const errorText = ref('')
const statusFilter = ref('')
const categoryFilter = ref('')
const levelFilter = ref('')
const busyId = ref('')

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await todos.fetchMyNotifications({
      status: statusFilter.value || undefined,
      category: categoryFilter.value || undefined,
      level: levelFilter.value || undefined,
    })
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载通知失败'
    }
  }
}

async function markRead(publicId: string): Promise<void> {
  if (busyId.value) return
  busyId.value = publicId
  errorText.value = ''
  try {
    await todos.markNotificationRead(publicId)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '标记已读失败'
    }
  } finally {
    busyId.value = ''
  }
}

async function closeNotice(publicId: string): Promise<void> {
  if (busyId.value) return
  busyId.value = publicId
  errorText.value = ''
  try {
    await todos.closeNotification(publicId, 'USER_CLOSED')
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '关闭通知失败'
    }
  } finally {
    busyId.value = ''
  }
}

function openDeepLink(link: string): void {
  const decision = resolveInternalDeepLink(link)
  if (!decision.ok) {
    errorText.value = '无权访问或内容不存在'
    return
  }
  void router.push(decision.path)
}

onMounted(load)
</script>

<template>
  <div class="notifications">
    <div class="notifications__header">
      <div>
        <h2>站内通知</h2>
        <p class="notifications__hint" data-test="unread-count">
          未读 {{ todos.unreadCount }} · 与待办分开维护，可互相定位
        </p>
      </div>
      <div class="notifications__actions">
        <el-button data-test="open-todos" @click="router.push('/todos')">查看待办</el-button>
        <el-button :loading="todos.notificationsLoading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="notifications__filters">
      <el-select
        v-model="statusFilter"
        clearable
        placeholder="状态"
        data-test="filter-status"
        style="width: 140px"
        @change="load"
      >
        <el-option label="未读" value="UNREAD" />
        <el-option label="已读" value="READ" />
        <el-option label="已关闭" value="CLOSED" />
      </el-select>
      <el-select
        v-model="categoryFilter"
        clearable
        placeholder="类别"
        data-test="filter-category"
        style="width: 180px"
        @change="load"
      >
        <el-option label="需处理" value="ACTION_REQUIRED" />
        <el-option label="期限" value="DEADLINE" />
        <el-option label="业务提醒" value="BUSINESS_ALERT" />
        <el-option label="流程结果" value="PROCESS_RESULT" />
        <el-option label="系统故障" value="SYSTEM_FAILURE" />
        <el-option label="信息" value="INFORMATION" />
      </el-select>
      <el-select
        v-model="levelFilter"
        clearable
        placeholder="等级"
        data-test="filter-level"
        style="width: 140px"
        @change="load"
      >
        <el-option label="紧急" value="URGENT" />
        <el-option label="重要" value="IMPORTANT" />
        <el-option label="普通" value="NORMAL" />
      </el-select>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="notifications__error"
      data-test="notification-error"
    />

    <el-empty
      v-else-if="!todos.notificationsLoading && todos.notifications.length === 0"
      description="暂无通知"
      data-test="notifications-empty"
    />

    <el-table
      v-else
      v-loading="todos.notificationsLoading"
      :data="todos.notifications"
      data-test="notifications-table"
    >
      <el-table-column prop="summary" label="摘要" min-width="220" />
      <el-table-column prop="category" label="类别" width="140" />
      <el-table-column prop="level" label="等级" width="110" />
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column label="操作" min-width="240">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            data-test="open-notification"
            @click="openDeepLink(row.deep_link)"
          >
            打开
          </el-button>
          <el-button
            link
            :disabled="busyId === row.public_id || row.status !== 'UNREAD'"
            data-test="mark-read"
            @click="markRead(row.public_id)"
          >
            已读
          </el-button>
          <el-button
            link
            :disabled="busyId === row.public_id || row.status === 'CLOSED'"
            data-test="close-notification"
            @click="closeNotice(row.public_id)"
          >
            关闭
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.notifications__header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  margin-bottom: 1rem;
}

.notifications__hint {
  color: #666;
}

.notifications__actions,
.notifications__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.notifications__error {
  margin-bottom: 1rem;
}
</style>
