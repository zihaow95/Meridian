<script setup lang="ts">
import { ref } from 'vue'

import { apiFetch, ApiError } from '@/api/client'
import { useProjectStore } from '@/modules/projects/store'

defineProps<{ projectPublicId: string }>()
const emit = defineEmits<{ changed: [] }>()

const projects = useProjectStore()
const confirmerPublicId = ref('confirmer-1')
const confirmationPublicId = ref('confirm-1')
const actionMessage = ref('')
const submitting = ref(false)

async function submitCurrentRevision(): Promise<void> {
  const deliverable = projects.deliverables[0]
  if (!deliverable?.current_revision_public_id) return
  submitting.value = true
  actionMessage.value = ''
  try {
    const result = await apiFetch<{ status: string }>(
      `/api/v1/deliverable-revisions/${deliverable.current_revision_public_id}/submit`,
      {
        method: 'POST',
        json: { confirmer_public_id: confirmerPublicId.value },
      },
    )
    actionMessage.value = `修订已提交：${result.status}`
    emit('changed')
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '提交确认失败'
    }
  } finally {
    submitting.value = false
  }
}

async function decideConfirmation(): Promise<void> {
  submitting.value = true
  actionMessage.value = ''
  try {
    await apiFetch(`/api/v1/professional-confirmations/${confirmationPublicId.value}/decide`, {
      method: 'POST',
      json: { decision: 'APPROVED', comment: '' },
    })
    actionMessage.value = '确认已完成。'
    emit('changed')
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '确认决策失败'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="deliverable-panel" data-test="deliverable-panel">
    <el-alert
      v-if="actionMessage"
      type="warning"
      :closable="false"
      :title="actionMessage"
      show-icon
      class="deliverable-panel__alert"
    />

    <el-table :data="projects.deliverables" style="width: 100%">
      <el-table-column prop="deliverable_code" label="编码" width="120" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="tier" label="层级" width="100" />
      <el-table-column prop="status" label="状态" width="140" />
    </el-table>

    <div v-if="projects.deliverables.length > 0" class="deliverable-panel__actions">
      <el-input v-model="confirmerPublicId" placeholder="确认人 public_id" />
      <el-button
        data-test="submit-revision"
        :loading="submitting"
        :disabled="submitting"
        @click="submitCurrentRevision"
      >
        提交修订确认
      </el-button>
      <el-button
        data-test="decide-confirmation"
        :loading="submitting"
        :disabled="submitting"
        @click="decideConfirmation"
      >
        专业确认通过
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.deliverable-panel__alert {
  margin-bottom: 1rem;
}

.deliverable-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 1rem;
  align-items: center;
}
</style>
