import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import StageGatePanel from '@/modules/projects/StageGatePanel.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['disabled', 'loading'],
    setup(props, { slots, attrs }) {
      return () =>
        h(
          'button',
          { ...attrs, disabled: props.disabled || props.loading ? true : undefined },
          slots.default?.(),
        )
    },
  }),
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title', 'type'],
    setup(props) {
      return () =>
        h('div', { class: 'alert', 'data-type': props.type as string }, props.title as string)
    },
  }),
  'el-select': defineComponent({
    name: 'ElSelectStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit }) {
      return () =>
        h('select', {
          value: props.modelValue as string,
          onChange: (event: Event) =>
            emit('update:modelValue', (event.target as HTMLSelectElement).value),
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
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('StageGatePanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('lists validation blockers and disables submit until cleared', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      blocks: [{ code: 'TASK_INCOMPLETE', message: 'Core task not complete.' }],
      warnings: [],
    })

    const wrapper = mount(StageGatePanel, {
      props: { stageGatePublicId: 'gate-1', launchMode: false },
      global: { stubs },
    })
    await flush()

    await wrapper.get('[data-test="validate-gate"]').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('TASK_INCOMPLETE')
    expect(wrapper.get('[data-test="submit-gate"]').attributes('disabled')).toBeDefined()
  })

  it('prevents double submit while request is in flight', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({ blocks: [], warnings: [] })
      .mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(
              () => resolve({ public_id: 'sub-1', submission_number: 1, content_hash: 'h' }),
              50,
            ),
          ),
      )

    const wrapper = mount(StageGatePanel, {
      props: { stageGatePublicId: 'gate-1', launchMode: false },
      global: { stubs },
    })
    await flush()

    await wrapper.get('[data-test="validate-gate"]').trigger('click')
    await flush()

    const submit = wrapper.get('[data-test="submit-gate"]')
    await submit.trigger('click')
    expect(submit.attributes('disabled')).toBeDefined()
    await submit.trigger('click')
    expect(
      vi.mocked(apiFetch).mock.calls.filter((call) => String(call[0]).includes('/submissions'))
        .length,
    ).toBe(1)
  })

  it('shows publish pending repair state after first launch handover error', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        decision_public_id: 'dec-1',
        management_conclusion: 'APPROVED',
      })
      .mockResolvedValueOnce({
        decision_public_id: 'dec-1',
        final_decision: 'APPROVED',
        handover_error: 'PRODUCT_PUBLICATION_FAILED',
        project_status: 'PUBLISH_PENDING_REPAIR',
      })

    const wrapper = mount(StageGatePanel, {
      props: { stageGatePublicId: 'gate-l2', launchMode: true },
      global: { stubs },
    })
    await flush()

    await wrapper.get('[data-test="record-management-conclusion"]').trigger('click')
    await flush()
    await wrapper.get('[data-test="record-final-decision"]').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('PUBLISH_PENDING_REPAIR')
    expect(wrapper.text()).toContain('PRODUCT_PUBLICATION_FAILED')
  })

  it('hides the final decision action when the actor may only record the conclusion', async () => {
    const wrapper = mount(StageGatePanel, {
      props: {
        stageGatePublicId: 'gate-l2',
        launchMode: true,
        canManagement: true,
        canFinal: false,
      },
      global: { stubs },
    })
    await flush()

    expect(wrapper.find('[data-test="record-management-conclusion"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="record-final-decision"]').exists()).toBe(false)
  })

  it('hides the conclusion action when the actor may only record the final decision', async () => {
    const wrapper = mount(StageGatePanel, {
      props: {
        stageGatePublicId: 'gate-l2',
        launchMode: true,
        canManagement: false,
        canFinal: true,
      },
      global: { stubs },
    })
    await flush()

    expect(wrapper.find('[data-test="record-management-conclusion"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="record-final-decision"]').exists()).toBe(true)
  })

  it('shows a no-permission notice when the actor holds neither launch decision right', async () => {
    const wrapper = mount(StageGatePanel, {
      props: {
        stageGatePublicId: 'gate-l2',
        launchMode: true,
        canManagement: false,
        canFinal: false,
      },
      global: { stubs },
    })
    await flush()

    expect(wrapper.find('[data-test="launch-no-permission"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="record-management-conclusion"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="record-final-decision"]').exists()).toBe(false)
  })
})
