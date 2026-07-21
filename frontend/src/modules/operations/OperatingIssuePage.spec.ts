import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, ref } from 'vue'

const routeParams = ref({ publicId: 'issue-1' })

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ params: routeParams.value, query: {} }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import OperatingIssuePage from '@/modules/operations/OperatingIssuePage.vue'
import { useOperationsStore } from '@/modules/operations/store'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['loading', 'disabled'],
    setup(props, { slots, attrs }) {
      return () =>
        h(
          'button',
          { ...attrs, disabled: props.loading || props.disabled ? true : undefined },
          slots.default?.(),
        )
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

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

const issueBrief = {
  public_id: 'issue-1',
  business_no: 'ISS-001',
  title: 'Margin drop',
  status: 'OPEN',
  version_no: 1,
  product_public_id: 'prod-1',
  phenomenon_summary: 'Sales fell',
}

describe('OperatingIssuePage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    routeParams.value = { publicId: 'issue-1' }
  })

  it('records a decision and converts to iteration without auto-submit', async () => {
    vi.mocked(apiFetch).mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.startsWith('/api/v1/operating-issues') && !url.includes('/decisions') && !url.includes('/iteration')) {
        if (init?.method === 'POST' && url.endsWith('/iteration-proposal')) {
          return {
            ...issueBrief,
            status: 'CONVERTED_TO_PROPOSAL',
            linked_opportunity_id: 'opp-draft-1',
          }
        }
        return { items: [issueBrief] }
      }
      if (url === '/api/v1/operating-issues/issue-1/decisions' && init?.method === 'POST') {
        return {
          public_id: 'dec-1',
          recommendation_type: 'ITERATE',
          action_summary: 'Open iteration draft',
          issue: {
            ...issueBrief,
            version_no: 2,
            data_snapshot_public_id: 'snap-1',
            signals: [{ signal_public_id: 'sig-1', is_primary: true }],
            decisions: [
              {
                public_id: 'dec-1',
                recommendation_type: 'ITERATE',
                action_summary: 'Open iteration draft',
                decided_at: '2026-07-21T00:00:00Z',
              },
            ],
          },
        }
      }
      if (
        url === '/api/v1/operating-issues/issue-1/iteration-proposal' &&
        init?.method === 'POST'
      ) {
        return {
          ...issueBrief,
          status: 'CONVERTED_TO_PROPOSAL',
          version_no: 2,
          linked_opportunity_id: 'opp-draft-1',
        }
      }
      throw new Error(`unexpected ${url}`)
    })

    const wrapper = mount(OperatingIssuePage, { global: { stubs } })
    await flush()
    expect(wrapper.text()).toContain('Margin drop')

    await wrapper.get('[data-test="recommendation-type"]').setValue('ITERATE')
    await wrapper.get('[data-test="action-summary"]').setValue('Open iteration draft')
    await wrapper.get('[data-test="record-decision"]').trigger('click')
    await flush()
    expect(wrapper.text()).toContain('snap-1')
    expect(wrapper.text()).toContain('sig-1')

    await wrapper.get('[data-test="proposal-owner"]').setValue('user-1')
    await wrapper.get('[data-test="idempotency-key"]').setValue('iter-1')
    await wrapper.get('[data-test="convert-iteration"]').trigger('click')
    await flush()

    const store = useOperationsStore()
    expect(store.currentIssue?.status).toBe('CONVERTED_TO_PROPOSAL')
    expect(wrapper.text()).toContain('opp-draft-1')
    expect(wrapper.text()).not.toContain('已自动提交')
    const convertCall = vi
      .mocked(apiFetch)
      .mock.calls.find((call) => String(call[0]).includes('/iteration-proposal'))
    expect(convertCall?.[1]).toMatchObject({ method: 'POST' })
  })
})
