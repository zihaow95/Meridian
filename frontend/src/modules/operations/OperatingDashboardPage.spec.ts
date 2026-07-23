import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, ref } from 'vue'

const routeQuery = ref<Record<string, string>>({ product: 'prod-1' })

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useRoute: () => ({ query: routeQuery.value, params: {} }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import OperatingDashboardPage from '@/modules/operations/OperatingDashboardPage.vue'
import { useOperationsStore } from '@/modules/operations/store'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['loading', 'disabled'],
    setup(props, { slots, attrs }) {
      return () =>
        h(
          'button',
          { ...attrs, disabled: props.loading || props.disabled ? true : undefined },
          slots.default?.(),
        )
    },
  }),
  'el-input': defineComponent({
    name: 'ElInputStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit, attrs }) {
      return () =>
        h('input', {
          ...attrs,
          value: props.modelValue as string,
          onInput: (event: Event) =>
            emit('update:modelValue', (event.target as HTMLInputElement).value),
        })
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

describe('OperatingDashboardPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    routeQuery.value = { product: 'prod-1' }
  })

  it('loads product summary and drills a chosen sku_breakdown entry', async () => {
    vi.mocked(apiFetch).mockImplementation(async (url: string) => {
      if (url.startsWith('/api/v1/products/prod-1/operating-summary')) {
        return {
          items: [
            {
              grain_type: 'PRODUCT',
              grain_public_id: 'prod-1',
              metric_code: 'SALES_QTY',
              coverage_rate: '0.42',
              status: 'INSUFFICIENT',
              value: '10',
              has_manual_value: true,
              sku_breakdown: [
                {
                  sku_public_id: 'sku-1',
                  value: '4',
                  status: 'INSUFFICIENT',
                  coverage_rate: '0.42',
                  has_manual_value: false,
                  calculated_at: '2026-03-01T00:00:00Z',
                },
                {
                  sku_public_id: 'sku-2',
                  value: '6',
                  status: 'OK',
                  coverage_rate: '1.00',
                  has_manual_value: true,
                  calculated_at: '2026-03-02T00:00:00Z',
                },
              ],
            },
          ],
        }
      }
      if (url.startsWith('/api/v1/skus/sku-2/operating-summary')) {
        return {
          items: [
            {
              grain_type: 'SKU',
              grain_public_id: 'sku-2',
              channel_public_id: 'ch-9',
              metric_code: 'SALES_QTY',
              coverage_rate: '1.00',
              status: 'OK',
              value: '6',
              has_manual_value: true,
              calculated_at: '2026-03-02T00:00:00Z',
            },
          ],
        }
      }
      if (url.startsWith('/api/v1/skus/sku-1/operating-summary')) {
        throw new Error('must drill the clicked SKU, not the first one')
      }
      throw new Error(`unexpected ${url}`)
    })

    const wrapper = mount(OperatingDashboardPage, { global: { stubs } })
    await flush()
    expect(wrapper.text()).toContain('INSUFFICIENT')
    expect(wrapper.text()).toContain('手工值')

    const buttons = wrapper.findAll('[data-test="drill-sku"]')
    expect(buttons.length).toBe(2)
    await buttons[1].trigger('click')
    await flush()
    expect(useOperationsStore().skuSummary?.items.length).toBe(1)
    expect(wrapper.text()).toContain('ch-9')
    expect(
      vi.mocked(apiFetch).mock.calls.some(([url]) => String(url).includes('/skus/sku-2/')),
    ).toBe(true)
  })
})
