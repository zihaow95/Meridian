import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import ProductImportPage from '@/modules/products/ProductImportPage.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['disabled', 'loading', 'type'],
    setup(props, { slots, attrs }) {
      return () =>
        h('button', { ...attrs, disabled: props.disabled ? true : undefined }, slots.default?.())
    },
  }),
  'el-input': defineComponent({
    name: 'ElInputStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit }) {
      return () =>
        h('textarea', {
          value: props.modelValue as string,
          onInput: (event: Event) =>
            emit('update:modelValue', (event.target as HTMLTextAreaElement).value),
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
    setup() {
      return () => h('div', { class: 'table' })
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup() {
      return () => h('div')
    },
  }),
}

describe('ProductImportPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders import workflow controls', () => {
    const wrapper = mount(ProductImportPage, { global: { stubs } })
    expect(wrapper.get('[data-test="parse-import"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="confirm-import"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="publish-baseline"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('存量产品导入')
  })
})
