<script setup lang="ts">
import { computed, ref } from 'vue'

import { ApiError } from '@/api/client'
import { useProjectStore } from '@/modules/projects/store'

const props = defineProps<{
  stageGatePublicId: string
  launchMode?: boolean
}>()

const emit = defineEmits<{ completed: [] }>()

const projects = useProjectStore()
const validating = ref(false)
const submitting = ref(false)
const deciding = ref(false)
const actionMessage = ref('')
const managementConclusion = ref('APPROVED')
const finalDecision = ref('APPROVED')

const hasBlocks = computed(() => (projects.gateValidation?.blocks?.length ?? 0) > 0)

async function validateGate(): Promise<void> {
  validating.value = true
  actionMessage.value = ''
  try {
    await projects.validateStageGate(props.stageGatePublicId)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '预检失败'
    }
  } finally {
    validating.value = false
  }
}

async function submitGate(): Promise<void> {
  if (hasBlocks.value || submitting.value) return
  submitting.value = true
  actionMessage.value = ''
  try {
    await projects.submitStageGate(
      props.stageGatePublicId,
      `submit-${props.stageGatePublicId}-${Date.now()}`,
    )
    actionMessage.value = '阶段门材料已提交。'
    emit('completed')
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '提交失败'
    }
  } finally {
    submitting.value = false
  }
}

async function recordManagementConclusion(): Promise<void> {
  if (deciding.value) return
  deciding.value = true
  actionMessage.value = ''
  try {
    await projects.recordFirstLaunchManagementConclusion(props.stageGatePublicId, {
      management_conclusion: managementConclusion.value,
      idempotency_key: `first-launch-mgmt-${props.stageGatePublicId}`,
      decision_summary: '',
    })
    actionMessage.value = '管理会结论已记录，等待终审。'
    emit('completed')
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '管理会结论失败'
    }
  } finally {
    deciding.value = false
  }
}

async function recordFinalDecision(): Promise<void> {
  if (deciding.value) return
  deciding.value = true
  actionMessage.value = ''
  try {
    const result = await projects.recordFirstLaunchFinalDecision(props.stageGatePublicId, {
      final_decision: finalDecision.value,
      idempotency_key: `first-launch-final-${props.stageGatePublicId}`,
      decision_summary: '',
    })
    if (result.project_status === 'PUBLISH_PENDING_REPAIR' || result.handover_error) {
      actionMessage.value = `PUBLISH_PENDING_REPAIR: ${result.handover_error ?? '产品发布待修复'}`
    } else {
      actionMessage.value = '首次上市终审已记录。'
    }
    emit('completed')
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '首次上市终审失败'
    }
  } finally {
    deciding.value = false
  }
}

async function recordNormalDecision(): Promise<void> {
  if (deciding.value) return
  deciding.value = true
  actionMessage.value = ''
  try {
    await projects.recordNormalGateDecision(props.stageGatePublicId, {
      result: 'APPROVED',
      idempotency_key: `decision-${props.stageGatePublicId}`,
      decision_summary: '',
    })
    actionMessage.value = '阶段门决策已记录。'
    emit('completed')
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '决策失败'
    }
  } finally {
    deciding.value = false
  }
}
</script>

<template>
  <div class="stage-gate-panel" data-test="stage-gate-panel">
    <div class="stage-gate-panel__actions">
      <el-button data-test="validate-gate" :loading="validating" @click="validateGate">
        预检
      </el-button>
      <el-button
        data-test="submit-gate"
        type="primary"
        :loading="submitting"
        :disabled="submitting || hasBlocks"
        @click="submitGate"
      >
        提交材料
      </el-button>
    </div>

    <ul v-if="projects.gateValidation?.blocks?.length" class="stage-gate-panel__blocks">
      <li v-for="(block, index) in projects.gateValidation?.blocks" :key="index">
        {{ (block as { code?: string; message?: string }).code }}:
        {{ (block as { message?: string }).message }}
      </li>
    </ul>

    <div v-if="launchMode" class="stage-gate-panel__launch">
      <el-select v-model="managementConclusion" data-test="management-conclusion">
        <el-option label="经管会通过" value="APPROVED" />
        <el-option label="待补充" value="NEEDS_INFO" />
      </el-select>
      <el-button
        data-test="record-management-conclusion"
        :loading="deciding"
        :disabled="deciding"
        @click="recordManagementConclusion"
      >
        记录管理会结论
      </el-button>
      <el-select v-model="finalDecision" data-test="final-decision">
        <el-option label="最终批准" value="APPROVED" />
        <el-option label="暂缓" value="DEFERRED" />
      </el-select>
      <el-button
        data-test="record-final-decision"
        type="primary"
        :loading="deciding"
        :disabled="deciding"
        @click="recordFinalDecision"
      >
        记录终审决策
      </el-button>
    </div>

    <el-button
      v-else
      data-test="record-decision"
      :loading="deciding"
      :disabled="deciding"
      @click="recordNormalDecision"
    >
      记录通过决策
    </el-button>

    <el-alert
      v-if="actionMessage"
      type="warning"
      :closable="false"
      :title="actionMessage"
      show-icon
      class="stage-gate-panel__alert"
    />
  </div>
</template>

<style scoped>
.stage-gate-panel__actions {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.stage-gate-panel__blocks {
  margin: 0 0 1rem;
  padding-left: 1.25rem;
  color: var(--el-color-danger);
}

.stage-gate-panel__launch {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-bottom: 1rem;
  align-items: center;
}

.stage-gate-panel__alert {
  margin-top: 1rem;
}
</style>
