import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { publicId: 'prod-1' } }),
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { ApiError, apiFetch } from '@/api/client'
import ProductDetailView from '@/modules/products/ProductDetailView.vue'

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
  'el-card': defineComponent({
    name: 'ElCardStub',
    setup(_, { slots }) {
      return () => h('div', [slots.header?.(), slots.default?.()])
    },
  }),
}

const PRODUCT_DETAIL = {
  public_id: 'prod-1',
  business_no: 'PRD-0001',
  name: 'Legacy yogurt',
  category_code: 'YOGURT',
  lifecycle_status: 'ACTIVE',
  versions: [],
  external_bindings: [],
}

const MATERIAL_GROUPS = {
  items: [
    {
      material_type_code: 'PRODUCTION_LICENSE',
      current: {
        public_id: 'mat-2',
        material_type_code: 'PRODUCTION_LICENSE',
        version_no: 2,
        material_status: 'CONFIRMED',
        is_current: true,
        document_version_public_id: 'dv-2',
        original_filename: 'license-v2.pdf',
        confirmation: {
          public_id: 'conf-2',
          decision: 'APPROVED',
          confirmer_public_id: 'user-9',
          content_hash: 'hash-2',
          requested_at: '2026-07-20T02:00:00Z',
          decided_at: '2026-07-21T02:00:00Z',
        },
      },
      history: [
        {
          public_id: 'mat-1',
          material_type_code: 'PRODUCTION_LICENSE',
          version_no: 1,
          material_status: 'SUPERSEDED',
          is_current: false,
          document_version_public_id: 'dv-1',
          original_filename: 'license-v1.pdf',
          confirmation: null,
        },
      ],
    },
  ],
}

const COMPLETENESS = {
  requirement_version_public_id: 'req-1',
  requirement_version_number: 3,
  requirement_content_digest: 'digest-3',
  is_complete: false,
  blocking_material_type_codes: ['NUTRITION_REPORT'],
  items: [
    { material_type_code: 'PRODUCTION_LICENSE', requirement: 'REQUIRED', state: 'SATISFIED' },
    { material_type_code: 'NUTRITION_REPORT', requirement: 'REQUIRED', state: 'MISSING' },
  ],
}

const TRIAGE_QUEUE = {
  items: [
    {
      public_id: 'sub-1',
      document_version_public_id: 'dv-3',
      processing_status: 'PENDING_TRIAGE',
      source_note: 'Found in the shared drive',
      original_file_date: '2024-03-01',
      claimed_version: 'v1',
      claimed_effective_from: '2024-03-05',
      sha256: 'abc',
      submitted_by_public_id: 'user-1',
      verified_by_public_id: null,
      verification_note: '',
    },
  ],
}

function refusal(): ApiError {
  return new ApiError(404, {
    code: 'RESOURCE_NOT_FOUND',
    message: 'Resource not found',
    details: {},
    trace_id: 'trace-1',
  })
}

function respondWith(overrides: Record<string, unknown | ApiError> = {}): void {
  vi.mocked(apiFetch).mockImplementation(async (input: string) => {
    const route = input.includes('/material-completeness')
      ? 'completeness'
      : input.includes('/legacy-materials')
        ? 'triage'
        : input.includes('/materials')
          ? 'materials'
          : 'detail'
    const defaults: Record<string, unknown> = {
      detail: PRODUCT_DETAIL,
      materials: MATERIAL_GROUPS,
      completeness: COMPLETENESS,
      triage: TRIAGE_QUEUE,
    }
    const answer = route in overrides ? overrides[route] : defaults[route]
    if (answer instanceof ApiError) throw answer
    return answer
  })
}

function mountDetail() {
  return mount(ProductDetailView, {
    global: { stubs, directives: { loading: () => {} } },
  })
}

describe('ProductDetailView material panel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('shows completeness, the current material and its superseded history', async () => {
    respondWith()
    const wrapper = mountDetail()
    await flushPromises()

    const panel = wrapper.get('[data-test="material-panel"]')
    expect(panel.text()).toContain('PRODUCTION_LICENSE')
    expect(wrapper.get('[data-test="material-current"]').text()).toContain('license-v2.pdf')
    expect(wrapper.get('[data-test="material-current"]').text()).toContain('APPROVED')
    expect(wrapper.get('[data-test="material-history-row"]').text()).toContain('license-v1.pdf')
    expect(wrapper.get('[data-test="material-completeness"]').text()).toContain('NUTRITION_REPORT')
    expect(wrapper.get('[data-test="material-completeness"]').text()).toContain('MISSING')
  })

  it('hides the whole panel when the material read action is refused', async () => {
    respondWith({ materials: refusal(), completeness: refusal(), triage: refusal() })
    const wrapper = mountDetail()
    await flushPromises()

    expect(wrapper.find('[data-test="material-panel"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('license-v2.pdf')
    expect(wrapper.text()).not.toContain('PRODUCTION_LICENSE')
  })

  it('lists the pending triage submissions with their confirmation state', async () => {
    respondWith()
    const wrapper = mountDetail()
    await flushPromises()

    const queue = wrapper.get('[data-test="material-triage-row"]')
    expect(queue.text()).toContain('PENDING_TRIAGE')
    expect(queue.text()).toContain('Found in the shared drive')
  })

  it('keeps the material list readable when no requirements are published yet', async () => {
    respondWith({
      completeness: new ApiError(400, {
        code: 'VALIDATION_FAILED',
        message: 'No published product material requirements.',
        details: {},
        trace_id: 'trace-2',
      }),
    })
    const wrapper = mountDetail()
    await flushPromises()

    expect(wrapper.get('[data-test="material-current"]').text()).toContain('license-v2.pdf')
    expect(wrapper.find('[data-test="material-completeness"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="material-completeness-note"]').text()).toContain('材料要求')
  })
})
