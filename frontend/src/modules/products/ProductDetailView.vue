<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import { useProductStore } from '@/modules/products/store'

const route = useRoute()
const products = useProductStore()
const errorText = ref('')

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
    </template>
  </div>
</template>

<style scoped>
.product-detail__meta {
  display: flex;
  gap: 1rem;
  color: #666;
}

.product-detail__version {
  margin-bottom: 0.75rem;
}

.product-detail__error {
  margin-bottom: 1rem;
}
</style>
