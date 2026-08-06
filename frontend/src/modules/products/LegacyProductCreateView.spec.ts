import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push, back: vi.fn() }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { ApiError, apiFetch } from '@/api/client'
import LegacyProductCreateView from '@/modules/products/LegacyProductCreateView.vue'

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
  'el-select': defineComponent({
    name: 'ElSelectStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit, attrs, slots }) {
      return () =>
        h(
          'select',
          {
            ...attrs,
            value: props.modelValue as string,
            onChange: (event: Event) =>
              emit('update:modelValue', (event.target as HTMLSelectElement).value),
          },
          slots.default?.(),
        )
    },
  }),
  'el-option': defineComponent({
    name: 'ElOptionStub',
    props: ['label', 'value'],
    setup(props) {
      return () => h('option', { value: props.value as string }, props.label as string)
    },
  }),
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert' }, props.title as string)
    },
  }),
  'el-card': defineComponent({
    name: 'ElCardStub',
    setup(_, { slots }) {
      return () => h('div', [slots.header?.(), slots.default?.()])
    },
  }),
}

type BaselineRequestBody = {
  payload: Record<string, unknown>
  idempotency_key: string
  decision?: string
  target_product_public_id?: string
}

type BaselineCall = [string, { method: string; json: BaselineRequestBody }]

function baselineCalls(): BaselineCall[] {
  return vi.mocked(apiFetch).mock.calls as unknown as BaselineCall[]
}

function duplicateRefusal(): ApiError {
  return new ApiError(400, {
    code: 'VALIDATION_FAILED',
    message: 'This product looks like one that already exists.',
    details: {
      reason: 'DUPLICATE_REQUIRES_DECISION',
      duplicate_candidates: [
        {
          product_public_id: 'prod-existing',
          business_no: 'PRD-0001',
          name: 'Legacy yogurt',
          blocking: true,
        },
      ],
    },
    trace_id: 'trace-1',
  })
}

async function fillMinimumBaseline(
  wrapper: ReturnType<typeof mount>,
  overrides: Record<string, string> = {},
): Promise<void> {
  const values: Record<string, string> = {
    'legacy-name': 'Legacy yogurt',
    'legacy-business-no': 'PRD-0001',
    'legacy-category-code': 'YOGURT',
    'legacy-sku-code': 'SKU-0001',
    'legacy-channel-code': 'DEFAULT',
    ...overrides,
  }
  for (const [field, value] of Object.entries(values)) {
    await wrapper.get(`[data-test="${field}"]`).setValue(value)
  }
}

describe('LegacyProductCreateView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    push.mockReset()
  })

  it('keeps submit disabled until the core fields, one SKU and one channel are present', async () => {
    const wrapper = mount(LegacyProductCreateView, { global: { stubs } })
    expect(wrapper.get('[data-test="submit-legacy-baseline"]').attributes('disabled')).toBeDefined()

    await fillMinimumBaseline(wrapper, { 'legacy-channel-code': '' })
    expect(wrapper.get('[data-test="submit-legacy-baseline"]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-test="legacy-channel-code"]').setValue('DEFAULT')
    expect(
      wrapper.get('[data-test="submit-legacy-baseline"]').attributes('disabled'),
    ).toBeUndefined()
  })

  it('sends the form fields to the shared legacy baseline endpoint with an idempotency key', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      change_set_public_id: 'cs-1',
      product_public_id: 'prod-1',
      created: true,
      duplicate_candidates: [],
    })

    const wrapper = mount(LegacyProductCreateView, { global: { stubs } })
    await fillMinimumBaseline(wrapper)
    await wrapper.get('[data-test="legacy-specification"]').setValue('120g')
    await wrapper.get('[data-test="submit-legacy-baseline"]').trigger('click')
    await flushPromises()

    expect(apiFetch).toHaveBeenCalledTimes(1)
    const [url, init] = baselineCalls()[0]
    expect(url).toBe('/api/v1/legacy-baselines')
    expect(init.method).toBe('POST')
    expect(init.json.payload).toMatchObject({
      name: 'Legacy yogurt',
      business_no: 'PRD-0001',
      category_code: 'YOGURT',
      sku_code: 'SKU-0001',
      specification: '120g',
      channel_code: 'DEFAULT',
    })
    expect(init.json.idempotency_key).toBeTruthy()
    expect(init.json.decision).toBeUndefined()
  })

  it('shows the duplicate candidates and creates nothing until the user decides', async () => {
    vi.mocked(apiFetch).mockRejectedValue(duplicateRefusal())

    const wrapper = mount(LegacyProductCreateView, { global: { stubs } })
    await fillMinimumBaseline(wrapper)
    await wrapper.get('[data-test="submit-legacy-baseline"]').trigger('click')
    await flushPromises()

    expect(apiFetch).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-test="duplicate-candidates"]').text()).toContain('PRD-0001')
    expect(wrapper.get('[data-test="create-anyway"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="link-existing"]').exists()).toBe(true)
    expect(push).not.toHaveBeenCalled()
  })

  it('repeats the submission with an explicit create decision and the same idempotency key', async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(duplicateRefusal()).mockResolvedValueOnce({
      change_set_public_id: 'cs-1',
      product_public_id: 'prod-1',
      created: true,
      duplicate_candidates: [],
    })

    const wrapper = mount(LegacyProductCreateView, { global: { stubs } })
    await fillMinimumBaseline(wrapper)
    await wrapper.get('[data-test="submit-legacy-baseline"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="create-anyway"]').trigger('click')
    await flushPromises()

    const calls = baselineCalls()
    expect(calls).toHaveLength(2)
    expect(calls[1][1].json.decision).toBe('CREATE')
    expect(calls[1][1].json.idempotency_key).toBe(calls[0][1].json.idempotency_key)
    expect(push).toHaveBeenCalledWith('/products/prod-1')
  })

  it('links to the candidate the user picked instead of merging anything automatically', async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(duplicateRefusal()).mockResolvedValueOnce({
      change_set_public_id: 'cs-2',
      product_public_id: 'prod-existing',
      created: true,
      duplicate_candidates: [],
    })

    const wrapper = mount(LegacyProductCreateView, { global: { stubs } })
    await fillMinimumBaseline(wrapper)
    await wrapper.get('[data-test="submit-legacy-baseline"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="link-target"]').setValue('prod-existing')
    await wrapper.get('[data-test="link-existing"]').trigger('click')
    await flushPromises()

    const calls = baselineCalls()
    expect(calls[1][1].json.decision).toBe('LINK')
    expect(calls[1][1].json.target_product_public_id).toBe('prod-existing')
  })

  it('refuses to link before a target product is chosen', async () => {
    vi.mocked(apiFetch).mockRejectedValueOnce(duplicateRefusal())

    const wrapper = mount(LegacyProductCreateView, { global: { stubs } })
    await fillMinimumBaseline(wrapper)
    await wrapper.get('[data-test="submit-legacy-baseline"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="link-existing"]').trigger('click')
    await flushPromises()

    expect(apiFetch).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-test="legacy-baseline-error"]').text()).toContain('关联')
  })

  it('says the draft already existed when the server answers a replay', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      change_set_public_id: 'cs-1',
      product_public_id: 'prod-1',
      created: false,
      duplicate_candidates: [],
    })

    const wrapper = mount(LegacyProductCreateView, { global: { stubs } })
    await fillMinimumBaseline(wrapper)
    await wrapper.get('[data-test="submit-legacy-baseline"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="legacy-baseline-status"]').text()).toContain('已存在')
  })
})
