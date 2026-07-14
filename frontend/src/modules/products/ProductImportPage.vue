<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useProductStore } from '@/modules/products/store'

const products = useProductStore()
const router = useRouter()
const csvContent = ref(
  'name,category_code,business_no,brand_code,sku_code,barcode,specification\n' +
    'Legacy yogurt,YOGURT,LEG-001,BRAND-A,SKU-LEG-001,6900000000001,120g\n',
)
const errorText = ref('')
const statusMessage = ref('')
const linkTargetByRow = ref<Record<number, string>>({})
const busy = ref(false)
const lastPublishedProductId = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

type DuplicateCandidate = {
  product_public_id?: string
  business_no?: string
  name?: string
  blocking?: boolean
}

type ImportItem = {
  row_number: number
  item_status: string
  baseline_public_id?: string | null
  duplicate_candidates?: DuplicateCandidate[]
  decision?: string | null
}

const importReport = computed(() => products.confirmResult)

onMounted(async () => {
  try {
    await products.fetchProducts('')
  } catch {
    // Product picker stays empty when search is denied.
  }
})

async function uploadAndParse(): Promise<void> {
  if (busy.value) return
  busy.value = true
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
  } finally {
    busy.value = false
  }
}

async function uploadSelectedFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || busy.value) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    const batch = await products.createImportBatchFromFile(file)
    statusMessage.value = `已解析文件 ${file.name}：${batch.total_count} 行，成功 ${batch.success_count} 行`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '文件导入解析失败'
    }
  } finally {
    busy.value = false
    input.value = ''
  }
}

async function downloadTemplate(): Promise<void> {
  errorText.value = ''
  try {
    await products.downloadImportTemplate()
    statusMessage.value = '已下载标准导入模板'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '模板下载失败'
    }
  }
}

async function decideCreate(rowNumber: number): Promise<void> {
  if (!products.importBatch || busy.value) return
  busy.value = true
  errorText.value = ''
  try {
    await products.decideImportItem(products.importBatch.public_id, {
      row_number: rowNumber,
      decision: 'CREATE',
    })
    statusMessage.value = `第 ${rowNumber} 行已决定为新建`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '人工决策失败'
    }
  } finally {
    busy.value = false
  }
}

async function decideSkip(rowNumber: number): Promise<void> {
  if (!products.importBatch || busy.value) return
  busy.value = true
  errorText.value = ''
  try {
    await products.decideImportItem(products.importBatch.public_id, {
      row_number: rowNumber,
      decision: 'SKIP',
    })
    statusMessage.value = `第 ${rowNumber} 行已跳过`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '跳过失败'
    }
  } finally {
    busy.value = false
  }
}

async function decideLink(rowNumber: number): Promise<void> {
  if (!products.importBatch || busy.value) return
  const target = linkTargetByRow.value[rowNumber]
  if (!target) {
    errorText.value = '请选择要关联的既有产品'
    return
  }
  busy.value = true
  errorText.value = ''
  try {
    await products.decideImportItem(products.importBatch.public_id, {
      row_number: rowNumber,
      decision: 'LINK',
      target_product_public_id: target,
    })
    statusMessage.value = `第 ${rowNumber} 行已关联既有产品`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '关联失败'
    }
  } finally {
    busy.value = false
  }
}

function candidateOptions(row: ImportItem): Array<{ label: string; value: string }> {
  const fromDuplicates = (row.duplicate_candidates ?? [])
    .filter((item) => item.product_public_id)
    .map((item) => ({
      label: `${item.business_no ?? ''} ${item.name ?? item.product_public_id}`.trim(),
      value: String(item.product_public_id),
    }))
  if (fromDuplicates.length) return fromDuplicates
  return products.items.map((item) => ({
    label: `${item.business_no} ${item.name}`,
    value: item.public_id,
  }))
}

async function confirmImport(): Promise<void> {
  if (!products.importBatch || busy.value) return
  busy.value = true
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
  } finally {
    busy.value = false
  }
}

async function publishFirstBaseline(): Promise<void> {
  if (busy.value) return
  const items = (products.confirmResult?.items ?? []) as Array<{
    baseline_public_id?: string | null
  }>
  const baselineId = items.find((item) => item.baseline_public_id)?.baseline_public_id
  if (!baselineId) {
    errorText.value = '没有可发布的基线'
    return
  }
  busy.value = true
  try {
    const published = await products.publishLegacyBaseline(baselineId, 'publish-import-ui')
    statusMessage.value = '基线已发布，产品可搜索'
    lastPublishedProductId.value = published.product_public_id
    await products.fetchProducts(published.product_name, { page_size: 20 })
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '基线发布失败'
    }
  } finally {
    busy.value = false
  }
}

function openFirstSearchHit(): void {
  const targetId = lastPublishedProductId.value || products.items[0]?.public_id
  if (targetId) {
    void router.push(`/products/${targetId}`)
  }
}
</script>

<template>
  <div class="product-import">
    <h2>存量产品导入</h2>
    <p class="product-import__hint">
      下载标准模板，上传 Excel/CSV，处理重复候选后确认导入并查看结果报告。
    </p>

    <el-input
      v-model="csvContent"
      type="textarea"
      :rows="6"
      data-test="import-csv"
      class="product-import__csv"
    />

    <div class="product-import__actions">
      <el-button data-test="download-template" @click="downloadTemplate">下载模板</el-button>
      <el-button data-test="choose-import-file" @click="fileInput?.click()"
        >选择 Excel/CSV</el-button
      >
      <input
        ref="fileInput"
        class="product-import__file"
        type="file"
        accept=".csv,.xlsx"
        data-test="import-file"
        @change="uploadSelectedFile"
      />
      <el-button
        type="primary"
        :loading="busy || products.loading"
        :disabled="busy"
        data-test="parse-import"
        @click="uploadAndParse"
      >
        解析文本
      </el-button>
      <el-button
        :disabled="!products.importBatch || busy"
        data-test="confirm-import"
        @click="confirmImport"
      >
        确认导入
      </el-button>
      <el-button
        :disabled="!products.confirmResult || busy"
        data-test="publish-baseline"
        @click="publishFirstBaseline"
      >
        发布基线
      </el-button>
      <el-button
        v-if="products.items.length"
        data-test="open-imported-product"
        @click="openFirstSearchHit"
      >
        打开已导入产品
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
      data-test="import-status"
    />

    <el-card v-if="importReport" class="product-import__report" data-test="import-report">
      <template #header>导入结果报告</template>
      <p>
        新建 {{ importReport.created_count }} / 关联 {{ importReport.linked_count }} / 跳过
        {{ importReport.skipped_count }} / 失败 {{ importReport.failed_count }}
      </p>
    </el-card>

    <el-table
      v-if="products.importBatch?.items?.length"
      :data="products.importBatch.items"
      data-test="import-items"
      class="product-import__table"
    >
      <el-table-column prop="row_number" label="行号" width="80" />
      <el-table-column prop="item_status" label="状态" width="120" />
      <el-table-column prop="decision" label="决策" width="100" />
      <el-table-column label="重复候选" min-width="180">
        <template #default="{ row }">
          <span data-test="duplicate-candidates">
            {{ JSON.stringify((row as ImportItem).duplicate_candidates ?? []) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="baseline_public_id" label="基线 ID" min-width="160" />
      <el-table-column label="操作" min-width="320">
        <template #default="{ row }">
          <div class="product-import__decide">
            <el-button
              size="small"
              :disabled="busy"
              data-test="decide-create"
              @click="decideCreate((row as ImportItem).row_number)"
            >
              新建
            </el-button>
            <el-button
              size="small"
              :disabled="busy"
              data-test="decide-skip"
              @click="decideSkip((row as ImportItem).row_number)"
            >
              跳过
            </el-button>
            <el-select
              v-model="linkTargetByRow[(row as ImportItem).row_number]"
              clearable
              placeholder="选择既有产品"
              size="small"
              data-test="link-target"
              style="width: 160px"
            >
              <el-option
                v-for="option in candidateOptions(row as ImportItem)"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-button
              size="small"
              :disabled="busy"
              data-test="decide-link"
              @click="decideLink((row as ImportItem).row_number)"
            >
              关联
            </el-button>
          </div>
        </template>
      </el-table-column>
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
  flex-wrap: wrap;
}

.product-import__file {
  display: none;
}

.product-import__message,
.product-import__report,
.product-import__table {
  margin-bottom: 1rem;
}

.product-import__decide {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
}
</style>
