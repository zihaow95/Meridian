import { beforeEach, describe, expect, it, vi } from 'vitest'
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

import { apiFetch } from '@/api/client'
import NotificationCenterView from '@/modules/todos/NotificationCenterView.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['disabled', 'loading', 'type'],
    setup(props, { slots, attrs }) {
      return () =>
        h('button', { ...attrs, disabled: props.disabled ? true : undefined }, slots.default?.())
    },
  }),
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title'],
    setup(props) {
      return () =>
        h('div', { class: 'alert', 'data-test': 'notification-error' }, props.title as string)
    },
  }),
  'el-empty': defineComponent({
    name: 'ElEmptyStub',
    props: ['description'],
    setup(props, { attrs }) {
      return () => h('div', { ...attrs, class: 'empty' }, props.description as string)
    },
  }),
  'el-select': defineComponent({
    name: 'ElSelectStub',
    setup(_, { slots, attrs }) {
      return () => h('select', attrs, slots.default?.())
    },
  }),
  'el-option': defineComponent({
    name: 'ElOptionStub',
    setup() {
      return () => h('option')
    },
  }),
  'el-table': defineComponent({
    name: 'ElTableStub',
    props: ['data'],
    setup(_props, { slots, attrs }) {
      return () => h('div', { ...attrs, class: 'table' }, slots.default?.())
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup(_, { slots }) {
      return () => h('div', slots.default?.({ row: sampleRow }))
    },
  }),
}

const sampleRow = {
  public_id: 'n-1',
  summary: '待办 复核用户状态 需要处理',
  category: 'ACTION_REQUIRED',
  level: 'IMPORTANT',
  status: 'UNREAD',
  deep_link: '/products/prod-1',
  created_at: '2026-08-01T00:00:00Z',
  read_at: null,
  closed_at: null,
  close_reason: '',
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('NotificationCenterView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    push.mockReset()
  })

  it('renders unread count and the notification table', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [sampleRow],
      page: 1,
      page_size: 20,
      count: 1,
      unread_count: 1,
    })
    const wrapper = mount(NotificationCenterView, {
      global: { stubs, directives: { loading: () => {} } },
    })
    await flush()
    expect(wrapper.get('[data-test="unread-count"]').text()).toContain('未读 1')
    expect(wrapper.get('[data-test="notifications-table"]').exists()).toBe(true)
  })

  it('shows empty state when there are no notifications', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
      count: 0,
      unread_count: 0,
    })
    const wrapper = mount(NotificationCenterView, {
      global: { stubs, directives: { loading: () => {} } },
    })
    await flush()
    expect(wrapper.get('[data-test="notifications-empty"]').exists()).toBe(true)
  })

  it('marks a notification read and refreshes the unread count', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        items: [sampleRow],
        page: 1,
        page_size: 20,
        count: 1,
        unread_count: 1,
      })
      .mockResolvedValueOnce({ ...sampleRow, status: 'READ', read_at: '2026-08-01T01:00:00Z' })
      .mockResolvedValueOnce({
        items: [{ ...sampleRow, status: 'READ', read_at: '2026-08-01T01:00:00Z' }],
        page: 1,
        page_size: 20,
        count: 1,
        unread_count: 0,
      })

    const wrapper = mount(NotificationCenterView, {
      global: { stubs, directives: { loading: () => {} } },
    })
    await flush()
    await wrapper.get('[data-test="mark-read"]').trigger('click')
    await flush()

    expect(apiFetch).toHaveBeenCalledWith('/api/v1/notifications/n-1/read', { method: 'POST' })
    expect(wrapper.get('[data-test="unread-count"]').text()).toContain('未读 0')
  })

  it('refuses an unsafe deep link with the same opaque message as a 403', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [{ ...sampleRow, deep_link: 'https://evil.example' }],
      page: 1,
      page_size: 20,
      count: 1,
      unread_count: 1,
    })
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const unsafeStubs = {
      ...stubs,
      'el-table-column': defineComponent({
        name: 'ElTableColumnStub',
        setup(_, { slots }) {
          return () =>
            h(
              'div',
              slots.default?.({
                row: { ...sampleRow, deep_link: 'https://evil.example' },
              }),
            )
        },
      }),
    }
    const wrapper = mount(NotificationCenterView, {
      global: { stubs: unsafeStubs, directives: { loading: () => {} } },
    })
    await flush()
    await wrapper.get('[data-test="open-notification"]').trigger('click')
    expect(push).not.toHaveBeenCalled()
    expect(assign).not.toHaveBeenCalled()
    expect(wrapper.get('[data-test="notification-error"]').text()).toContain('无权访问或内容不存在')
  })
})
