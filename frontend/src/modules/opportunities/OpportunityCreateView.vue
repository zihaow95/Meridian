<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import ProposalQuotaPanel from '@/modules/opportunities/ProposalQuotaPanel.vue'
import { useOpportunityStore } from '@/modules/opportunities/store'

const router = useRouter()
const opportunities = useOpportunityStore()

const title = ref('')
const publicSummary = ref('')
const marketAnalysis = ref('')
const coreSellingPoints = ref('')
const targetUsersNeeds = ref('')
const suggestedRetailPrice = ref('')
const errorText = ref('')
const saving = ref(false)

const canSubmit = computed(() => {
  return (
    title.value.trim().length > 0 &&
    marketAnalysis.value.trim().length > 0 &&
    coreSellingPoints.value.trim().length > 0 &&
    targetUsersNeeds.value.trim().length > 0 &&
    suggestedRetailPrice.value.trim().length > 0 &&
    publicSummary.value.trim().length > 0
  )
})

async function saveDraft(): Promise<void> {
  errorText.value = ''
  saving.value = true
  try {
    const detail = await opportunities.createOpportunity({
      title: title.value.trim(),
      public_summary: publicSummary.value,
      market_analysis: marketAnalysis.value,
      core_selling_points: coreSellingPoints.value,
      target_users_needs: targetUsersNeeds.value,
      suggested_retail_price: suggestedRetailPrice.value,
    })
    router.push(`/opportunities/${detail.public_id}`)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '保存草稿失败'
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="opportunity-create">
    <div class="opportunity-create__header">
      <h2>新建提案</h2>
      <el-button @click="router.push('/opportunities')">返回列表</el-button>
    </div>

    <ProposalQuotaPanel compact />

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="opportunity-create__error"
    />

    <el-form label-position="top" class="opportunity-create__form">
      <el-form-item label="标题">
        <el-input v-model="title" data-test="title" />
      </el-form-item>
      <el-form-item label="公开摘要">
        <el-input v-model="publicSummary" type="textarea" data-test="public-summary" />
      </el-form-item>
      <el-form-item label="市场分析">
        <el-input v-model="marketAnalysis" type="textarea" data-test="market-analysis" />
      </el-form-item>
      <el-form-item label="核心卖点">
        <el-input v-model="coreSellingPoints" type="textarea" data-test="core-selling-points" />
      </el-form-item>
      <el-form-item label="目标用户与需求">
        <el-input v-model="targetUsersNeeds" type="textarea" data-test="target-users-needs" />
      </el-form-item>
      <el-form-item label="建议零售价">
        <el-input v-model="suggestedRetailPrice" data-test="suggested-retail-price" />
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          data-test="submit-proposal"
          :disabled="!canSubmit || saving"
          :loading="saving"
          @click="saveDraft"
        >
          保存草稿并进入工作台
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<style scoped>
.opportunity-create__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.opportunity-create__error {
  margin-bottom: 1rem;
}

.opportunity-create__form {
  max-width: 720px;
}
</style>
