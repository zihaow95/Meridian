<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useAuthStore } from '@/modules/auth/store'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const nonProduction = !import.meta.env.PROD
// Optional extra gate for builds that still want to hide the form while the
// backend capability remains on. Production builds never show this path.
const vitePilotEnabled = import.meta.env.VITE_ENABLE_PILOT_PASSWORD_LOGIN !== 'false'
const loginKey = ref('active-user')
const organizationPublicId = ref('')
const employeeNo = ref('')
const password = ref('')
const errorText = ref('')

// Backend capability is authoritative: LAN pilot sets ENABLE_DEV_LOGIN=false so
// the login_key route stays unavailable even if a Vite env flag is left on.
const showDevLogin = computed(
  () =>
    import.meta.env.DEV &&
    import.meta.env.VITE_ENABLE_DEV_LOGIN === 'true' &&
    auth.capabilities?.dev_login === true,
)

const showPilotLogin = computed(
  () => nonProduction && vitePilotEnabled && auth.capabilities?.pilot_password_login === true,
)

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

async function onPilotLogin(): Promise<void> {
  errorText.value = ''
  try {
    await auth.pilotLogin({
      organizationPublicId: organizationPublicId.value.trim(),
      employeeNo: employeeNo.value.trim(),
      password: password.value,
    })
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

onMounted(async () => {
  try {
    await auth.fetchCapabilities()
  } catch {
    // Capabilities stay null; pilot form remains hidden.
  }
})
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

      <div v-if="showPilotLogin" class="login__pilot" data-test="pilot-login">
        <div class="login__hint">临时账号登录（非生产环境 · 每位参与人独立账号）</div>
        <el-input
          v-model="organizationPublicId"
          placeholder="organization_public_id"
          data-test="pilot-org"
        />
        <el-input v-model="employeeNo" placeholder="工号" data-test="pilot-employee-no" />
        <el-input
          v-model="password"
          type="password"
          show-password
          placeholder="密码"
          data-test="pilot-password"
        />
        <el-button
          :loading="auth.loading"
          data-test="pilot-submit"
          type="warning"
          @click="onPilotLogin"
        >
          临时账号登录
        </el-button>
      </div>

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

.login__dev,
.login__pilot {
  display: grid;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.login__hint {
  color: #666;
  font-size: 0.9rem;
}
</style>
