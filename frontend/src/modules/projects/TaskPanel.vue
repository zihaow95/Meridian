<script setup lang="ts">
import { computed, ref } from 'vue'

import { ApiError } from '@/api/client'
import { useProjectStore } from '@/modules/projects/store'

const props = defineProps<{
  projectPublicId: string
  leaderPublicId: string
  deputyLeaderPublicId?: string
  actorPublicId: string
}>()

const emit = defineEmits<{ changed: [] }>()

const projects = useProjectStore()
const assigneePublicId = ref('')
const actionMessage = ref('')
const assigning = ref(false)

const canAssign = computed(
  () =>
    props.actorPublicId === props.leaderPublicId ||
    (props.deputyLeaderPublicId !== undefined &&
      props.deputyLeaderPublicId !== '' &&
      props.actorPublicId === props.deputyLeaderPublicId),
)

async function assignFirstTask(): Promise<void> {
  const task = projects.tasks[0]
  if (!task || !assigneePublicId.value.trim()) return
  assigning.value = true
  actionMessage.value = ''
  try {
    await projects.assignTask(task.public_id, {
      user_public_id: assigneePublicId.value.trim(),
      version_no: task.version_no,
    })
    actionMessage.value = '责任人已更新。'
    emit('changed')
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '分派失败'
    }
  } finally {
    assigning.value = false
  }
}
</script>

<template>
  <div class="task-panel" data-test="task-panel">
    <el-alert
      v-if="actionMessage"
      type="warning"
      :closable="false"
      :title="actionMessage"
      show-icon
      class="task-panel__alert"
    />

    <el-table :data="projects.tasks" style="width: 100%">
      <el-table-column prop="task_code" label="编码" width="120" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="status" label="状态" width="140" />
      <el-table-column label="责任人" width="220">
        <template #default="{ row }">
          {{ row.responsible_user_public_id ?? '未分派' }}
        </template>
      </el-table-column>
    </el-table>

    <div v-if="canAssign && projects.tasks.length > 0" class="task-panel__assign">
      <el-input
        v-model="assigneePublicId"
        placeholder="责任人 public_id"
        data-test="assignee-input"
      />
      <el-button
        data-test="assign-task"
        :loading="assigning"
        :disabled="assigning || !assigneePublicId.trim()"
        @click="assignFirstTask"
      >
        分派首个任务
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.task-panel__alert {
  margin-bottom: 1rem;
}

.task-panel__assign {
  display: flex;
  gap: 0.75rem;
  margin-top: 1rem;
  align-items: center;
}
</style>
