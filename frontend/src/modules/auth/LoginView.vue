<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const showDevLogin = import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEV_LOGIN === 'true'
const loginKey = ref('active-user')
const errorText = ref('')

async function onDevLogin(): Promise<void> {
  errorText.value = ''
  try {
    await auth.devLogin(loginKey.value)
    const next = typeof route.query.next === 'string' ? route.query.next : '/todos'
    await router.replace(next)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '登录失败'
    }
  }
}

function onDingTalkLogin(): void {
  const next = typeof route.query.next === 'string' ? route.query.next : '/todos'
  auth.startDingTalk(next)
}
</script>

<template>
  <div class="login">
    <el-card class="login__card">
      <template #header>
        <div class="login__title">登录</div>
      </template>

      <el-alert
        v-if="errorText"
        type="error"
        :closable="false"
        :title="errorText"
        show-icon
        class="login__error"
      />

      <div class="login__actions">
        <el-button type="primary" @click="onDingTalkLogin">钉钉登录</el-button>
      </div>

      <el-divider />

      <div v-if="showDevLogin" class="login__dev">
        <div class="login__hint">开发登录（仅 DEV/TEST）</div>
        <el-input v-model="loginKey" placeholder="login_key" />
        <el-button :loading="auth.loading" @click="onDevLogin">开发登录</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  place-items: center;
  min-height: 60vh;
}

.login__card {
  width: min(520px, 100%);
}

.login__title {
  font-weight: 600;
}

.login__error {
  margin-bottom: 1rem;
}

.login__actions {
  display: flex;
  gap: 0.75rem;
}

.login__dev {
  display: grid;
  gap: 0.75rem;
}

.login__hint {
  color: #666;
  font-size: 0.9rem;
}
</style>
