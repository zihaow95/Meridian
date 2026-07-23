<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import { useOperationsStore, type SkuBreakdownItem } from '@/modules/operations/store'

const route = useRoute()
const operations = useOperationsStore()
const errorText = ref('')
const statusMessage = ref('')
const busy = ref(false)

const productPublicId = ref(String(route.query.product ?? ''))
const periodStart = ref('2026-01-01')
const periodEnd = ref('2026-03-31')
const periodGranularity = ref('QUARTER')
const selectedSkuId = ref('')
const selectedChannelId = ref('')

const selectedChannelRow = computed(() => {
  if (!selectedChannelId.value) return null
  return (
    operations.skuSummaryItems.find((row) => row.channel_public_id === selectedChannelId.value) ??
    null
  )
})

const selectedChannelContributors = computed(() => {
  const contributors = selectedChannelRow.value?.contributors
  return Array.isArray(contributors) ? contributors : []
})

function formatError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return `${err.code}: ${err.message}`
  return fallback
}

async function loadProductSummary(): Promise<void> {
  if (!productPublicId.value || busy.value) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.fetchProductSummary(productPublicId.value, {
      period_start: periodStart.value,
      period_end: periodEnd.value,
      period_granularity: periodGranularity.value,
      include_drilldown: true,
    })
  } catch (err: unknown) {
    errorText.value = formatError(err, '加载产品经营汇总失败')
  } finally {
    busy.value = false
  }
}

async function drillSku(skuId: string): Promise<void> {
  if (!skuId || busy.value) return
  selectedSkuId.value = skuId
  selectedChannelId.value = ''
  busy.value = true
  errorText.value = ''
  try {
    await operations.fetchSkuSummary(skuId, {
      period_start: periodStart.value,
      period_end: periodEnd.value,
      period_granularity: periodGranularity.value,
      include_drilldown: true,
    })
  } catch (err: unknown) {
    errorText.value = formatError(err, '加载 SKU 汇总失败')
  } finally {
    busy.value = false
  }
}

function selectChannel(channelPublicId: string | null | undefined): void {
  selectedChannelId.value = String(channelPublicId ?? '')
}

async function exportData(): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    const ticket = await operations.createExport({
      period_start: periodStart.value,
      period_end: periodEnd.value,
      period_granularity: periodGranularity.value,
    })
    window.location.assign(`/api/v1/documents/download/${ticket.token}`)
    statusMessage.value = '已申请导出并开始下载'
  } catch (err: unknown) {
    errorText.value = formatError(err, '导出失败')
  } finally {
    busy.value = false
  }
}

function formatSku(sku: SkuBreakdownItem): string {
  const value = sku.value ?? '—'
  const manual = sku.has_manual_value ? '手工值' : '来源值'
  const updated = sku.calculated_at ?? '—'
  return `SKU ${sku.sku_public_id} / 值 ${value} / ${sku.status} / ${manual} / 更新 ${updated}`
}

function formatContributor(contributor: unknown): string {
  if (!contributor || typeof contributor !== 'object') return String(contributor)
  const row = contributor as Record<string, unknown>
  const type = String(row.type ?? 'UNKNOWN')
  const value = row.numeric_value == null ? '—' : String(row.numeric_value)
  const source = row.source_code == null ? '手工' : String(row.source_code)
  const sensitivity = row.sensitivity_level == null ? '—' : String(row.sensitivity_level)
  return `${type} / 来源 ${source} / 值 ${value} / 敏感级 ${sensitivity}`
}

onMounted(() => {
  if (productPublicId.value) {
    void loadProductSummary()
  }
})
</script>

<template>
  <div class="ops-dashboard" data-test="operating-dashboard-page">
    <div class="ops-dashboard__header">
      <h2>经营看板</h2>
      <el-button data-test="export-data" :loading="busy" :disabled="busy" @click="exportData">
        导出
      </el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="ops-dashboard__alert"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="ops-dashboard__alert"
    />

    <div class="ops-dashboard__filters">
      <el-input
        v-model="productPublicId"
        data-test="product-public-id"
        placeholder="产品 public_id"
      />
      <el-input v-model="periodStart" data-test="period-start" placeholder="period_start" />
      <el-input v-model="periodEnd" data-test="period-end" placeholder="period_end" />
      <el-input
        v-model="periodGranularity"
        data-test="period-granularity"
        placeholder="period_granularity"
      />
      <el-button
        data-test="load-product-summary"
        type="primary"
        :loading="busy"
        :disabled="busy"
        @click="loadProductSummary"
      >
        加载产品汇总
      </el-button>
    </div>

    <h3>产品汇总</h3>
    <ul class="ops-dashboard__summary" data-test="product-summary-list">
      <li
        v-for="(row, index) in operations.productSummaryItems"
        :key="`${row.grain_public_id}-${row.metric_code}-${index}`"
        data-test="summary-row"
      >
        {{ row.metric_code }} / 值 {{ row.value ?? '—' }} / 覆盖率 {{ row.coverage_rate }} /
        {{ row.status }} / 人工值 {{ row.has_manual_value ? '是' : '否' }}
        <div
          v-if="row.sku_breakdown?.length"
          class="ops-dashboard__sku-breakdown"
          data-test="sku-breakdown"
        >
          <button
            v-for="sku in row.sku_breakdown"
            :key="sku.sku_public_id"
            type="button"
            class="ops-dashboard__sku-link"
            data-test="drill-sku"
            :disabled="busy"
            @click="drillSku(sku.sku_public_id)"
          >
            {{ formatSku(sku) }}
          </button>
        </div>
      </li>
    </ul>

    <template v-if="selectedSkuId">
      <h3>SKU 汇总（{{ selectedSkuId }}）</h3>
      <ul class="ops-dashboard__summary" data-test="sku-summary-list">
        <li
          v-for="(row, index) in operations.skuSummaryItems"
          :key="`${row.grain_public_id}-${row.metric_code}-${index}`"
          data-test="sku-summary-row"
        >
          {{ row.metric_code }} / 渠道 {{ row.channel_public_id ?? 'ALL' }} / 值
          {{ row.value ?? '—' }} / 覆盖率 {{ row.coverage_rate }} / {{ row.status }} / 人工值
          {{ row.has_manual_value ? '是' : '否' }} / 更新
          {{ row.calculated_at ?? '—' }}
          <el-button
            v-if="row.channel_public_id"
            link
            type="primary"
            data-test="select-channel"
            @click="selectChannel(row.channel_public_id)"
          >
            查看渠道事实
          </el-button>
        </li>
      </ul>
      <section
        v-if="selectedChannelId && selectedChannelRow"
        class="ops-dashboard__channel-facts"
        data-test="selected-channel"
      >
        <h4>渠道事实（{{ selectedChannelId }}）</h4>
        <p>
          指标 {{ selectedChannelRow.metric_code }} / 值 {{ selectedChannelRow.value ?? '—' }} /
          {{ selectedChannelRow.status }} / 覆盖率
          {{ selectedChannelRow.coverage_rate }}
        </p>
        <ul data-test="channel-contributors">
          <li
            v-for="(contributor, index) in selectedChannelContributors"
            :key="index"
            data-test="channel-contributor"
          >
            {{ formatContributor(contributor) }}
          </li>
        </ul>
        <p v-if="!selectedChannelContributors.length">暂无贡献明细</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ops-dashboard__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.ops-dashboard__alert,
.ops-dashboard__filters,
.ops-dashboard__channel-facts {
  margin-bottom: 1rem;
}

.ops-dashboard__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.ops-dashboard__sku-breakdown {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-top: 0.5rem;
}

.ops-dashboard__sku-link {
  text-align: left;
  background: transparent;
  border: 0;
  color: #1d4ed8;
  cursor: pointer;
  padding: 0;
}
</style>
