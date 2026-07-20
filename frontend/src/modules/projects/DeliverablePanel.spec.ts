import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
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
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: {
      title: { type: String, default: '' },
    },
    setup(props) {
      return () => h('div', { 'data-test': 'action-message' }, props.title)
    },
  }),
  'el-input': true,
  'el-table': true,
  'el-table-column': true,
  'el-button': defineComponent({
    name: 'ElButtonStub',
    inheritAttrs: false,
    setup(_, { attrs, slots }) {
      return () => h('button', attrs, slots.default?.())
    },
  }),
}

describe('DeliverablePanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  function seedStore(canDownload: boolean): void {
    const store = useProjectStore()
    store.detail = {
      public_id: 'proj-1',
      can_download_documents: canDownload,
    } as never
    store.deliverables = [
      {
        public_id: 'd1',
        deliverable_code: 'D1',
        name: 'report.pdf',
        stage_code: 'D3',
        tier: 'PROJECT_CUSTOM',
        status: 'CONTROLLED',
        current_revision_public_id: 'r1',
        document_version_public_id: 'v1',
      },
    ] as never
  }

  it('hides download when the actor lacks document download permission', async () => {
    seedStore(false)
    const wrapper = mount(DeliverablePanel, {
      props: { projectPublicId: 'proj-1' },
      global: { stubs },
    })
    await flushPromises()
    expect(wrapper.find('[data-test="deliverable-downloads"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="download-deliverable"]').exists()).toBe(false)
  })

  it('shows download when permitted and still surfaces 403 from the ticket API', async () => {
    seedStore(true)
    vi.mocked(apiFetch).mockRejectedValue(
      new ApiError(403, {
        code: 'FORBIDDEN',
        message: 'denied',
        details: {},
        trace_id: 't',
      }),
    )
    const wrapper = mount(DeliverablePanel, {
      props: { projectPublicId: 'proj-1' },
      global: { stubs },
    })
    await flushPromises()
    const button = wrapper.find('[data-test="download-deliverable"]')
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('FORBIDDEN')
  })
})
