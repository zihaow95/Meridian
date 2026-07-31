<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useOperationsStore, type RiskSignal } from '@/modules/operations/store'

const router = useRouter()
const operations = useOperationsStore()
const errorText = ref('')
const statusMessage = ref('')
const busy = ref(false)
const statusFilter = ref('')
const closeReason = ref('')
const escalateTitle = ref('')
const escalateSummary = ref('')
const activeSignalId = ref('')

function formatError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.code}: ${err.message}`
  return fallback
}

function canMutate(signal: RiskSignal): boolean {
  return signal.status === 'NEW' || signal.status === 'VIEWED'
}

async function loadSignals(): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  try {
    await operations.fetchRiskSignals(statusFilter.value || undefined)
  } catch (err: unknown) {
    errorText.value = formatError(err, '加载风险信号失败')
  } finally {
    busy.value = false
  }
}

async function viewSignal(signal: RiskSignal): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  activeSignalId.value = signal.public_id
  try {
    await operations.viewRiskSignal(signal.public_id)
  } catch (err: unknown) {
    errorText.value = formatError(err, '标记已读失败')
  } finally {
    busy.value = false
  }
}

async function closeSignal(signal: RiskSignal): Promise<void> {
  if (busy.value || !canMutate(signal)) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  activeSignalId.value = signal.public_id
  try {
    await operations.closeRiskSignal(signal.public_id, {
      reason: closeReason.value || 'closed from workbench',
    })
    statusMessage.value = '信号已关闭'
  } catch (err: unknown) {
    errorText.value = operations.conflictHint || formatError(err, '关闭信号失败')
  } finally {
    busy.value = false
  }
}

async function escalateSignal(signal: RiskSignal): Promise<void> {
  if (busy.value || !canMutate(signal)) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  activeSignalId.value = signal.public_id
  try {
    const result = await operations.escalateRiskSignal(signal.public_id, {
      title: escalateTitle.value || `Issue from ${signal.rule_code}`,
      phenomenon_summary: escalateSummary.value || signal.rule_code,
    })
    statusMessage.value = `已升级议题 ${result.issue_public_id}`
    await router.push(`/operations/issues/${result.issue_public_id}`)
  } catch (err: unknown) {
    errorText.value = operations.conflictHint || formatError(err, '升级议题失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="ops-risk" data-test="risk-signal-center-page">
    <div class="ops-risk__header">
      <h2>风险信号中心</h2>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="ops-risk__alert"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="ops-risk__alert"
    />
    <el-alert
      v-if="operations.conflictHint"
      type="warning"
      :closable="false"
      :title="operations.conflictHint"
      show-icon
      class="ops-risk__alert"
    />

    <div class="ops-risk__filters">
      <el-select v-model="statusFilter" data-test="status-filter" placeholder="状态筛选" clearable>
        <el-option label="全部" value="" />
        <el-option label="NEW" value="NEW" />
        <el-option label="VIEWED" value="VIEWED" />
        <el-option label="CLOSED" value="CLOSED" />
      </el-select>
      <el-button
        data-test="load-signals"
        type="primary"
        :loading="busy"
        :disabled="busy"
        @click="loadSignals"
      >
        加载信号
      </el-button>
    </div>

    <div class="ops-risk__forms">
      <el-input v-model="closeReason" data-test="close-reason" placeholder="关闭理由" />
      <el-input v-model="escalateTitle" data-test="escalate-title" placeholder="升级议题标题" />
      <el-input v-model="escalateSummary" data-test="escalate-summary" placeholder="现象摘要" />
    </div>

    <ul class="ops-risk__list" data-test="risk-signal-list">
      <li
        v-for="row in operations.riskSignals"
        :key="row.public_id"
        class="ops-risk__item"
        data-test="risk-signal-row"
      >
        <div>
          {{ row.rule_code }} / {{ row.status }} / {{ row.coverage_status }} /
          {{ row.actual_value }} / {{ row.threshold_value }}
        </div>
        <div class="ops-risk__item-actions">
          <el-button
            link
            type="primary"
            data-test="view-signal"
            :loading="busy && activeSignalId === row.public_id"
            :disabled="busy"
            @click="viewSignal(row)"
          >
            查看
          </el-button>
          <el-button
            v-if="canMutate(row)"
            link
            type="warning"
            data-test="close-signal"
            :loading="busy && activeSignalId === row.public_id"
            :disabled="busy"
            @click="closeSignal(row)"
          >
            关闭
          </el-button>
          <el-button
            v-if="canMutate(row)"
            link
            type="danger"
            data-test="escalate-signal"
            :loading="busy && activeSignalId === row.public_id"
            :disabled="busy"
            @click="escalateSignal(row)"
          >
            升级议题
          </el-button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.ops-risk__header {
  margin-bottom: 1rem;
}

.ops-risk__alert,
.ops-risk__filters,
.ops-risk__forms {
  margin-bottom: 1rem;
}

.ops-risk__filters,
.ops-risk__forms {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.ops-risk__item {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.75rem;
}

.ops-risk__item-actions {
  display: flex;
  gap: 0.5rem;
}
</style>
