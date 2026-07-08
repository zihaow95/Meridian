import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch, ApiError } from '@/api/client'
import TodoListView from '@/modules/todos/TodoListView.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    setup(_, { slots }) {
      return () => h('button', slots.default?.())
    },
  }),
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert' }, props.title as string)
    },
  }),
  'el-empty': defineComponent({
    name: 'ElEmptyStub',
    props: ['description'],
    setup(props) {
      return () => h('div', { class: 'empty' }, props.description as string)
    },
  }),
  'el-table': defineComponent({
    name: 'ElTableStub',
    props: ['data'],
    setup(props, { slots }) {
      return () =>
        h('div', { class: 'table' }, [String((props.data as unknown[]).length), slots.default?.()])
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup(_, { slots }) {
      return () =>
        h('div', slots.default?.({ row: { deep_link: '/demo', title: 't', status: 'OPEN' } }))
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('TodoListView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('renders todos returned by the API', async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { public_id: '1', title: 'Mine', status: 'OPEN', due_at: null, deep_link: '/x' },
    ])
    const wrapper = mount(TodoListView, { global: { stubs } })
    await flush()
    expect(wrapper.text()).toContain('我的待办')
    expect(wrapper.find('.table').exists()).toBe(true)
  })

  it('shows empty state when no todos', async () => {
    vi.mocked(apiFetch).mockResolvedValue([])
    const wrapper = mount(TodoListView, { global: { stubs } })
    await flush()
    expect(wrapper.find('.empty').exists()).toBe(true)
  })

  it('shows an error message with trace id on failure', async () => {
    vi.mocked(apiFetch).mockRejectedValue(
      new ApiError(404, {
        code: 'RESOURCE_NOT_FOUND',
        message: 'nope',
        details: {},
        trace_id: 'trace-xyz',
      }),
    )
    const wrapper = mount(TodoListView, { global: { stubs } })
    await flush()
    expect(wrapper.find('.alert').text()).toContain('RESOURCE_NOT_FOUND')
    expect(wrapper.find('.alert').text()).toContain('trace-xyz')
  })
})
