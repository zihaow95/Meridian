import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}))

import OpportunityCreateView from '@/modules/opportunities/OpportunityCreateView.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['disabled', 'loading', 'type'],
    setup(props, { slots, attrs }) {
      return () =>
        h('button', { ...attrs, disabled: props.disabled ? true : undefined }, slots.default?.())
    },
  }),
  'el-form': defineComponent({
    name: 'ElFormStub',
    setup(_, { slots }) {
      return () => h('form', slots.default?.())
    },
  }),
  'el-form-item': defineComponent({
    name: 'ElFormItemStub',
    setup(_, { slots }) {
      return () => h('div', slots.default?.())
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
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert' }, props.title as string)
    },
  }),
  ProposalQuotaPanel: defineComponent({
    name: 'ProposalQuotaPanelStub',
    setup() {
      return () => h('div')
    },
  }),
}

describe('OpportunityCreateView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('blocks submit button until the four required proposal fields are present', async () => {
    const wrapper = mount(OpportunityCreateView, { global: { stubs } })
    expect(wrapper.get('[data-test="submit-proposal"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="title"]').setValue('Greek Yogurt Cup')
    await wrapper.get('[data-test="market-analysis"]').setValue('Channel demand exists')
    await wrapper.get('[data-test="core-selling-points"]').setValue('High protein')
    await wrapper.get('[data-test="target-users-needs"]').setValue('Breakfast replacement')
    await wrapper.get('[data-test="suggested-retail-price"]').setValue('9.90')
    await wrapper.get('[data-test="public-summary"]').setValue('High protein yogurt')
    expect(wrapper.get('[data-test="submit-proposal"]').attributes('disabled')).toBeUndefined()
  })
})
