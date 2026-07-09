<script setup lang="ts">
defineProps<{
  compact?: boolean
}>()
</script>

<template>
  <el-alert
    type="info"
    :closable="false"
    show-icon
    title="季度额度提示"
    description="提案正式提交时由后端校验提案资格与额度归属；前端仅作提示，不以本地状态代替服务端判定。"
    :class="compact ? 'quota-panel quota-panel--compact' : 'quota-panel'"
  />
</template>

<style scoped>
.quota-panel {
  margin-bottom: 1rem;
}

.quota-panel--compact {
  margin-bottom: 0.75rem;
}
</style>
