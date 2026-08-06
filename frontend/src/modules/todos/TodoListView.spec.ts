import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

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
    push.mockReset()
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

  it('uses SPA navigation for operations and retirement deep links', async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      {
        public_id: '1',
        title: 'Ops',
        status: 'OPEN',
        due_at: null,
        deep_link: '/operations/issues/issue-1',
      },
    ])
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })

    const opsStubs = {
      ...stubs,
      'el-table-column': defineComponent({
        name: 'ElTableColumnStub',
        setup(_, { slots }) {
          return () =>
            h(
              'div',
              slots.default?.({
                row: {
                  deep_link: '/operations/issues/issue-1',
                  title: 't',
                  status: 'OPEN',
                },
              }),
            )
        },
      }),
    }
    const opsWrapper = mount(TodoListView, {
      global: {
        stubs: opsStubs,
        directives: { loading: () => {} },
      },
    })
    await flush()
    await opsWrapper.get('[data-test="open-todo"]').trigger('click')
    expect(push).toHaveBeenCalledWith('/operations/issues/issue-1')

    push.mockReset()
    const retirementStubs = {
      ...stubs,
      'el-table-column': defineComponent({
        name: 'ElTableColumnStub',
        setup(_, { slots }) {
          return () =>
            h(
              'div',
              slots.default?.({
                row: {
                  deep_link: '/retirement-plans/plan-1',
                  title: 't',
                  status: 'OPEN',
                },
              }),
            )
        },
      }),
    }
    const retirementWrapper = mount(TodoListView, {
      global: {
        stubs: retirementStubs,
        directives: { loading: () => {} },
      },
    })
    await flush()
    await retirementWrapper.get('[data-test="open-todo"]').trigger('click')
    expect(push).toHaveBeenCalledWith('/retirement-plans/plan-1')
    expect(assign).not.toHaveBeenCalled()
  })

  it('refuses an unknown deep link without assigning the window location', async () => {
    vi.mocked(apiFetch).mockResolvedValue([
      { public_id: '1', title: 'Mine', status: 'OPEN', due_at: null, deep_link: '/demo' },
    ])
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const wrapper = mount(TodoListView, {
      global: { stubs, directives: { loading: () => {} } },
    })
    await flush()
    await wrapper.get('[data-test="open-todo"]').trigger('click')
    expect(push).not.toHaveBeenCalled()
    expect(assign).not.toHaveBeenCalled()
    expect(wrapper.get('[data-test="todo-error"]').text()).toContain('无权访问或内容不存在')
  })
})
