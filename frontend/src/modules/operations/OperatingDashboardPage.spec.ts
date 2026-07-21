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
  'el-table': defineComponent({
    name: 'ElTableStub',
    props: ['data'],
    setup(props, { slots }) {
      const rows = (props.data as Array<Record<string, unknown>>) ?? []
      return () =>
        h(
          'div',
          { class: 'table' },
          rows.map((row) =>
            h('div', { class: 'summary-row', 'data-test': 'summary-row' }, [
              String(row.coverage_rate ?? ''),
              ' ',
              String(row.status ?? ''),
              ' ',
              String(row.grain_public_id ?? ''),
              slots.default?.({ row }),
            ]),
          ),
        )
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup(_, { slots }) {
      return () => h('div', slots.default?.({ row: {} }))
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

  it('loads product summary and drills into SKU coverage status', async () => {
    vi.mocked(apiFetch).mockImplementation(async (url: string) => {
      if (url.startsWith('/api/v1/products/prod-1/operating-summary')) {
        return {
          items: [
            {
              grain_type: 'SKU',
              grain_public_id: 'sku-1',
              metric_code: 'SALES_QTY',
              coverage_rate: '0.42',
              status: 'INSUFFICIENT',
              value: '10',
            },
          ],
        }
      }
      if (url.startsWith('/api/v1/skus/sku-1/operating-summary')) {
        return {
          items: [
            {
              grain_type: 'CHANNEL',
              grain_public_id: 'ch-1',
              metric_code: 'SALES_QTY',
              coverage_rate: '0.42',
              status: 'INSUFFICIENT',
              value: '10',
            },
          ],
        }
      }
      throw new Error(`unexpected ${url}`)
    })

    const wrapper = mount(OperatingDashboardPage, { global: { stubs } })
    await flush()
    expect(wrapper.text()).toContain('INSUFFICIENT')
    expect(wrapper.text()).toContain('0.42')

    await wrapper.get('[data-test="drill-sku"]').trigger('click')
    await flush()
    expect(useOperationsStore().skuSummary?.items.length).toBe(1)
    expect(wrapper.text()).toContain('ch-1')
  })
})
