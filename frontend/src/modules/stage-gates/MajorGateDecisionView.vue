<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useOpportunityStore } from '@/modules/opportunities/store'

const route = useRoute()
const router = useRouter()
const opportunities = useOpportunityStore()

const managementConclusion = ref('APPROVED')
const finalDecision = ref('APPROVED')
const decisionSummary = ref('')
const deferReason = ref('')
const restartTrigger = ref('')
const nextReviewQuarter = ref('')
const errorText = ref('')
const successText = ref('')
const submitting = ref(false)

const stageGatePublicId = computed(() => String(route.params.publicId))

const hasDifference = computed(() => managementConclusion.value !== finalDecision.value)
const requiresDeferDetails = computed(() => finalDecision.value === 'DEFERRED')
const canSubmitDefer = computed(
  () =>
    !requiresDeferDetails.value ||
    deferReason.value.trim().length > 0 ||
    restartTrigger.value.trim().length > 0,
)

const previewStatus = computed(() => {
  const mapping: Record<string, string> = {
    APPROVED: '进入立案 / 创建项目（以阶段门类型为准）',
    APPROVED_WITH_EXCEPTION: '带例外通过',
    NEEDS_INFO: '待补充',
    DEFERRED: '暂缓',
    PASSED: 'Pass',
  }
  return mapping[finalDecision.value] ?? finalDecision.value
})

async function submitDecision(): Promise<void> {
  errorText.value = ''
  successText.value = ''
  submitting.value = true
  try {
    const decision = await opportunities.recordMajorDecision(stageGatePublicId.value, {
      management_conclusion: managementConclusion.value,
      final_decision: finalDecision.value,
      decision_summary: decisionSummary.value,
      idempotency_key: `decision-${stageGatePublicId.value}`,
      defer_reason: deferReason.value,
      restart_trigger: restartTrigger.value,
      next_review_quarter: nextReviewQuarter.value,
    })
    successText.value = `决策已记录：${decision.final_decision}`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '记录决策失败'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="gate-decision" data-test="major-gate-decision">
    <div class="gate-decision__header">
      <div>
        <h2>重大阶段门决策</h2>
        <p class="gate-decision__meta">阶段门 {{ stageGatePublicId }}</p>
      </div>
      <el-button @click="router.back()">返回</el-button>
    </div>

    <el-alert
      v-if="hasDifference"
      type="warning"
      :closable="false"
      title="经管会结论与老板最终决策不一致"
      description="流程状态将仅按老板最终决策迁移。"
      show-icon
      data-test="conclusion-difference"
      class="gate-decision__alert"
    />

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="gate-decision__alert"
    />
    <el-alert
      v-if="successText"
      type="success"
      :closable="false"
      :title="successText"
      show-icon
      class="gate-decision__alert"
    />

    <el-form label-position="top" class="gate-decision__form">
      <el-form-item label="经管会整体结论">
        <el-select v-model="managementConclusion" data-test="management-conclusion">
          <el-option label="通过" value="APPROVED" />
          <el-option label="例外通过" value="APPROVED_WITH_EXCEPTION" />
          <el-option label="待补充" value="NEEDS_INFO" />
          <el-option label="暂缓" value="DEFERRED" />
          <el-option label="Pass" value="PASSED" />
        </el-select>
      </el-form-item>
      <el-form-item label="老板最终决策">
        <el-select v-model="finalDecision" data-test="final-decision">
          <el-option label="通过" value="APPROVED" />
          <el-option label="例外通过" value="APPROVED_WITH_EXCEPTION" />
          <el-option label="待补充" value="NEEDS_INFO" />
          <el-option label="暂缓" value="DEFERRED" />
          <el-option label="Pass" value="PASSED" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="requiresDeferDetails" label="暂缓原因">
        <el-input v-model="deferReason" type="textarea" data-test="defer-reason" />
      </el-form-item>
      <el-form-item v-if="requiresDeferDetails" label="重启条件">
        <el-input v-model="restartTrigger" type="textarea" data-test="restart-trigger" />
      </el-form-item>
      <el-form-item v-if="requiresDeferDetails" label="下次回看季度">
        <el-input v-model="nextReviewQuarter" placeholder="例如 2026Q4" data-test="next-review-quarter" />
      </el-form-item>
      <el-form-item label="决策摘要">
        <el-input v-model="decisionSummary" type="textarea" data-test="decision-summary" />
      </el-form-item>
      <el-card shadow="never" data-test="decision-preview">
        <p><strong>决策后状态预览：</strong>{{ previewStatus }}</p>
      </el-card>
      <el-form-item>
        <el-button
          type="primary"
          data-test="submit-decision"
          :disabled="!canSubmitDefer"
          :loading="submitting"
          @click="submitDecision"
        >
          提交决策
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<style scoped>
.gate-decision__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.gate-decision__meta {
  color: #666;
  margin: 0.25rem 0 0;
}

.gate-decision__alert {
  margin-bottom: 1rem;
}

.gate-decision__form {
  max-width: 720px;
}
</style>
