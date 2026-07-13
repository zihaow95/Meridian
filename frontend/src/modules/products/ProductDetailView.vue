<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import { useProductStore } from '@/modules/products/store'

const route = useRoute()
const products = useProductStore()
const errorText = ref('')
const statusMessage = ref('')
const sourceSystem = ref('ERP')
const objectType = ref('PRODUCT')
const externalId = ref('')

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await products.fetchProductDetail(String(route.params.publicId))
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载产品详情失败'
    }
  }
}

async function saveBinding(): Promise<void> {
  if (!products.detail) return
  errorText.value = ''
  statusMessage.value = ''
  try {
    await products.upsertExternalBinding(products.detail.public_id, {
      source_system: sourceSystem.value,
      object_type: objectType.value,
      external_id: externalId.value,
    })
    statusMessage.value = '外部绑定已保存'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '保存外部绑定失败'
    }
  }
}

onMounted(load)
</script>

<template>
  <div class="product-detail" v-loading="products.loading">
    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="product-detail__error"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="product-detail__error"
    />

    <template v-if="products.detail">
      <h2 data-test="product-name">{{ products.detail.name }}</h2>
      <p class="product-detail__meta">
        <span>{{ products.detail.business_no }}</span>
        <span>{{ products.detail.lifecycle_status }}</span>
        <span>{{ products.detail.category_code }}</span>
      </p>
      <p v-if="products.detail.formula_summary" data-test="formula-summary">
        {{ products.detail.formula_summary }}
      </p>

      <h3>版本与 SKU</h3>
      <el-card
        v-for="version in products.detail.versions"
        :key="version.public_id"
        class="product-detail__version"
      >
        <p>
          <strong>{{ version.version_code }}</strong>
          {{ version.version_name }} ({{ version.status }})
        </p>
        <ul>
          <li v-for="sku in version.skus" :key="sku.public_id">
            {{ sku.sku_code }} — {{ sku.name }} {{ sku.specification }}
          </li>
        </ul>
      </el-card>

      <el-card class="product-detail__bindings" data-test="external-bindings">
        <template #header>外部绑定</template>
        <ul v-if="products.detail.external_bindings?.length">
          <li
            v-for="binding in products.detail.external_bindings"
            :key="binding.public_id"
            data-test="external-binding-row"
          >
            {{ binding.source_system }} / {{ binding.object_type }} / {{ binding.external_id }}
          </li>
        </ul>
        <p v-else data-test="external-bindings-empty">暂无外部绑定</p>
        <el-form label-width="100px" class="product-detail__binding-form">
          <el-form-item label="来源系统">
            <el-input v-model="sourceSystem" data-test="binding-source-system" />
          </el-form-item>
          <el-form-item label="对象类型">
            <el-input v-model="objectType" data-test="binding-object-type" />
          </el-form-item>
          <el-form-item label="外部编码">
            <el-input v-model="externalId" data-test="binding-external-id" />
          </el-form-item>
          <el-button data-test="save-external-binding" type="primary" @click="saveBinding">
            保存绑定
          </el-button>
        </el-form>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.product-detail__meta {
  display: flex;
  gap: 1rem;
  color: #666;
}

.product-detail__version,
.product-detail__bindings,
.product-detail__error {
  margin-bottom: 0.75rem;
}

.product-detail__binding-form {
  margin-top: 1rem;
}
</style>
