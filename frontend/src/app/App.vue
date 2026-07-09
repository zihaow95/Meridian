<script setup lang="ts">
import { storeToRefs } from 'pinia'

import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const { me } = storeToRefs(auth)
</script>

<template>
  <div class="app-shell">
    <header class="app-shell__header">
      <div>
        <h1>Project Meridian</h1>
        <p class="app-shell__subtitle">Product lifecycle management platform</p>
      </div>

      <div v-if="me" class="app-shell__me">
        <el-text>{{ me.display_name }}</el-text>
        <el-button link @click="auth.logout">退出</el-button>
      </div>
    </header>

    <nav class="app-shell__nav">
      <RouterLink to="/todos">我的待办</RouterLink>
      <RouterLink to="/opportunities">我的提案</RouterLink>
      <RouterLink to="/lifecycle-board">生命周期看板</RouterLink>
      <RouterLink to="/opportunities/pool">候选机会池</RouterLink>
      <RouterLink to="/admin/configurations">配置</RouterLink>
      <RouterLink to="/admin/documents">文件</RouterLink>
      <RouterLink to="/admin/audit">审计</RouterLink>
      <RouterLink to="/admin/users">用户访问</RouterLink>
    </nav>
    <RouterView />
  </div>
</template>

<style scoped>
.app-shell {
  max-width: 960px;
  margin: 0 auto;
  padding: 2rem 1rem;
}

.app-shell__subtitle {
  color: #666;
}

.app-shell__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.app-shell__me {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.app-shell__nav {
  display: flex;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.app-shell__nav a {
  color: #333;
  text-decoration: none;
}

.app-shell__nav a.router-link-active {
  font-weight: 600;
}
</style>
