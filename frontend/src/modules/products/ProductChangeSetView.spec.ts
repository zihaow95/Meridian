import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { publicId: 'change-set-1' } }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import ProductChangeSetView from '@/modules/products/ProductChangeSetView.vue'

const stubs = {
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert' }, props.title as string)
    },
  }),
  'el-card': defineComponent({
    name: 'ElCardStub',
    setup(_props, { slots }) {
      return () => h('div', [slots.header?.(), slots.default?.()])
    },
  }),
  'el-form': defineComponent({
    name: 'ElFormStub',
    setup(_props, { slots }) {
      return () => h('form', slots.default?.())
    },
  }),
  'el-form-item': defineComponent({
    name: 'ElFormItemStub',
    setup(_props, { slots }) {
      return () => h('div', slots.default?.())
    },
  }),
  'el-input': defineComponent({
    name: 'ElInputStub',
    props: ['modelValue'],
    setup(props, { attrs }) {
      return () => h('input', { ...attrs, value: props.modelValue as string })
    },
  }),
  'el-button': defineComponent({
    name: 'ElButtonStub',
    setup(_props, { slots, attrs }) {
      return () => h('button', attrs, slots.default?.())
    },
  }),
  ProductPublicationPanel: defineComponent({
    name: 'ProductPublicationPanelStub',
    props: ['changeSetPublicId'],
    setup(props) {
      return () => h('div', { 'data-test': 'publication-panel' }, props.changeSetPublicId as string)
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('ProductChangeSetView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('loads change set detail and renders publication panel', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        public_id: 'user-1',
        display_name: 'Owner',
        status: 'ACTIVE',
      })
      .mockResolvedValueOnce({
        public_id: 'change-set-1',
        change_type: 'NEW_PRODUCT',
        status: 'APPROVED',
        title: 'Yogurt draft',
        version_no: 1,
        product_public_id: 'prod-1',
        change_scope: {},
        attribute_groups: [],
      })
      .mockResolvedValueOnce({
        change_set_public_id: 'change-set-1',
        changed_fields: [],
      })
      .mockResolvedValueOnce({
        can_publish: true,
        blocks: [],
      })

    const wrapper = mount(ProductChangeSetView, { global: { stubs } })
    await flush()
    expect(wrapper.get('[data-test="change-set-title"]').text()).toBe('Yogurt draft')
    expect(wrapper.get('[data-test="attribute-editor"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="change-set-diff"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="scope-sku-barcode"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="reassign-confirmer-id"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="publication-panel"]').text()).toBe('change-set-1')
  })
})
