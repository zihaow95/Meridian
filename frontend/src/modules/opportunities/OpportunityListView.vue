<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import ProposalQuotaPanel from '@/modules/opportunities/ProposalQuotaPanel.vue'
import { useOpportunityStore, type OpportunitySummary } from '@/modules/opportunities/store'

const router = useRouter()
const opportunities = useOpportunityStore()
const errorText = ref('')
const activeTab = ref<'all' | 'drafts' | 'active'>('all')

const visibleItems = computed(() => {
  if (activeTab.value === 'drafts') return opportunities.drafts
  if (activeTab.value === 'active') return opportunities.ownedActive
  return opportunities.items
})

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await opportunities.fetchMyOpportunities()
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载提案列表失败'
    }
  }
}

onMounted(load)

function openDetail(publicId: string): void {
  router.push(`/opportunities/${publicId}`)
}

function onRowClick(row: OpportunitySummary): void {
  openDetail(row.public_id)
}
</script>

<template>
  <div class="opportunity-list">
    <div class="opportunity-list__header">
      <div>
        <h2>我的提案</h2>
        <p class="opportunity-list__hint">包含我负责的提案与我参与的联合提案。</p>
      </div>
      <div class="opportunity-list__actions">
        <el-button type="primary" @click="router.push('/opportunities/new')">新建提案</el-button>
        <el-button :loading="opportunities.loading" @click="load">刷新</el-button>
      </div>
    </div>

    <ProposalQuotaPanel />

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="opportunity-list__error"
    />

    <el-tabs v-model="activeTab" class="opportunity-list__tabs">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane label="我的草稿" name="drafts" />
      <el-tab-pane label="进行中" name="active" />
    </el-tabs>

    <el-empty v-if="!opportunities.loading && visibleItems.length === 0" description="暂无提案" />

    <el-table
      v-else
      v-loading="opportunities.loading"
      :data="visibleItems"
      style="width: 100%"
      @row-click="onRowClick"
    >
      <el-table-column prop="business_no" label="编号" width="140" />
      <el-table-column prop="title" label="标题" />
      <el-table-column prop="proposal_status" label="状态" width="140" />
      <el-table-column prop="updated_at" label="更新时间" width="200" />
    </el-table>
  </div>
</template>

<style scoped>
.opportunity-list__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.opportunity-list__actions {
  display: flex;
  gap: 0.5rem;
}

.opportunity-list__hint {
  color: #666;
  margin: 0.25rem 0 0;
}

.opportunity-list__error {
  margin-bottom: 1rem;
}

.opportunity-list__tabs {
  margin-bottom: 1rem;
}
</style>
