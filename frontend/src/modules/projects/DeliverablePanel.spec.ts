import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch, ApiError } from '@/api/client'
import DeliverablePanel from '@/modules/projects/DeliverablePanel.vue'
import { useProjectStore } from '@/modules/projects/store'

const stubs = {
  'el-table': defineComponent({
    name: 'ElTableStub',
    props: ['data'],
    setup(props) {
      return () => {
        const rows = (props.data as Array<{ name: string; deliverable_code: string }>) ?? []
        return h(
          'div',
          { class: 'table' },
          rows.map((row) =>
            h('div', { 'data-test': 'deliverable-row' }, `${row.deliverable_code} ${row.name}`),
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
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert' }, props.title as string)
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
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('DeliverablePanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('renders deliverables from the store', async () => {
    const store = useProjectStore()
    store.deliverables = [
      {
        public_id: 'del-1',
        deliverable_code: 'D-001',
        name: 'Formula draft',
        stage_code: 'D3',
        tier: 'CORE',
        status: 'DRAFT',
        current_revision_public_id: 'rev-1',
      },
    ]

    const wrapper = mount(DeliverablePanel, {
      props: { projectPublicId: 'proj-1' },
      global: { stubs },
    })
    await flush()

    expect(wrapper.text()).toContain('D-001')
    expect(wrapper.text()).toContain('Formula draft')
  })

  it('submits revision for professional confirmation', async () => {
    const store = useProjectStore()
    store.deliverables = [
      {
        public_id: 'del-1',
        deliverable_code: 'D-001',
        name: 'Formula draft',
        stage_code: 'D3',
        tier: 'CORE',
        status: 'DRAFT',
        current_revision_public_id: 'rev-1',
      },
    ]

    vi.mocked(apiFetch).mockResolvedValue({
      public_id: 'rev-1',
      status: 'PENDING_CONFIRMATION',
      content_hash: 'hash-1',
    })

    const wrapper = mount(DeliverablePanel, {
      props: { projectPublicId: 'proj-1' },
      global: { stubs },
    })
    await flush()

    await wrapper.get('[data-test="submit-revision"]').trigger('click')
    await flush()

    expect(apiFetch).toHaveBeenCalledWith('/api/v1/deliverable-revisions/rev-1/submit', {
      method: 'POST',
      json: { confirmer_public_id: expect.any(String) },
    })
    expect(wrapper.text()).toContain('PENDING_CONFIRMATION')
  })

  it('shows revision conflict when confirmation is invalidated by a newer revision', async () => {
    const store = useProjectStore()
    store.deliverables = [
      {
        public_id: 'del-1',
        deliverable_code: 'D-001',
        name: 'Formula draft',
        stage_code: 'D3',
        tier: 'CORE',
        status: 'DRAFT',
        current_revision_public_id: 'rev-2',
      },
    ]

    vi.mocked(apiFetch).mockRejectedValue(
      new ApiError(409, {
        code: 'DELIVERABLE_REVISION_CONFLICT',
        message: 'The deliverable revision conflicted with another operation.',
        details: {},
        trace_id: 'trace-rev-conflict',
      }),
    )

    const wrapper = mount(DeliverablePanel, {
      props: { projectPublicId: 'proj-1' },
      global: { stubs },
    })
    await flush()

    await wrapper.get('[data-test="decide-confirmation"]').trigger('click')
    await flush()

    expect(wrapper.find('.alert').text()).toContain('DELIVERABLE_REVISION_CONFLICT')
  })
})
