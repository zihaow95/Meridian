<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
const reason = typeof route.query.reason === 'string' ? route.query.reason : ''
</script>

<template>
  <el-result
    icon="warning"
    title="无权访问或内容不存在"
    sub-title="请确认你已登录，并拥有访问权限。"
  >
    <template #extra>
      <el-text v-if="reason" type="info">原因：{{ reason }}</el-text>
    </template>
  </el-result>
</template>
