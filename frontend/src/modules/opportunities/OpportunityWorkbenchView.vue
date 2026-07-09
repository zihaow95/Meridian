<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import ProposalQuotaPanel from '@/modules/opportunities/ProposalQuotaPanel.vue'
import { useOpportunityStore } from '@/modules/opportunities/store'

const route = useRoute()
const router = useRouter()
const opportunities = useOpportunityStore()

const errorText = ref('')
const actionMessage = ref('')
const submitting = ref(false)

const publicId = computed(() => String(route.params.publicId))
const detail = computed(() => opportunities.current)
const isDraft = computed(() =>
  ['DRAFT', 'NEEDS_INFO'].includes(detail.value?.proposal_status ?? ''),
)
const canSubmit = computed(() =>
  ['DRAFT', 'NEEDS_INFO'].includes(detail.value?.proposal_status ?? ''),
)
const canWithdraw = computed(() => detail.value?.proposal_status === 'SUBMITTED')
const canOpenReview = computed(() => detail.value?.proposal_status === 'SUBMITTED')
const canDecide = computed(() => detail.value?.proposal_status === 'IN_REVIEW')

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await opportunities.fetchDetail(publicId.value)
    await opportunities.fetchVersions(publicId.value)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载机会工作台失败'
    }
  }
}

onMounted(load)

async function submitProposal(): Promise<void> {
  if (!detail.value) return
  submitting.value = true
  actionMessage.value = ''
  try {
    await opportunities.submitOpportunity(
      detail.value.public_id,
      detail.value.version_no,
      `submit-${detail.value.public_id}`,
    )
    actionMessage.value = '提案已提交，等待后端确认状态。'
    await load()
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

async function withdrawProposal(): Promise<void> {
  if (!detail.value) return
  submitting.value = true
  actionMessage.value = ''
  try {
    await opportunities.withdrawOpportunity(detail.value.public_id, detail.value.version_no)
    actionMessage.value = '提案已撤回。'
    await load()
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '撤回失败'
    }
  } finally {
    submitting.value = false
  }
}

async function openReviewCycle(): Promise<void> {
  if (!detail.value) return
  submitting.value = true
  actionMessage.value = ''
  try {
    const gate = await opportunities.openProposalReviewCycle(detail.value.public_id)
    router.push(`/stage-gates/${gate.public_id}/decide`)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      actionMessage.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      actionMessage.value = '开启评审失败'
    }
  } finally {
    submitting.value = false
  }
}

function openGateDecision(): void {
  const gateId = opportunities.activeStageGate?.public_id
  if (gateId) {
    router.push(`/stage-gates/${gateId}/decide`)
    return
  }
  actionMessage.value = '请先开启评审周期，或从待办进入阶段门。'
}
</script>

<template>
  <div class="workbench" data-test="opportunity-workbench">
    <div class="workbench__header">
      <div>
        <h2>{{ detail?.title ?? '机会工作台' }}</h2>
        <p v-if="detail" class="workbench__meta">
          <span data-test="proposal-status">{{ detail.proposal_status }}</span>
          · 版本 {{ detail.version_no }} · {{ detail.business_no }}
        </p>
      </div>
      <el-button @click="router.push('/opportunities')">返回列表</el-button>
    </div>

    <ProposalQuotaPanel compact />

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="workbench__alert"
    />
    <el-alert
      v-if="actionMessage"
      :type="actionMessage.includes('trace') ? 'error' : 'success'"
      :closable="false"
      :title="actionMessage"
      show-icon
      class="workbench__alert"
    />

    <el-card v-if="detail" class="workbench__card">
      <template #header>当前阶段与内容</template>
      <p><strong>公开摘要：</strong>{{ detail.public_summary || '—' }}</p>
      <template v-if="detail.current_version">
        <p><strong>市场分析：</strong>{{ detail.current_version.market_analysis || '—' }}</p>
        <p><strong>核心卖点：</strong>{{ detail.current_version.core_selling_points || '—' }}</p>
        <p>
          <strong>目标用户与需求：</strong>{{ detail.current_version.target_users_needs || '—' }}
        </p>
        <p>
          <strong>建议零售价：</strong>{{ detail.current_version.suggested_retail_price ?? '—' }}
        </p>
      </template>
    </el-card>

    <el-card class="workbench__card">
      <template #header>版本链</template>
      <el-empty v-if="opportunities.versions.length === 0" description="暂无版本" />
      <el-table v-else :data="opportunities.versions" size="small">
        <el-table-column prop="version_number" label="版本" width="80" />
        <el-table-column prop="version_status" label="状态" width="120" />
        <el-table-column prop="submitted_at" label="提交时间" />
      </el-table>
    </el-card>

    <el-card class="workbench__card">
      <template #header>阶段门与后续动作</template>
      <p class="workbench__hint">
        成员、评估、文件与来源关系的完整视图将在后续迭代补齐；写操作以后端响应为准。
      </p>
      <div class="workbench__actions">
        <el-button
          v-if="canSubmit"
          type="primary"
          data-test="submit-proposal"
          :loading="submitting"
          @click="submitProposal"
        >
          正式提交
        </el-button>
        <el-button v-if="canWithdraw" :loading="submitting" @click="withdrawProposal">
          撤回提案
        </el-button>
        <el-button
          v-if="canOpenReview"
          type="warning"
          :loading="submitting"
          @click="openReviewCycle"
        >
          开启提案评审
        </el-button>
        <el-button v-if="canDecide" type="danger" @click="openGateDecision">记录重大决策</el-button>
        <el-button v-if="isDraft" @click="router.push('/opportunities/new')"
          >继续编辑草稿</el-button
        >
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.workbench__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.workbench__meta {
  color: #666;
  margin: 0.25rem 0 0;
}

.workbench__alert {
  margin-bottom: 1rem;
}

.workbench__card {
  margin-bottom: 1rem;
}

.workbench__hint {
  color: #666;
  margin-top: 0;
}

.workbench__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
</style>
