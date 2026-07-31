import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, ref } from 'vue'

const routeParams = ref({ publicId: 'plan-1' })

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useRoute: () => ({ params: routeParams.value, query: {} }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import RetirementPlanPage from '@/modules/operations/RetirementPlanPage.vue'
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
    props: ['title', 'type'],
    setup(props) {
      return () =>
        h('div', { class: 'alert', 'data-type': props.type as string }, props.title as string)
    },
  }),
  'el-card': defineComponent({
    name: 'ElCardStub',
    setup(_, { slots }) {
      return () => h('section', [slots.header?.(), slots.default?.()])
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

const plan = {
  public_id: 'plan-1',
  status: 'DRAFT',
  product_public_id: 'prod-1',
  issue_public_id: 'issue-1',
  stage_gate_public_id: 'gate-1',
  content_hash: 'hash-1',
}

describe('RetirementPlanPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    routeParams.value = { publicId: 'plan-1' }
  })

  it('shows validate blocks, dual-step decision UI, and execute status', async () => {
    const store = useOperationsStore()
    store.retirementPlan = { ...plan }

    vi.mocked(apiFetch).mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/retirement-plans/plan-1/validate' && init?.method === 'POST') {
        return { ok: false, missing: ['inventory_plan', 'operating_snapshot'] }
      }
      if (url === '/api/v1/retirement-plans/plan-1/submit' && init?.method === 'POST') {
        return { public_id: 'plan-1', submission_number: 1, content_hash: 'hash-1' }
      }
      if (
        url === '/api/v1/stage-gates/gate-1/retirement-management-conclusion' &&
        init?.method === 'POST'
      ) {
        return { public_id: 'dec-mgmt', result: 'APPROVED' }
      }
      if (
        url === '/api/v1/stage-gates/gate-1/retirement-final-decision' &&
        init?.method === 'POST'
      ) {
        return { public_id: 'dec-final', result: 'APPROVED' }
      }
      if (url === '/api/v1/retirement-plans/plan-1/execute' && init?.method === 'POST') {
        return { ...plan, status: 'EXECUTED' }
      }
      throw new Error(`unexpected ${url}`)
    })

    const wrapper = mount(RetirementPlanPage, { global: { stubs } })
    await flush()

    expect(wrapper.text()).toContain('经管会')
    expect(wrapper.text()).toContain('老板')

    await wrapper.get('[data-test="validate-plan"]').trigger('click')
    await flush()
    expect(wrapper.text()).toContain('inventory_plan')
    expect(wrapper.text()).toContain('operating_snapshot')

    await wrapper.get('[data-test="submit-plan"]').trigger('click')
    await flush()

    await wrapper.get('[data-test="management-conclusion"]').setValue('APPROVE')
    await wrapper.get('[data-test="management-idempotency"]').setValue('mgmt-1')
    await wrapper.get('[data-test="record-management"]').trigger('click')
    await flush()

    await wrapper.get('[data-test="final-decision"]').setValue('APPROVE')
    await wrapper.get('[data-test="final-idempotency"]').setValue('boss-1')
    await wrapper.get('[data-test="record-final"]').trigger('click')
    await flush()

    await wrapper.get('[data-test="execute-as-of"]').setValue('2026-07-21')
    await wrapper.get('[data-test="execute-plan"]').trigger('click')
    await flush()
    expect(useOperationsStore().retirementPlan?.status).toBe('EXECUTED')
    expect(wrapper.text()).toContain('EXECUTED')
  })
})
