<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { ApiError } from '@/api/client'
import { useProductStore } from '@/modules/products/store'

const props = defineProps<{
  changeSetPublicId: string
}>()

const products = useProductStore()
const errorText = ref('')
const publishing = ref(false)
const publishMessage = ref('')

const canPublish = computed(
  () => products.publicationValidation?.can_publish === true && !publishing.value,
)

async function loadValidation(): Promise<void> {
  errorText.value = ''
  try {
    await products.validatePublication(props.changeSetPublicId)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '发布预检失败'
    }
  }
}

async function publish(): Promise<void> {
  publishing.value = true
  publishMessage.value = ''
  try {
    await products.publishChangeSet(props.changeSetPublicId, `publish-${props.changeSetPublicId}`)
    publishMessage.value = '发布成功'
    await loadValidation()
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      publishMessage.value = `${err.code}: ${err.message}`
    } else {
      publishMessage.value = '发布失败'
    }
  } finally {
    publishing.value = false
  }
}

onMounted(loadValidation)
</script>

<template>
  <el-card class="publication-panel">
    <template #header>发布预检</template>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="publication-panel__error"
    />

    <ul v-if="products.publicationValidation?.blocks?.length" data-test="publication-blocks">
      <li v-for="block in products.publicationValidation.blocks" :key="block.code">
        {{ block.code }}: {{ block.message }}
      </li>
    </ul>
    <p v-else-if="products.publicationValidation?.can_publish" data-test="publication-ready">
      可以发布
    </p>

    <el-alert
      v-if="publishMessage"
      :title="publishMessage"
      :type="publishMessage === '发布成功' ? 'success' : 'error'"
      show-icon
      :closable="false"
      class="publication-panel__message"
    />

    <el-button
      data-test="publish-change-set"
      type="primary"
      :disabled="!canPublish"
      :loading="publishing"
      @click="publish"
    >
      发布变更集
    </el-button>
  </el-card>
</template>

<style scoped>
.publication-panel__error,
.publication-panel__message {
  margin-bottom: 1rem;
}
</style>
