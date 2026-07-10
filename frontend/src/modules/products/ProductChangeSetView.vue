<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import ProductPublicationPanel from '@/modules/products/ProductPublicationPanel.vue'
import { useProductStore } from '@/modules/products/store'

const route = useRoute()
const products = useProductStore()
const errorText = ref('')

const changeSetPublicId = computed(() => String(route.params.publicId))

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

    <template v-if="products.changeSet">
      <h2 data-test="change-set-title">{{ products.changeSet.title }}</h2>
      <p class="product-change-set__meta">
        <span data-test="change-set-status">{{ products.changeSet.status }}</span>
        <span>{{ products.changeSet.change_type }}</span>
        <span>v{{ products.changeSet.version_no }}</span>
      </p>

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

.product-change-set__error {
  margin-bottom: 1rem;
}
</style>
