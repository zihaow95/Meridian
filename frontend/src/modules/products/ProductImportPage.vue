<script setup lang="ts">
import { ref } from 'vue'

import { ApiError } from '@/api/client'
import { useProductStore } from '@/modules/products/store'

const products = useProductStore()
const csvContent = ref(
  'name,category_code,business_no,brand_code,sku_code,barcode,specification\n' +
    'Legacy yogurt,YOGURT,LEG-001,BRAND-A,SKU-LEG-001,6900000000001,120g\n',
)
const errorText = ref('')
const statusMessage = ref('')

async function uploadAndParse(): Promise<void> {
  errorText.value = ''
  statusMessage.value = ''
  try {
    const batch = await products.createImportBatch(csvContent.value, 'legacy.csv')
    statusMessage.value = `已解析 ${batch.total_count} 行，成功 ${batch.success_count} 行`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '导入解析失败'
    }
  }
}

async function confirmImport(): Promise<void> {
  if (!products.importBatch) return
  errorText.value = ''
  try {
    await products.confirmImportBatch(products.importBatch.public_id, 'confirm-import-ui')
    statusMessage.value = `已确认导入，创建 ${products.confirmResult?.created_count ?? 0} 条基线`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '确认导入失败'
    }
  }
}

async function publishFirstBaseline(): Promise<void> {
  const items = (products.confirmResult?.items ?? []) as Array<{
    baseline_public_id?: string | null
  }>
  const baselineId = items.find((item) => item.baseline_public_id)?.baseline_public_id
  if (!baselineId) {
    errorText.value = '没有可发布的基线'
    return
  }
  try {
    await products.publishLegacyBaseline(baselineId, 'publish-import-ui')
    statusMessage.value = '基线已发布，产品可搜索'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '基线发布失败'
    }
  }
}
</script>

<template>
  <div class="product-import">
    <h2>存量产品导入</h2>
    <p class="product-import__hint">上传 CSV 样例，解析后确认导入并发布基线。</p>

    <el-input
      v-model="csvContent"
      type="textarea"
      :rows="6"
      data-test="import-csv"
      class="product-import__csv"
    />

    <div class="product-import__actions">
      <el-button type="primary" :loading="products.loading" data-test="parse-import" @click="uploadAndParse">
        解析文件
      </el-button>
      <el-button :disabled="!products.importBatch" data-test="confirm-import" @click="confirmImport">
        确认导入
      </el-button>
      <el-button :disabled="!products.confirmResult" data-test="publish-baseline" @click="publishFirstBaseline">
        发布基线
      </el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="product-import__message"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="product-import__message"
    />

    <el-table
      v-if="products.importBatch?.items?.length"
      :data="products.importBatch.items"
      data-test="import-items"
      class="product-import__table"
    >
      <el-table-column prop="row_number" label="行号" width="80" />
      <el-table-column prop="item_status" label="状态" width="140" />
      <el-table-column prop="baseline_public_id" label="基线 ID" />
    </el-table>
  </div>
</template>

<style scoped>
.product-import__hint {
  color: #666;
}

.product-import__csv {
  margin: 1rem 0;
}

.product-import__actions {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.product-import__message {
  margin-bottom: 1rem;
}

.product-import__table {
  margin-top: 1rem;
}
</style>
