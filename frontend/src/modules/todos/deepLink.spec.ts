import { describe, expect, it } from 'vitest'

import { resolveInternalDeepLink } from '@/modules/todos/deepLink'

describe('resolveInternalDeepLink', () => {
  it('accepts allowlisted internal routes', () => {
    expect(resolveInternalDeepLink('/products/prod-1')).toEqual({
      ok: true,
      path: '/products/prod-1',
    })
    expect(resolveInternalDeepLink('/operations?product=1').ok).toBe(true)
    expect(resolveInternalDeepLink('/notifications').ok).toBe(true)
  })

  it('refuses external URLs, schemes and unknown paths', () => {
    expect(resolveInternalDeepLink('https://evil.example/x').ok).toBe(false)
    expect(resolveInternalDeepLink('javascript:alert(1)').ok).toBe(false)
    expect(resolveInternalDeepLink('//evil.example/x').ok).toBe(false)
    expect(resolveInternalDeepLink('/unknown-surface').ok).toBe(false)
    expect(resolveInternalDeepLink('').ok).toBe(false)
  })
})
