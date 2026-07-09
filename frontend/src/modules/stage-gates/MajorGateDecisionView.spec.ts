import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { publicId: 'gate-1' } }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}))

import MajorGateDecisionView from '@/modules/stage-gates/MajorGateDecisionView.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    setup(_, { slots, attrs }) {
      return () => h('button', attrs, slots.default?.())
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
  'el-select': defineComponent({
    name: 'ElSelectStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit, attrs }) {
      return () =>
        h(
          'select',
          {
            ...attrs,
            value: props.modelValue as string,
            onChange: (event: Event) =>
              emit('update:modelValue', (event.target as HTMLSelectElement).value),
          },
          [
            h('option', { value: 'APPROVED' }, '通过'),
            h('option', { value: 'NEEDS_INFO' }, '待补充'),
            h('option', { value: 'PASSED' }, 'Pass'),
          ],
        )
    },
  }),
  'el-option': defineComponent({
    name: 'ElOptionStub',
    setup() {
      return () => h('option')
    },
  }),
  'el-input': defineComponent({
    name: 'ElInputStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit, attrs }) {
      return () =>
        h('textarea', {
          ...attrs,
          value: props.modelValue as string,
          onInput: (event: Event) =>
            emit('update:modelValue', (event.target as HTMLTextAreaElement).value),
        })
    },
  }),
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title', 'description'],
    setup(props, { attrs }) {
      return () =>
        h('div', { ...attrs, class: 'alert' }, [props.title as string, props.description as string])
    },
  }),
  'el-card': defineComponent({
    name: 'ElCardStub',
    setup(_, { slots, attrs }) {
      return () => h('div', { ...attrs, class: 'card' }, slots.default?.())
    },
  }),
}

describe('MajorGateDecisionView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows difference alert when management and final decisions differ', async () => {
    const wrapper = mount(MajorGateDecisionView, { global: { stubs } })
    await wrapper.get('[data-test="final-decision"]').setValue('NEEDS_INFO')
    expect(wrapper.find('[data-test="conclusion-difference"]').exists()).toBe(true)
  })

  it('previews flow state from the final decision only', async () => {
    const wrapper = mount(MajorGateDecisionView, { global: { stubs } })
    await wrapper.get('[data-test="final-decision"]').setValue('PASSED')
    expect(wrapper.get('[data-test="decision-preview"]').text()).toContain('Pass')
  })
})
