import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import ProductPublicationPanel from '@/modules/products/ProductPublicationPanel.vue'

const stubs = {
  'el-card': defineComponent({
    name: 'ElCardStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'card' }, slots.default?.())
    },
  }),
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['disabled', 'loading', 'type'],
    setup(props, { slots, attrs }) {
      return () =>
        h(
          'button',
          { ...attrs, disabled: props.disabled ? true : undefined },
          slots.default?.(),
        )
    },
  }),
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert' }, props.title as string)
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('ProductPublicationPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('shows publication blockers before publish button can be used', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      can_publish: false,
      blocks: [
        {
          code: 'PRODUCT_REQUIRED_FIELD_MISSING',
          message: 'Required product fields are missing.',
        },
      ],
    })

    const wrapper = mount(ProductPublicationPanel, {
      props: { changeSetPublicId: 'change-set-1' },
      global: { stubs },
    })
    await flush()
    expect(wrapper.text()).toContain('PRODUCT_REQUIRED_FIELD_MISSING')
    expect(wrapper.get('[data-test="publish-change-set"]').attributes('disabled')).toBeDefined()
  })
})
