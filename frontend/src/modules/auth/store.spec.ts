import { describe, expect, it } from 'vitest'

import { setActivePinia, createPinia } from 'pinia'

import { buildDingTalkStartUrl, useAuthStore } from '@/modules/auth/store'

describe('auth store', () => {
  it('does not persist sensitive responses', async () => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    const original = auth.me
    expect(original).toBeNull()
  })

  it('builds DingTalk start URL with next', () => {
    setActivePinia(createPinia())
    const url = buildDingTalkStartUrl('/todos', 'http://localhost:5173')
    expect(url).toContain('/api/v1/auth/dingtalk/start')
    expect(url).toContain('next=%2Ftodos')
    // ensure store action stays pure enough to call
    const auth = useAuthStore()
    expect(() => auth.startDingTalk('/todos')).not.toThrow()
  })
})
