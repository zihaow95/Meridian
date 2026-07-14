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
  'el-select': defineComponent({
    name: 'ElSelectStub',
    props: ['modelValue'],
    setup(props, { attrs, slots }) {
      return () => h('select', { ...attrs, value: props.modelValue as string }, slots.default?.())
    },
  }),
  'el-option': defineComponent({
    name: 'ElOptionStub',
    props: ['label', 'value'],
    setup(props) {
      return () => h('option', { value: props.value as string }, props.label as string)
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
        can_reassign_confirmer: true,
      })
      .mockResolvedValueOnce({
        change_set_public_id: 'change-set-1',
        changed_fields: [],
      })
      .mockResolvedValueOnce({
        items: [{ public_id: 'user-1', display_name: 'Owner' }],
        page: 1,
        page_size: 50,
        count: 1,
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
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith(
      '/api/v1/product-change-sets/change-set-1/confirmer-candidates?page=1&page_size=50',
    )
  })

  it('skips confirmer candidates when reassign is not allowed', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        public_id: 'approver-1',
        display_name: 'Approver',
        status: 'ACTIVE',
      })
      .mockResolvedValueOnce({
        public_id: 'change-set-1',
        change_type: 'NEW_PRODUCT',
        status: 'IN_CONFIRMATION',
        title: 'Yogurt draft',
        version_no: 1,
        product_public_id: 'prod-1',
        change_scope: {},
        attribute_groups: [],
        can_reassign_confirmer: false,
      })
      .mockResolvedValueOnce({
        change_set_public_id: 'change-set-1',
        changed_fields: [],
      })
      .mockResolvedValueOnce({
        can_publish: false,
        blocks: [],
      })

    const wrapper = mount(ProductChangeSetView, { global: { stubs } })
    await flush()
    expect(wrapper.find('[data-test="reassign-confirmer-id"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="reassign-confirmer"]').exists()).toBe(false)
    expect(
      vi.mocked(apiFetch).mock.calls.some(([url]) => String(url).includes('confirmer-candidates')),
    ).toBe(false)
  })
})
