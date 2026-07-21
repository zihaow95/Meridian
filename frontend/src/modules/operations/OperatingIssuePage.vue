<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import { useOperationsStore } from '@/modules/operations/store'

const route = useRoute()
const operations = useOperationsStore()
const errorText = ref('')
const statusMessage = ref('')
const busy = ref(false)

const recommendationType = ref('ITERATE')
const actionSummary = ref('')
const proposalOwner = ref('')
const idempotencyKey = ref(`iter-${Date.now()}`)

const issueId = computed(() => String(route.params.publicId ?? ''))

const linkedOpportunityIds = computed(() => {
  const ids = [
    operations.currentIssue?.linked_opportunity_id,
    operations.currentIssueDetail?.linked_opportunity_id,
  ].filter((value): value is string => Boolean(value))
  return [...new Set(ids)]
})

function formatError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.code}: ${err.message}`
  return fallback
}

async function load(): Promise<void> {
  if (!issueId.value) return
  errorText.value = ''
  try {
    await operations.fetchIssue(issueId.value)
    if (!operations.currentIssue) {
      errorText.value = '未找到可见经营议题'
    }
  } catch (err: unknown) {
    errorText.value = formatError(err, '加载经营议题失败')
  }
}

async function recordDecision(): Promise<void> {
  if (busy.value || !operations.currentIssue) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.recordIssueDecision(operations.currentIssue.public_id, {
      version_no: operations.currentIssue.version_no,
      recommendation_type: recommendationType.value,
      action_summary: actionSummary.value,
    })
    statusMessage.value = '研判已记录（未自动提交提案）'
  } catch (err: unknown) {
    errorText.value = operations.conflictHint || formatError(err, '记录研判失败')
  } finally {
    busy.value = false
  }
}

async function convertIteration(): Promise<void> {
  if (busy.value || !operations.currentIssue) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.convertIssueToIteration(operations.currentIssue.public_id, {
      proposal_owner_public_id: proposalOwner.value,
      idempotency_key: idempotencyKey.value,
      version_no: operations.currentIssue.version_no,
    })
    statusMessage.value = '已转换为迭代提案草稿，不会自动提交'
  } catch (err: unknown) {
    errorText.value = operations.conflictHint || formatError(err, '转换迭代提案失败')
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="ops-issue" data-test="operating-issue-page" v-loading="operations.loading">
    <div class="ops-issue__header">
      <h2>经营议题</h2>
      <el-button :loading="operations.loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="ops-issue__alert"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="ops-issue__alert"
    />
    <el-alert
      v-if="operations.conflictHint"
      type="warning"
      :closable="false"
      :title="operations.conflictHint"
      show-icon
      class="ops-issue__alert"
    />

    <template v-if="operations.currentIssue">
      <p data-test="issue-title">{{ operations.currentIssue.title }}</p>
      <p>
        {{ operations.currentIssue.business_no }} /
        {{ operations.currentIssue.status }} /
        v{{ operations.currentIssue.version_no }}
      </p>
      <p>{{ operations.currentIssue.phenomenon_summary }}</p>

      <h3>快照与信号</h3>
      <p data-test="issue-snapshot">
        快照：{{ operations.currentIssueDetail?.data_snapshot_public_id || '暂无' }}
      </p>
      <ul data-test="issue-signals">
        <li
          v-for="signal in operations.currentIssueDetail?.signals ?? []"
          :key="signal.signal_public_id"
        >
          {{ signal.signal_public_id }}
          <span v-if="signal.is_primary">(主)</span>
        </li>
      </ul>

      <h3>研判记录</h3>
      <ul data-test="issue-decisions">
        <li
          v-for="decision in operations.currentIssueDetail?.decisions ?? []"
          :key="decision.public_id"
        >
          {{ decision.recommendation_type }} — {{ decision.action_summary }}
        </li>
      </ul>

      <div class="ops-issue__form">
        <el-input
          v-model="recommendationType"
          data-test="recommendation-type"
          placeholder="recommendation_type"
        />
        <el-input
          v-model="actionSummary"
          data-test="action-summary"
          placeholder="action_summary"
        />
        <el-button
          data-test="record-decision"
          type="primary"
          :loading="busy"
          :disabled="busy"
          @click="recordDecision"
        >
          记录研判
        </el-button>
      </div>

      <h3>转为迭代提案（仅草稿，不自动提交）</h3>
      <div class="ops-issue__form">
        <el-input
          v-model="proposalOwner"
          data-test="proposal-owner"
          placeholder="proposal_owner_public_id"
        />
        <el-input
          v-model="idempotencyKey"
          data-test="idempotency-key"
          placeholder="idempotency_key"
        />
        <el-button
          data-test="convert-iteration"
          type="warning"
          :loading="busy"
          :disabled="busy"
          @click="convertIteration"
        >
          转换为迭代提案
        </el-button>
      </div>

      <p v-if="linkedOpportunityIds.length" data-test="linked-opportunities">
        关联提案：{{ linkedOpportunityIds.join(', ') }}
      </p>
    </template>
  </div>
</template>

<style scoped>
.ops-issue__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.ops-issue__alert,
.ops-issue__form {
  margin-bottom: 1rem;
}

.ops-issue__form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}
</style>
