<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useProductStore } from '@/modules/products/store'
import type { LegacyBaselineDecision } from '@/modules/products/store'

const products = useProductStore()
const router = useRouter()

const name = ref('')
const businessNo = ref('')
const categoryCode = ref('')
const brandCode = ref('')
const skuCode = ref('')
const specification = ref('')
const barcode = ref('')
const netContentValue = ref('')
const netContentUnit = ref('')
const channelCode = ref('DEFAULT')

const errorText = ref('')
const statusMessage = ref('')
const busy = ref(false)
const linkTarget = ref('')

type DuplicateCandidate = {
  product_public_id?: string
  business_no?: string
  name?: string
  specification?: string
  barcode?: string
  reason?: string
  blocking?: boolean
}

const candidates = ref<DuplicateCandidate[]>([])

const canSubmit = computed(
  () =>
    !busy.value &&
    Boolean(
      name.value.trim() &&
      businessNo.value.trim() &&
      categoryCode.value.trim() &&
      skuCode.value.trim() &&
      channelCode.value.trim(),
    ),
)

const candidateOptions = computed(() =>
  candidates.value
    .filter((candidate) => candidate.product_public_id)
    .map((candidate) => ({
      label: `${candidate.business_no ?? ''} ${candidate.name ?? ''}`.trim(),
      value: String(candidate.product_public_id),
    })),
)

// Keyed on the business number so a retry of the same product — including the
// retry that carries the user's duplicate decision — cannot create a second
// draft.
const idempotencyKey = computed(() => `legacy-baseline-form:${businessNo.value.trim()}`)

function baselinePayload(): Record<string, unknown> {
  return {
    name: name.value.trim(),
    business_no: businessNo.value.trim(),
    category_code: categoryCode.value.trim(),
    brand_code: brandCode.value.trim(),
    sku_code: skuCode.value.trim(),
    specification: specification.value.trim(),
    barcode: barcode.value.trim(),
    net_content_value: netContentValue.value.trim(),
    net_content_unit: netContentUnit.value.trim(),
    channel_code: channelCode.value.trim(),
  }
}

function readCandidates(error: ApiError): DuplicateCandidate[] {
  const raw = error.details?.duplicate_candidates
  return Array.isArray(raw) ? (raw as DuplicateCandidate[]) : []
}

async function submit(
  decision?: LegacyBaselineDecision,
  targetProductPublicId?: string,
): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorText.value = ''
  statusMessage.value = ''
  try {
    const draft = await products.createLegacyBaseline({
      payload: baselinePayload(),
      idempotencyKey: idempotencyKey.value,
      decision,
      targetProductPublicId,
    })
    candidates.value = []
    statusMessage.value = draft.created
      ? '老品基线草稿已创建，可在产品详情关联材料后发布'
      : '该业务编号已存在基线草稿，已打开既有草稿'
    await router.push(`/products/${draft.product_public_id}`)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      candidates.value = readCandidates(err)
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '创建老品基线草稿失败'
    }
  } finally {
    busy.value = false
  }
}

async function createAnyway(): Promise<void> {
  await submit('CREATE')
}

async function linkExisting(): Promise<void> {
  if (!linkTarget.value) {
    errorText.value = '请先选择要关联的既有产品，再确认关联'
    return
  }
  await submit('LINK', linkTarget.value)
}
</script>

<template>
  <div class="legacy-create">
    <h2>存量产品逐一录入</h2>
    <p class="legacy-create__hint">
      逐一录入上市产品的核心字段、一个 SKU
      和一个渠道；材料在产品详情的材料面板中关联，不在此处上传文件。
    </p>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="legacy-create__message"
      data-test="legacy-baseline-error"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="legacy-create__message"
      data-test="legacy-baseline-status"
    />

    <el-form label-width="120px">
      <el-form-item label="产品名称">
        <el-input v-model="name" data-test="legacy-name" />
      </el-form-item>
      <el-form-item label="业务编号">
        <el-input v-model="businessNo" data-test="legacy-business-no" />
      </el-form-item>
      <el-form-item label="品类编码">
        <el-input v-model="categoryCode" data-test="legacy-category-code" />
      </el-form-item>
      <el-form-item label="品牌编码">
        <el-input v-model="brandCode" data-test="legacy-brand-code" />
      </el-form-item>
      <el-form-item label="SKU 编码">
        <el-input v-model="skuCode" data-test="legacy-sku-code" />
      </el-form-item>
      <el-form-item label="规格">
        <el-input v-model="specification" data-test="legacy-specification" />
      </el-form-item>
      <el-form-item label="条码">
        <el-input v-model="barcode" data-test="legacy-barcode" />
      </el-form-item>
      <el-form-item label="净含量">
        <el-input v-model="netContentValue" data-test="legacy-net-content-value" />
      </el-form-item>
      <el-form-item label="净含量单位">
        <el-input v-model="netContentUnit" data-test="legacy-net-content-unit" />
      </el-form-item>
      <el-form-item label="渠道编码">
        <el-input v-model="channelCode" data-test="legacy-channel-code" />
      </el-form-item>
      <el-button
        type="primary"
        :disabled="!canSubmit"
        :loading="busy"
        data-test="submit-legacy-baseline"
        @click="submit()"
      >
        创建基线草稿
      </el-button>
    </el-form>

    <el-card v-if="candidates.length" class="legacy-create__duplicates">
      <template #header>疑似重复产品</template>
      <ul data-test="duplicate-candidates">
        <li v-for="candidate in candidates" :key="candidate.product_public_id ?? candidate.barcode">
          {{ candidate.business_no }} {{ candidate.name }} {{ candidate.specification }}
          <span v-if="candidate.barcode"> / {{ candidate.barcode }}</span>
          <span v-if="candidate.reason"> ({{ candidate.reason }})</span>
        </li>
      </ul>
      <p class="legacy-create__hint">
        系统不会自动合并，请明确选择新建、关联既有产品或放弃本次录入。
      </p>
      <div class="legacy-create__decide">
        <el-button :disabled="busy" data-test="create-anyway" @click="createAnyway">
          仍然新建
        </el-button>
        <el-select
          v-model="linkTarget"
          clearable
          placeholder="选择既有产品"
          data-test="link-target"
          style="width: 220px"
        >
          <el-option
            v-for="option in candidateOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button :disabled="busy" data-test="link-existing" @click="linkExisting">
          关联既有产品
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.legacy-create__hint {
  color: #666;
}

.legacy-create__message,
.legacy-create__duplicates {
  margin-bottom: 1rem;
}

.legacy-create__decide {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
}
</style>
