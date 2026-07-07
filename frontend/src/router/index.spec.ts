import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { router } from '@/router'
import { useAuthStore } from '@/modules/auth/store'

describe('router guards', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await router.replace('/')
  })

  it('redirects unauthenticated user to login without revealing target', async () => {
    const auth = useAuthStore()
    vi.spyOn(auth, 'fetchMe').mockRejectedValue(new Error('not logged in'))

    await router.push('/documents/secret-id')
    expect(router.currentRoute.value.path).toBe('/login')
    expect(String(router.currentRoute.value.query.next)).toContain('/documents/secret-id')
  })
})
