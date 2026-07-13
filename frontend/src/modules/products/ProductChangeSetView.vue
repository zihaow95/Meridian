<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import ProductPublicationPanel from '@/modules/products/ProductPublicationPanel.vue'
import { useProductStore } from '@/modules/products/store'

const route = useRoute()
const products = useProductStore()
const errorText = ref('')
const statusMessage = ref('')
const effectiveFrom = ref(new Date().toISOString())
const skuCode = ref('SKU-UI-001')
const channelCode = ref('TMALL')

const changeSetPublicId = computed(() => String(route.params.publicId))
const versionNo = computed(() => products.changeSet?.version_no ?? 1)

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await products.fetchChangeSet(changeSetPublicId.value)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载变更集失败'
    }
  }
}

async function saveScope(): Promise<void> {
  errorText.value = ''
  statusMessage.value = ''
  try {
    await products.updateChangeSetScope(changeSetPublicId.value, {
      version_no: versionNo.value,
      effective_from: effectiveFrom.value,
      skus: [
        {
          sku_code: skuCode.value,
          name: products.changeSet?.title ?? 'SKU',
          barcode: '6900000000999',
          specification: '120g',
        },
      ],
      channels: [
        {
          sku_code: skuCode.value,
          channel_code: channelCode.value,
          channel_status: 'ON_SALE',
        },
      ],
    })
    statusMessage.value = '范围已更新'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '更新范围失败'
    }
  }
}

async function submitForConfirmation(): Promise<void> {
  errorText.value = ''
  try {
    await products.submitChangeSet(changeSetPublicId.value)
    statusMessage.value = '已提交确认'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '提交失败'
    }
  }
}

async function approveChangeSet(): Promise<void> {
  errorText.value = ''
  try {
    await products.approveChangeSet(changeSetPublicId.value)
    statusMessage.value = '变更集已批准'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '批准失败'
    }
  }
}

onMounted(load)
</script>

<template>
  <div class="product-change-set" v-loading="products.loading">
    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="product-change-set__error"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="product-change-set__error"
    />

    <template v-if="products.changeSet">
      <h2 data-test="change-set-title">{{ products.changeSet.title }}</h2>
      <p class="product-change-set__meta">
        <span data-test="change-set-status">{{ products.changeSet.status }}</span>
        <span>{{ products.changeSet.change_type }}</span>
        <span>v{{ products.changeSet.version_no }}</span>
      </p>

      <el-card class="product-change-set__scope" data-test="scope-editor">
        <template #header>范围与生效时间</template>
        <el-form label-width="120px">
          <el-form-item label="生效时间">
            <el-input v-model="effectiveFrom" data-test="effective-from" />
          </el-form-item>
          <el-form-item label="SKU 编码">
            <el-input v-model="skuCode" data-test="scope-sku-code" />
          </el-form-item>
          <el-form-item label="渠道">
            <el-input v-model="channelCode" data-test="scope-channel-code" />
          </el-form-item>
          <el-button data-test="save-scope" type="primary" @click="saveScope">保存范围</el-button>
        </el-form>
      </el-card>

      <div class="product-change-set__workflow">
        <el-button data-test="submit-confirmation" @click="submitForConfirmation">
          提交确认
        </el-button>
        <el-button data-test="approve-change-set" type="success" @click="approveChangeSet">
          批准变更集
        </el-button>
      </div>

      <ProductPublicationPanel :change-set-public-id="changeSetPublicId" />
    </template>
  </div>
</template>

<style scoped>
.product-change-set__meta {
  display: flex;
  gap: 1rem;
  color: #666;
  margin-bottom: 1rem;
}

.product-change-set__error,
.product-change-set__scope,
.product-change-set__workflow {
  margin-bottom: 1rem;
}

.product-change-set__workflow {
  display: flex;
  gap: 0.75rem;
}
</style>
