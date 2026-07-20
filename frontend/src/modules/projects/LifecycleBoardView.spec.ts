import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
  useRoute: () => ({ query: {}, params: {} }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import LifecycleBoardView from '@/modules/projects/LifecycleBoardView.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['loading'],
    setup(props, { slots, attrs }) {
      return () =>
        h('button', { ...attrs, disabled: props.loading ? true : undefined }, slots.default?.())
    },
  }),
  'el-select': defineComponent({
    name: 'ElSelectStub',
    props: ['modelValue'],
    emits: ['update:modelValue', 'change'],
    setup(props, { emit }) {
      return () =>
        h('select', {
          'data-test': 'filter-status',
          value: props.modelValue as string,
          onInput: (event: Event) => {
            const value = (event.target as HTMLSelectElement).value
            emit('update:modelValue', value)
          },
          onChange: (event: Event) => {
            const value = (event.target as HTMLSelectElement).value
            emit('update:modelValue', value)
            emit('change', value)
          },
        })
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
    emits: ['row-click'],
    setup(props, { emit }) {
      return () => {
        const rows = (props.data as Array<{ name: string; public_id: string }>) ?? []
        return h(
          'div',
          { class: 'table' },
          rows.map((row) =>
            h(
              'button',
              {
                'data-test': 'project-row',
                onClick: () => emit('row-click', row),
              },
              row.name,
            ),
          ),
        )
      }
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup() {
      return () => h('div')
    },
  }),
  'el-pagination': defineComponent({
    name: 'ElPaginationStub',
    props: ['total', 'currentPage', 'pageSize'],
    emits: ['current-change'],
    setup(props, { emit }) {
      return () =>
        h(
          'button',
          {
            'data-test': 'next-page',
            onClick: () => emit('current-change', (props.currentPage as number) + 1),
          },
          `page ${props.currentPage}`,
        )
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('LifecycleBoardView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    push.mockReset()
  })

  it('renders paginated project list from the API', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [
        {
          public_id: 'proj-1',
          business_no: 'PRJ-001',
          name: 'Yogurt launch',
          project_type: 'NEW_PRODUCT',
          status: 'EXECUTING',
          leader_public_id: 'leader-1',
          current_stage_code: 'D3',
        },
      ],
      page: 1,
      page_size: 20,
      count: 30,
    })

    const wrapper = mount(LifecycleBoardView, { global: { stubs } })
    await flush()

    expect(wrapper.text()).toContain('Yogurt launch')
    expect(wrapper.text()).toContain('page 1')
    expect(apiFetch).toHaveBeenCalledWith('/api/v1/projects?page=1&page_size=20')
  })

  it('applies status filter when changed', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [],
      page: 1,
      page_size: 20,
      count: 0,
    })

    const wrapper = mount(LifecycleBoardView, { global: { stubs } })
    await flush()
    vi.mocked(apiFetch).mockClear()

    const select = wrapper.findComponent({ name: 'ElSelectStub' })
    await select.vm.$emit('update:modelValue', 'EXECUTING')
    await flush()

    expect(apiFetch).toHaveBeenCalledWith('/api/v1/projects?page=1&page_size=20&status=EXECUTING')
  })

  it('navigates to project workbench on row click', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      items: [
        {
          public_id: 'proj-9',
          business_no: 'PRJ-009',
          name: 'Click target',
          project_type: 'NEW_PRODUCT',
          status: 'EXECUTING',
          leader_public_id: 'leader-1',
          current_stage_code: 'D1',
        },
      ],
      page: 1,
      page_size: 20,
      count: 1,
    })

    const wrapper = mount(LifecycleBoardView, { global: { stubs } })
    await flush()
    await wrapper.get('[data-test="project-row"]').trigger('click')

    expect(push).toHaveBeenCalledWith('/projects/proj-9')
  })
})
