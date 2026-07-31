import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {}, params: {} }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch, ApiError } from '@/api/client'
import RiskSignalCenterPage from '@/modules/operations/RiskSignalCenterPage.vue'
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
  'el-select': defineComponent({
    name: 'ElSelectStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit, attrs, slots }) {
      return () =>
        h(
          'select',
          {
            ...attrs,
            value: props.modelValue as string,
            onChange: (event: Event) =>
              emit('update:modelValue', (event.target as HTMLSelectElement).value),
          },
          slots.default?.(),
        )
    },
  }),
  'el-option': defineComponent({
    name: 'ElOptionStub',
    props: ['label', 'value'],
    setup(props) {
      return () => h('option', { value: props.value as string }, props.label as string)
    },
  }),
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title', 'type'],
    setup(props) {
      return () =>
        h('div', { class: 'alert', 'data-type': props.type as string }, props.title as string)
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
          rows.map((row) => h('div', { class: 'signal-row' }, slots.default?.({ row }))),
        )
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup(_, { slots }) {
      return () => h('div', slots.default?.())
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

const openSignal = {
  public_id: 'sig-1',
  status: 'NEW',
  scope_type: 'SKU',
  scope_id: 'sku-1',
  scope_key: 'sku-1',
  period_start: '2026-01-01',
  period_end: '2026-03-31',
  period_granularity: 'QUARTER',
  coverage_status: 'SUFFICIENT',
  actual_value: '1',
  threshold_value: '10',
  rule_code: 'MIN_QTY',
  closed_reason: '',
}

describe('RiskSignalCenterPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('filters, closes, and escalates risk signals', async () => {
    vi.mocked(apiFetch).mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.startsWith('/api/v1/risk-signals?') || url === '/api/v1/risk-signals') {
        return { items: [openSignal] }
      }
      if (url === '/api/v1/risk-signals/sig-1/view' && init?.method === 'POST') {
        return { ...openSignal, status: 'VIEWED' }
      }
      if (url === '/api/v1/risk-signals/sig-1/close' && init?.method === 'POST') {
        return { ...openSignal, status: 'CLOSED', closed_reason: 'resolved' }
      }
      if (url === '/api/v1/risk-signals/sig-1/escalate' && init?.method === 'POST') {
        return { issue_public_id: 'issue-1', title: 'Escalated', status: 'OPEN' }
      }
      throw new Error(`unexpected ${url}`)
    })

    const wrapper = mount(RiskSignalCenterPage, { global: { stubs } })
    await wrapper.get('[data-test="status-filter"]').setValue('NEW')
    await wrapper.get('[data-test="load-signals"]').trigger('click')
    await flush()
    expect(wrapper.text()).toContain('MIN_QTY')

    await wrapper.get('[data-test="view-signal"]').trigger('click')
    await flush()
    expect(useOperationsStore().riskSignals[0]?.status).toBe('VIEWED')

    await wrapper.get('[data-test="close-reason"]').setValue('resolved')
    await wrapper.get('[data-test="close-signal"]').trigger('click')
    await flush()
    expect(useOperationsStore().riskSignals[0]?.status).toBe('CLOSED')

    useOperationsStore().riskSignals = [{ ...openSignal, status: 'VIEWED' }]
    await wrapper.vm.$nextTick()
    await wrapper.get('[data-test="escalate-title"]').setValue('Escalated')
    await wrapper.get('[data-test="escalate-summary"]').setValue('Need review')
    await wrapper.get('[data-test="escalate-signal"]').trigger('click')
    await flush()
    expect(wrapper.text()).toContain('issue-1')
  })

  it('shows refresh guidance on HTTP 409 and reloads authoritative list', async () => {
    let listCalls = 0
    vi.mocked(apiFetch).mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/risk-signals' || url.startsWith('/api/v1/risk-signals?')) {
        listCalls += 1
        return {
          items: [
            {
              ...openSignal,
              status: listCalls > 1 ? 'CLOSED' : 'NEW',
              closed_reason: listCalls > 1 ? 'already closed' : '',
            },
          ],
        }
      }
      if (url === '/api/v1/risk-signals/sig-1/close' && init?.method === 'POST') {
        throw new ApiError(409, {
          code: 'CONFLICT',
          message: 'version conflict',
          details: {},
          trace_id: 't-409',
        })
      }
      throw new Error(`unexpected ${url}`)
    })

    const wrapper = mount(RiskSignalCenterPage, { global: { stubs } })
    await wrapper.get('[data-test="load-signals"]').trigger('click')
    await flush()
    await wrapper.get('[data-test="close-reason"]').setValue('late close')
    await wrapper.get('[data-test="close-signal"]').trigger('click')
    await flush()

    expect(wrapper.find('.alert').text()).toMatch(/刷新|比较|409|CONFLICT/)
    expect(useOperationsStore().riskSignals[0]?.status).toBe('CLOSED')
    expect(listCalls).toBeGreaterThanOrEqual(2)
  })

  it('hides close action for already closed signals', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [{ ...openSignal, status: 'CLOSED', closed_reason: 'done' }],
    })
    const wrapper = mount(RiskSignalCenterPage, { global: { stubs } })
    await wrapper.get('[data-test="load-signals"]').trigger('click')
    await flush()
    expect(wrapper.find('[data-test="close-signal"]').exists()).toBe(false)
  })
})
