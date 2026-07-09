import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { publicId: 'opp-1' } }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import OpportunityWorkbenchView from '@/modules/opportunities/OpportunityWorkbenchView.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['disabled', 'loading', 'type'],
    setup(props, { slots, attrs }) {
      return () =>
        h('button', { ...attrs, disabled: props.disabled ? true : undefined }, slots.default?.())
    },
  }),
  'el-card': defineComponent({
    name: 'ElCardStub',
    setup(_, { slots }) {
      return () => h('div', { class: 'card' }, slots.default?.())
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
    setup(props, { slots }) {
      return () => h('div', { class: 'table' }, slots.default?.())
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup() {
      return () => h('div')
    },
  }),
  ProposalQuotaPanel: defineComponent({
    name: 'ProposalQuotaPanelStub',
    setup() {
      return () => h('div')
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('OpportunityWorkbenchView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('renders proposal status from loaded detail', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        public_id: 'opp-1',
        business_no: 'OPP-1',
        title: 'Greek Yogurt',
        public_summary: 'summary',
        initial_type: 'NEW',
        proposal_status: 'DRAFT',
        version_no: 1,
        updated_at: '2026-07-09T00:00:00Z',
        quota_owner_type: 'USER',
        current_version: null,
      })
      .mockResolvedValueOnce([])

    const wrapper = mount(OpportunityWorkbenchView, { global: { stubs } })
    await flush()
    expect(wrapper.get('[data-test="proposal-status"]').text()).toBe('DRAFT')
    expect(wrapper.get('[data-test="submit-proposal"]').exists()).toBe(true)
  })

  it('hides submit action when proposal is already submitted', async () => {
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        public_id: 'opp-1',
        business_no: 'OPP-1',
        title: 'Greek Yogurt',
        public_summary: 'summary',
        initial_type: 'NEW',
        proposal_status: 'SUBMITTED',
        version_no: 2,
        updated_at: '2026-07-09T00:00:00Z',
        quota_owner_type: 'USER',
        current_version: null,
      })
      .mockResolvedValueOnce([])

    const wrapper = mount(OpportunityWorkbenchView, { global: { stubs } })
    await flush()
    expect(wrapper.find('[data-test="submit-proposal"]').exists()).toBe(false)
  })

  it('shows an error message with trace id on load failure', async () => {
    const { ApiError } = await import('@/api/client')
    vi.mocked(apiFetch).mockRejectedValueOnce(
      new ApiError(404, {
        code: 'RESOURCE_NOT_FOUND',
        message: 'nope',
        details: {},
        trace_id: 'trace-opp',
      }),
    )

    const wrapper = mount(OpportunityWorkbenchView, { global: { stubs } })
    await flush()
    expect(wrapper.find('.alert').text()).toContain('RESOURCE_NOT_FOUND')
    expect(wrapper.find('.alert').text()).toContain('trace-opp')
  })
})
