import { defineStore } from 'pinia'

import { apiFetch, ApiError } from '@/api/client'

export type Me = {
  public_id: string
  display_name: string
  status: string
}

export function buildDingTalkStartUrl(next: string, origin: string): string {
  const url = new URL('/api/v1/auth/dingtalk/start', origin)
  url.searchParams.set('next', next)
  return url.toString()
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    me: null as Me | null,
    loading: false,
    lastError: null as ApiError | Error | null,
  }),
  getters: {
    isAuthenticated: (state) => state.me !== null,
  },
  actions: {
    async ensureCsrf(): Promise<void> {
      await apiFetch<void>('/api/v1/auth/csrf')
    },
    async fetchMe(): Promise<Me> {
      this.loading = true
      this.lastError = null
      try {
        const me = await apiFetch<Me>('/api/v1/me')
        this.me = me
        return me
      } catch (err) {
        this.me = null
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
    async devLogin(loginKey: string): Promise<void> {
      this.loading = true
      this.lastError = null
      try {
        await this.ensureCsrf()
        await apiFetch('/api/v1/auth/dev/login', {
          method: 'POST',
          json: { login_key: loginKey },
        })
        await this.fetchMe()
      } catch (err) {
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
    startDingTalk(next = '/'): void {
      window.location.href = buildDingTalkStartUrl(next, window.location.origin)
    },
    async logout(): Promise<void> {
      await this.ensureCsrf()
      await apiFetch<void>('/api/v1/auth/logout', { method: 'POST' })
      this.me = null
    },
  },
})
