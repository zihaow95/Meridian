<script setup lang="ts">
import { computed, ref } from 'vue'

import { ApiError } from '@/api/client'
import { useOperationsStore } from '@/modules/operations/store'

const operations = useOperationsStore()
const errorText = ref('')
const statusMessage = ref('')
const busy = ref(false)

const sourcePublicId = ref('')
const batchKey = ref('')
const sourceType = ref('API')
const rowsJson = ref('[]')
const documentVersionId = ref('')
const confirmWarnings = ref(false)
const confirmIdempotencyKey = ref(`confirm-${Date.now()}`)

const overrideSku = ref('')
const overrideChannel = ref('')
const overrideMetric = ref('')
const overrideGranularity = ref('QUARTER')
const overridePeriodStart = ref('')
const overridePeriodEnd = ref('')
const overrideValue = ref('')
const overrideReason = ref('')
const revokeReason = ref('')

const batchRows = computed(() => {
  const rows = operations.batch?.rows
  return Array.isArray(rows) ? (rows as Array<Record<string, unknown>>) : []
})

function formatError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 403 || err.status === 404) {
      return `${err.code}: ${err.message}`
    }
    return `${err.code}: ${err.message}`
  }
  return fallback
}

async function createBatch(): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    let rows: unknown[] | undefined
    if (rowsJson.value.trim()) {
      rows = JSON.parse(rowsJson.value) as unknown[]
    }
    await operations.createBatch({
      source_public_id: sourcePublicId.value,
      batch_key: batchKey.value,
      source_type: sourceType.value,
      rows,
      input_file_version_public_id: documentVersionId.value || null,
    })
    statusMessage.value = `批次已创建：${operations.batch?.status ?? ''}`
  } catch (err: unknown) {
    errorText.value = formatError(err, '创建批次失败')
  } finally {
    busy.value = false
  }
}

async function confirmBatch(): Promise<void> {
  if (busy.value || !operations.batch) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    const result = await operations.confirmBatch(operations.batch.public_id, {
      idempotency_key: confirmIdempotencyKey.value || `confirm-${Date.now()}`,
      confirm_warnings: confirmWarnings.value,
    })
    statusMessage.value = `确认完成：added ${result.added_count}`
  } catch (err: unknown) {
    errorText.value = operations.conflictHint || formatError(err, '确认批次失败')
  } finally {
    busy.value = false
  }
}

async function retryBatch(): Promise<void> {
  if (busy.value || !operations.batch) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.retryBatch(operations.batch.public_id)
    statusMessage.value = `已重试：${operations.batch.status}`
  } catch (err: unknown) {
    errorText.value = formatError(err, '重试批次失败')
  } finally {
    busy.value = false
  }
}

async function loadUnmapped(): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  try {
    await operations.fetchUnmappedRows(operations.batch?.public_id)
  } catch (err: unknown) {
    errorText.value = formatError(err, '加载未映射行失败')
  } finally {
    busy.value = false
  }
}

async function createOverride(): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.createManualOverride({
      sku_public_id: overrideSku.value,
      channel_public_id: overrideChannel.value,
      metric_definition_public_id: overrideMetric.value,
      period_granularity: overrideGranularity.value,
      period_start: overridePeriodStart.value,
      period_end: overridePeriodEnd.value,
      numeric_value: overrideValue.value,
      reason: overrideReason.value,
    })
    statusMessage.value = `人工值已创建：${operations.manualValue?.public_id ?? ''}`
  } catch (err: unknown) {
    errorText.value = formatError(err, '创建人工值失败')
  } finally {
    busy.value = false
  }
}

async function revokeOverride(): Promise<void> {
  if (busy.value || !operations.manualValue) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    await operations.revokeManualOverride(operations.manualValue.public_id, {
      reason: revokeReason.value || 'revoked from workbench',
    })
    statusMessage.value = `人工值已撤销：${operations.manualValue.status}`
  } catch (err: unknown) {
    errorText.value = operations.conflictHint || formatError(err, '撤销人工值失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="ops-batch" data-test="operating-data-batch-page">
    <div class="ops-batch__header">
      <h2>经营数据批次</h2>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="ops-batch__alert"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="ops-batch__alert"
    />
    <el-alert
      v-if="operations.conflictHint"
      type="warning"
      :closable="false"
      :title="operations.conflictHint"
      show-icon
      class="ops-batch__alert"
    />

    <el-form label-width="140px" class="ops-batch__form">
      <el-form-item label="数据源 ID">
        <el-input
          v-model="sourcePublicId"
          data-test="source-public-id"
          placeholder="source_public_id"
        />
      </el-form-item>
      <el-form-item label="批次键">
        <el-input v-model="batchKey" data-test="batch-key" placeholder="batch_key" />
      </el-form-item>
      <el-form-item label="来源类型">
        <el-input v-model="sourceType" data-test="source-type" placeholder="API / CSV / MANUAL" />
      </el-form-item>
      <el-form-item label="JSON 行">
        <el-input
          v-model="rowsJson"
          type="textarea"
          data-test="rows-json"
          placeholder='[{"sku_code":"..."}]'
        />
      </el-form-item>
      <el-form-item label="文件版本 ID">
        <el-input
          v-model="documentVersionId"
          data-test="document-version-id"
          placeholder="可选 document version"
        />
      </el-form-item>
      <el-form-item>
        <el-button
          data-test="create-batch"
          type="primary"
          :loading="busy"
          :disabled="busy"
          @click="createBatch"
        >
          创建批次
        </el-button>
      </el-form-item>
    </el-form>

    <template v-if="operations.batch">
      <p data-test="batch-status">
        状态：{{ operations.batch.status }} / 错误行：{{ operations.batch.error_count }}
      </p>
      <el-table :data="batchRows" style="width: 100%">
        <el-table-column prop="row_number" label="行号" width="80" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="error_code" label="错误" />
      </el-table>

      <div class="ops-batch__actions">
        <label>
          <input
            data-test="confirm-warnings"
            type="checkbox"
            :checked="confirmWarnings"
            @change="confirmWarnings = ($event.target as HTMLInputElement).checked"
          />
          确认警告行
        </label>
        <el-input
          v-model="confirmIdempotencyKey"
          data-test="confirm-idempotency"
          placeholder="idempotency_key"
        />
        <el-button
          data-test="confirm-batch"
          type="primary"
          :loading="busy"
          :disabled="busy"
          @click="confirmBatch"
        >
          确认导入
        </el-button>
        <el-button data-test="retry-batch" :loading="busy" :disabled="busy" @click="retryBatch">
          重试
        </el-button>
        <el-button data-test="load-unmapped" :loading="busy" :disabled="busy" @click="loadUnmapped">
          未映射行
        </el-button>
      </div>
    </template>

    <el-table
      v-if="operations.unmappedRows.length"
      :data="operations.unmappedRows"
      style="width: 100%"
      class="ops-batch__unmapped"
    >
      <el-table-column prop="row_number" label="行号" width="80" />
      <el-table-column prop="status" label="状态" width="120" />
      <el-table-column prop="sku_code" label="SKU" />
    </el-table>

    <h3>人工有效值</h3>
    <el-form label-width="140px" class="ops-batch__form">
      <el-form-item label="SKU">
        <el-input v-model="overrideSku" data-test="override-sku" />
      </el-form-item>
      <el-form-item label="渠道">
        <el-input v-model="overrideChannel" data-test="override-channel" />
      </el-form-item>
      <el-form-item label="指标定义">
        <el-input v-model="overrideMetric" data-test="override-metric" />
      </el-form-item>
      <el-form-item label="粒度">
        <el-input v-model="overrideGranularity" data-test="override-granularity" />
      </el-form-item>
      <el-form-item label="期间起">
        <el-input v-model="overridePeriodStart" data-test="override-period-start" />
      </el-form-item>
      <el-form-item label="期间止">
        <el-input v-model="overridePeriodEnd" data-test="override-period-end" />
      </el-form-item>
      <el-form-item label="数值">
        <el-input v-model="overrideValue" data-test="override-value" />
      </el-form-item>
      <el-form-item label="原因">
        <el-input v-model="overrideReason" data-test="override-reason" />
      </el-form-item>
      <el-form-item>
        <el-button
          data-test="create-override"
          :loading="busy"
          :disabled="busy"
          @click="createOverride"
        >
          创建人工值
        </el-button>
      </el-form-item>
      <el-form-item v-if="operations.manualValue" label="撤销原因">
        <el-input v-model="revokeReason" data-test="revoke-reason" />
        <el-button
          data-test="revoke-override"
          :loading="busy"
          :disabled="busy"
          @click="revokeOverride"
        >
          撤销
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<style scoped>
.ops-batch__header {
  margin-bottom: 1rem;
}

.ops-batch__alert,
.ops-batch__form,
.ops-batch__actions,
.ops-batch__unmapped {
  margin-bottom: 1rem;
}

.ops-batch__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
}
</style>
