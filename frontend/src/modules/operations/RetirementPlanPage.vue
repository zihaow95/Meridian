<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useOperationsStore } from '@/modules/operations/store'

const route = useRoute()
const router = useRouter()
const operations = useOperationsStore()
const errorText = ref('')
const statusMessage = ref('')
const busy = ref(false)

const productPublicId = ref('')
const issuePublicId = ref('')
const scopeSnapshotJson = ref('{"skus":[]}')
const submitIdempotency = ref(`submit-${Date.now()}`)
const managementConclusion = ref('APPROVE')
const managementIdempotency = ref(`mgmt-${Date.now()}`)
const finalDecision = ref('APPROVE')
const finalIdempotency = ref(`final-${Date.now()}`)
const executeAsOf = ref('')

const planId = computed(() => String(route.params.publicId ?? ''))
const stageGateId = computed(() => operations.retirementPlan?.stage_gate_public_id || '')

function formatError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.code}: ${err.message}`
  return fallback
}

onMounted(() => {
  if (planId.value && planId.value !== 'new') {
    operations.bindRetirementPlanPublicId(planId.value)
  }
})

async function createPlan(): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    const scope_snapshot = JSON.parse(scopeSnapshotJson.value) as Record<string, unknown>
    const plan = await operations.createRetirementPlan({
      product_public_id: productPublicId.value,
      issue_public_id: issuePublicId.value || null,
      scope_snapshot,
    })
    statusMessage.value = `退市计划已创建：${plan.status}`
    await router.replace(`/retirement-plans/${plan.public_id}`)
  } catch (err: unknown) {
    errorText.value = formatError(err, '创建退市计划失败')
  } finally {
    busy.value = false
  }
}

async function validatePlan(): Promise<void> {
  if (busy.value || !planId.value || planId.value === 'new') return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    const result = await operations.validateRetirementPlan(planId.value)
    if (result.ok) {
      statusMessage.value = '预检通过'
    } else {
      statusMessage.value = `预检阻塞：${(result.missing as unknown[]).join(', ')}`
    }
  } catch (err: unknown) {
    errorText.value = formatError(err, '预检失败')
  } finally {
    busy.value = false
  }
}

async function submitPlan(): Promise<void> {
  if (busy.value || !planId.value || planId.value === 'new') return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    const result = await operations.submitRetirementPlan(planId.value, {
      idempotency_key: submitIdempotency.value,
    })
    statusMessage.value = `已提交：submission #${result.submission_number}`
  } catch (err: unknown) {
    errorText.value = operations.conflictHint || formatError(err, '提交退市计划失败')
  } finally {
    busy.value = false
  }
}

async function recordManagement(): Promise<void> {
  if (busy.value || !stageGateId.value) {
    errorText.value = '缺少阶段门 ID，请先提交计划或绑定 stage_gate_public_id'
    return
  }
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.recordRetirementManagementConclusion(stageGateId.value, {
      management_conclusion: managementConclusion.value,
      idempotency_key: managementIdempotency.value,
    })
    statusMessage.value = '经管会结论已记录（需由不同角色完成老板决策）'
  } catch (err: unknown) {
    errorText.value = formatError(err, '记录经管会结论失败')
  } finally {
    busy.value = false
  }
}

async function recordFinal(): Promise<void> {
  if (busy.value || !stageGateId.value) {
    errorText.value = '缺少阶段门 ID，请先提交计划或绑定 stage_gate_public_id'
    return
  }
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.recordRetirementFinalDecision(stageGateId.value, {
      final_decision: finalDecision.value,
      idempotency_key: finalIdempotency.value,
    })
    statusMessage.value = '老板最终决策已记录'
  } catch (err: unknown) {
    errorText.value = formatError(err, '记录最终决策失败')
  } finally {
    busy.value = false
  }
}

async function executePlan(): Promise<void> {
  if (busy.value || !planId.value || planId.value === 'new') return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.executeRetirementPlan(planId.value, {
      as_of: executeAsOf.value || null,
    })
    statusMessage.value = `执行状态：${operations.retirementPlan?.status ?? ''}`
  } catch (err: unknown) {
    errorText.value = operations.conflictHint || formatError(err, '执行退市失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="ops-retirement" data-test="retirement-plan-page">
    <div class="ops-retirement__header">
      <h2>退市计划</h2>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="ops-retirement__alert"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="ops-retirement__alert"
    />
    <el-alert
      v-if="operations.conflictHint"
      type="warning"
      :closable="false"
      :title="operations.conflictHint"
      show-icon
      class="ops-retirement__alert"
    />

    <el-card class="ops-retirement__card">
      <template #header>创建计划</template>
      <div class="ops-retirement__form">
        <el-input
          v-model="productPublicId"
          data-test="product-public-id"
          placeholder="product_public_id"
        />
        <el-input
          v-model="issuePublicId"
          data-test="issue-public-id"
          placeholder="issue_public_id（可选）"
        />
        <el-input
          v-model="scopeSnapshotJson"
          type="textarea"
          data-test="scope-snapshot"
          placeholder="scope_snapshot JSON"
        />
        <el-button
          data-test="create-plan"
          type="primary"
          :loading="busy"
          :disabled="busy"
          @click="createPlan"
        >
          创建
        </el-button>
      </div>
    </el-card>

    <p v-if="operations.retirementPlan" data-test="plan-status">
      计划 {{ operations.retirementPlan.public_id }} 状态：{{ operations.retirementPlan.status }}
    </p>

    <div class="ops-retirement__actions">
      <el-button data-test="validate-plan" :loading="busy" :disabled="busy" @click="validatePlan">
        预检
      </el-button>
      <el-input
        v-model="submitIdempotency"
        data-test="submit-idempotency"
        placeholder="submit idempotency_key"
      />
      <el-button
        data-test="submit-plan"
        type="primary"
        :loading="busy"
        :disabled="busy"
        @click="submitPlan"
      >
        提交阶段门
      </el-button>
    </div>

    <p v-if="operations.retirementValidation && !operations.retirementValidation.ok">
      阻塞项：
      <span
        v-for="item in operations.retirementValidation.missing"
        :key="String(item)"
        data-test="validate-missing"
      >
        {{ item }}
      </span>
    </p>

    <el-card class="ops-retirement__card">
      <template #header>经管会结论（与老板决策须由不同角色完成）</template>
      <div class="ops-retirement__form">
        <el-input
          v-model="managementConclusion"
          data-test="management-conclusion"
          placeholder="management_conclusion"
        />
        <el-input
          v-model="managementIdempotency"
          data-test="management-idempotency"
          placeholder="idempotency_key"
        />
        <el-button
          data-test="record-management"
          :loading="busy"
          :disabled="busy"
          @click="recordManagement"
        >
          记录经管会结论
        </el-button>
      </div>
    </el-card>

    <el-card class="ops-retirement__card">
      <template #header>老板最终决策</template>
      <div class="ops-retirement__form">
        <el-input v-model="finalDecision" data-test="final-decision" placeholder="final_decision" />
        <el-input
          v-model="finalIdempotency"
          data-test="final-idempotency"
          placeholder="idempotency_key"
        />
        <el-button
          data-test="record-final"
          type="warning"
          :loading="busy"
          :disabled="busy"
          @click="recordFinal"
        >
          记录老板决策
        </el-button>
      </div>
    </el-card>

    <div class="ops-retirement__actions">
      <el-input v-model="executeAsOf" data-test="execute-as-of" placeholder="as_of（可选）" />
      <el-button
        data-test="execute-plan"
        type="danger"
        :loading="busy"
        :disabled="busy"
        @click="executePlan"
      >
        执行退市
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.ops-retirement__header {
  margin-bottom: 1rem;
}

.ops-retirement__alert,
.ops-retirement__card,
.ops-retirement__actions {
  margin-bottom: 1rem;
}

.ops-retirement__form,
.ops-retirement__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-start;
}
</style>
