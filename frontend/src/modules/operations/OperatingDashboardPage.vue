<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import { useOperationsStore, type OperatingSummaryItem } from '@/modules/operations/store'

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

function firstSkuPublicId(row: OperatingSummaryItem): string {
  const fromBreakdown = row.sku_breakdown?.find((item) => item.sku_public_id)?.sku_public_id
  return String(fromBreakdown ?? '')
}

async function drillSku(row: OperatingSummaryItem): Promise<void> {
  // Product-grain rows use product public_id as grain_public_id; SKU ids live in sku_breakdown.
  const skuId = firstSkuPublicId(row)
  if (!skuId || busy.value) return
  selectedSkuId.value = skuId
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
        {{ row.metric_code }} / {{ row.grain_public_id }} / 覆盖率 {{ row.coverage_rate }} /
        {{ row.status }}
        <div
          v-if="row.sku_breakdown?.length"
          class="ops-dashboard__sku-breakdown"
          data-test="sku-breakdown"
        >
          <span
            v-for="sku in row.sku_breakdown"
            :key="sku.sku_public_id"
            data-test="sku-breakdown-item"
          >
            SKU {{ sku.sku_public_id }} / {{ sku.status }}
          </span>
        </div>
        <el-button
          v-if="firstSkuPublicId(row)"
          link
          type="primary"
          data-test="drill-sku"
          @click="drillSku(row)"
        >
          下钻 SKU
        </el-button>
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
          {{ row.metric_code }} / {{ row.grain_public_id }} / 覆盖率 {{ row.coverage_rate }} /
          {{ row.status }}
        </li>
      </ul>
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
.ops-dashboard__filters {
  margin-bottom: 1rem;
}

.ops-dashboard__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}
</style>
