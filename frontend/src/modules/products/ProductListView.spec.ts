import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import ProductListView from '@/modules/products/ProductListView.vue'
import { useProductStore } from '@/modules/products/store'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['loading', 'type'],
    setup(props, { slots, attrs }) {
      return () =>
        h('button', { ...attrs, disabled: props.loading ? true : undefined }, slots.default?.())
    },
  }),
  'el-input': defineComponent({
    name: 'ElInputStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit }) {
      return () =>
        h('input', {
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
    setup(props) {
      return () => {
        const rows = (props.data as Array<{ name: string }>) ?? []
        return h('div', rows.map((row) => h('div', row.name)))
      }
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup() {
      return () => h('div')
    },
  }),
}

const flush = async () => {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('ProductListView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('renders product search results without sensitive formula fields', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)

    vi.mocked(apiFetch).mockResolvedValue({
      items: [
        {
          public_id: 'prod-1',
          business_no: 'PRD-ACTIVE',
          name: 'High protein yogurt',
          lifecycle_status: 'ACTIVE',
          formula_summary: '12g protein per serving',
        },
      ],
    })

    const wrapper = mount(ProductListView, {
      global: {
        plugins: [pinia],
        stubs,
        directives: {
          loading: () => {},
        },
      },
    })
    await vi.waitFor(() => expect(useProductStore().items.length).toBe(1))
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('High protein yogurt')
    expect(wrapper.text()).not.toContain('formula')
    expect(wrapper.text()).not.toContain('12g protein')
  })
})
