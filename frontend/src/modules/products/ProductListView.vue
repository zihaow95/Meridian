<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useProductStore, type ProductSummary } from '@/modules/products/store'

const router = useRouter()
const products = useProductStore()
const errorText = ref('')
const searchText = ref('')

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await products.fetchProducts(searchText.value)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载产品列表失败'
    }
  }
}

onMounted(load)

function openDetail(publicId: string): void {
  router.push(`/products/${publicId}`)
}
</script>

<template>
  <div class="product-list">
    <div class="product-list__header">
      <div>
        <h2>产品档案</h2>
        <p class="product-list__hint">搜索已发布与开发中的产品档案。</p>
      </div>
      <div class="product-list__actions">
        <el-button @click="router.push('/products/import')">存量导入</el-button>
        <el-button :loading="products.loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="product-list__search">
      <el-input v-model="searchText" placeholder="按名称搜索" clearable @keyup.enter="load" />
      <el-button type="primary" @click="load">搜索</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="product-list__error"
    />

    <el-empty v-if="!products.loading && products.items.length === 0" description="暂无产品" />

    <el-table
      v-else
      v-loading="products.loading"
      :data="products.items"
      style="width: 100%"
      @row-click="(row: ProductSummary) => openDetail(row.public_id)"
    >
      <el-table-column prop="business_no" label="编号" width="140" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="lifecycle_status" label="状态" width="120" />
    </el-table>
  </div>
</template>

<style scoped>
.product-list__header {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.product-list__hint {
  color: #666;
}

.product-list__actions,
.product-list__search {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}

.product-list__search {
  margin-bottom: 1rem;
}

.product-list__error {
  margin-bottom: 1rem;
}
</style>
