<script setup lang="ts">
import { computed, ref } from 'vue'

import { apiFetch, ApiError } from '@/api/client'
import type { WorkbenchDeliverableItem } from '@/modules/projects/store'
import { useProjectStore } from '@/modules/projects/store'

defineProps<{ projectPublicId: string }>()
const emit = defineEmits<{ changed: [] }>()

const projects = useProjectStore()
const confirmerPublicId = ref('confirmer-1')
const confirmationPublicId = ref('confirm-1')
const actionMessage = ref('')
const submitting = ref(false)
const downloadingId = ref('')
const canDownload = computed(() => projects.detail?.can_download_documents ?? false)

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

async function downloadDeliverable(row: WorkbenchDeliverableItem): Promise<void> {
  const versionId = row.document_version_public_id
  if (!versionId) {
    actionMessage.value = '该交付物尚无可下载文件版本。'
    return
  }
  downloadingId.value = row.public_id
  actionMessage.value = ''
  try {
    const ticket = await apiFetch<{ token: string }>(
      `/api/v1/documents/versions/${versionId}/download-ticket`,
      { method: 'POST' },
    )
    // Ticket consumption relies on the download endpoint's X-Accel-Redirect
    // headers; navigating preserves cookies and lets the gateway stream bytes.
    window.location.assign(`/api/v1/documents/download/${ticket.token}`)
    actionMessage.value = `已开始下载：${row.name}`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '下载失败'
    }
  } finally {
    downloadingId.value = ''
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

    <ul v-if="canDownload" class="deliverable-panel__downloads" data-test="deliverable-downloads">
      <li v-for="row in projects.deliverables" :key="row.public_id">
        <el-button
          v-if="row.document_version_public_id"
          link
          type="primary"
          data-test="download-deliverable"
          :loading="downloadingId === row.public_id"
          :disabled="Boolean(downloadingId)"
          @click="downloadDeliverable(row)"
        >
          下载 {{ row.name }}
        </el-button>
      </li>
    </ul>

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

.deliverable-panel__muted {
  color: var(--el-text-color-secondary);
}
</style>
