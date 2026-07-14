<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useProductStore, type ProductSummary } from '@/modules/products/store'

const route = useRoute()
const router = useRouter()
const products = useProductStore()
const errorText = ref('')
const searchText = ref(typeof route.query.search === 'string' ? route.query.search : '')
const brandCode = ref('')
const categoryCode = ref('')
const lifecycleStatus = ref('')
const skuCode = ref('')
const externalId = ref('')
const channelCode = ref('')

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await products.fetchProducts(searchText.value, {
      brand_code: brandCode.value,
      category_code: categoryCode.value,
      lifecycle_status: lifecycleStatus.value,
      sku_code: skuCode.value,
      external_id: externalId.value,
      channel_code: channelCode.value,
      page: products.page,
      page_size: products.pageSize,
    })
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载产品列表失败'
    }
  }
}

async function onPageChange(page: number): Promise<void> {
  products.page = page
  await load()
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
        <p class="product-list__hint">
          按名称、品牌、品类、状态、SKU、外部编码和渠道筛选产品档案。
        </p>
      </div>
      <div class="product-list__actions">
        <el-button @click="router.push('/products/import')">存量导入</el-button>
        <el-button :loading="products.loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="product-list__search">
      <el-input v-model="searchText" placeholder="名称/编号" clearable @keyup.enter="load" />
      <el-input v-model="brandCode" placeholder="品牌" clearable data-test="filter-brand" />
      <el-input v-model="categoryCode" placeholder="品类" clearable data-test="filter-category" />
      <el-input
        v-model="lifecycleStatus"
        placeholder="状态"
        clearable
        data-test="filter-lifecycle"
      />
      <el-input v-model="skuCode" placeholder="SKU" clearable data-test="filter-sku" />
      <el-input
        v-model="externalId"
        placeholder="外部编码"
        clearable
        data-test="filter-external-id"
      />
      <el-input v-model="channelCode" placeholder="渠道" clearable data-test="filter-channel" />
      <el-button type="primary" data-test="product-search" @click="load">搜索</el-button>
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
      <el-table-column prop="brand_code" label="品牌" width="120" />
      <el-table-column prop="category_code" label="品类" width="120" />
      <el-table-column prop="lifecycle_status" label="状态" width="120" />
    </el-table>

    <el-pagination
      v-if="products.totalCount > 0"
      class="product-list__pagination"
      layout="prev, pager, next, total"
      :current-page="products.page"
      :page-size="products.pageSize"
      :total="products.totalCount"
      data-test="product-pagination"
      @current-change="onPageChange"
    />
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
  flex-wrap: wrap;
}

.product-list__search {
  margin-bottom: 1rem;
}

.product-list__error {
  margin-bottom: 1rem;
}

.product-list__pagination {
  margin-top: 1rem;
  justify-content: flex-end;
}
</style>
