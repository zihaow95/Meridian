import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch, ApiError } from '@/api/client'
import AuditListView from '@/modules/admin/AuditListView.vue'

const stubs = {
  'el-button': defineComponent({
    setup(_, { slots }) {
      return () => h('button', slots.default?.())
    },
  }),
  'el-alert': defineComponent({
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert' }, props.title as string)
    },
  }),
  'el-empty': defineComponent({
    props: ['description'],
    setup(props) {
      return () => h('div', { class: 'empty' }, props.description as string)
    },
  }),
  'el-table': defineComponent({
    props: ['data'],
    setup(props, { slots }) {
      return () =>
        h('div', { class: 'table' }, [String((props.data as unknown[]).length), slots.default?.()])
    },
  }),
  'el-table-column': defineComponent({
    setup(_, { slots }) {
      return () => h('div', slots.default?.({ row: {} }))
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('AuditListView', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
  })

  it('renders audit events from the API', async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      {
        event_id: 'e1',
        occurred_at: '2026-01-01T00:00:00Z',
        action_code: 'audit.event.read',
        resource_type: 'audit.event',
        resource_public_id: null,
        result: 'SUCCESS',
      },
    ])
    const wrapper = mount(AuditListView, { global: { stubs } })
    await flush()
    expect(wrapper.find('.table').exists()).toBe(true)
  })

  it('shows empty state', async () => {
    vi.mocked(apiFetch).mockResolvedValue([])
    const wrapper = mount(AuditListView, { global: { stubs } })
    await flush()
    expect(wrapper.find('.empty').exists()).toBe(true)
  })

  it('surfaces permission errors with trace id', async () => {
    vi.mocked(apiFetch).mockRejectedValue(
      new ApiError(404, {
        code: 'RESOURCE_NOT_FOUND',
        message: 'denied',
        details: {},
        trace_id: 'trace-audit',
      }),
    )
    const wrapper = mount(AuditListView, { global: { stubs } })
    await flush()
    expect(wrapper.find('.alert').text()).toContain('trace-audit')
  })
})
