<script setup lang="ts"></script>

<template>
  <div class="app-shell">
    <h1>Project Meridian</h1>
    <p class="app-shell__subtitle">Product lifecycle management platform</p>
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
</style>
