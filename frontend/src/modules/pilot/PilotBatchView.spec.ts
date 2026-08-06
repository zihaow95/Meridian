import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import PilotBatchView from '@/modules/pilot/PilotBatchView.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    setup(_, { slots, attrs }) {
      return () => h('button', attrs, slots.default?.())
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
}

describe('PilotBatchView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('labels the surface as non-production internal acceptance', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ items: [] })
    const wrapper = mount(PilotBatchView, { global: { stubs } })
    await flushPromises()
    expect(wrapper.get('[data-test="pilot-batch-view"]').text()).toContain('非生产')
    expect(wrapper.text()).toContain('内部验收')
  })
})
