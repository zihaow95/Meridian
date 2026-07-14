import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { publicId: 'change-set-1' } }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import ProductChangeSetView from '@/modules/products/ProductChangeSetView.vue'

type ConfirmerState = {
  candidates: Array<{ public_id: string; display_name: string }>
  page: number
  total: number
  error: string
  loading: boolean
}

type Exposed = {
  searchConfirmerCandidates: (query: string) => void
  loadMoreConfirmerCandidates: () => Promise<void>
  loadConfirmerCandidates: (options?: {
    reset?: boolean
    search?: string
    page?: number
  }) => Promise<void>
  getConfirmerState: () => ConfirmerState
}

const stubs = {
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert', 'data-test': 'alert' }, props.title as string)
    },
  }),
  'el-card': defineComponent({
    name: 'ElCardStub',
    setup(_props, { slots }) {
      return () => h('div', [slots.header?.(), slots.default?.()])
    },
  }),
  'el-form': defineComponent({
    name: 'ElFormStub',
    setup(_props, { slots }) {
      return () => h('form', slots.default?.())
    },
  }),
  'el-form-item': defineComponent({
    name: 'ElFormItemStub',
    setup(_props, { slots }) {
      return () => h('div', slots.default?.())
    },
  }),
  'el-input': defineComponent({
    name: 'ElInputStub',
    props: ['modelValue'],
    setup(props, { attrs }) {
      return () => h('input', { ...attrs, value: props.modelValue as string })
    },
  }),
  'el-select': true,
  'el-option': true,
  'el-button': true,
  'el-table': true,
  'el-table-column': true,
  ProductPublicationPanel: defineComponent({
    name: 'ProductPublicationPanelStub',
    props: ['changeSetPublicId'],
    setup(props) {
      return () => h('div', { 'data-test': 'publication-panel' }, props.changeSetPublicId as string)
    },
  }),
}

function mockApiByUrl(
  handlers: Array<
    | { match: (url: string) => boolean; response: unknown }
    | { match: (url: string) => boolean; error: unknown }
  >,
) {
  vi.mocked(apiFetch).mockImplementation(async (url: string) => {
    const href = String(url)
    const handler = handlers.find((row) => row.match(href))
    if (!handler) {
      throw new Error(`unexpected url: ${href}`)
    }
    if ('error' in handler) {
      throw handler.error
    }
    return handler.response as never
  })
}

function mockInitialLoad(options: { canReassign?: boolean; count?: number } = {}) {
  const canReassign = options.canReassign ?? true
  const count = options.count ?? 1
  mockApiByUrl([
    {
      match: (url) => url.includes('/api/v1/me'),
      response: { public_id: 'user-1', display_name: 'Owner', status: 'ACTIVE' },
    },
    {
      match: (url) =>
        url.includes('/api/v1/product-change-sets/change-set-1') &&
        !url.includes('/diff') &&
        !url.includes('/confirmer-candidates') &&
        !url.includes('validate'),
      response: {
        public_id: 'change-set-1',
        change_type: 'NEW_PRODUCT',
        status: 'APPROVED',
        title: 'Yogurt draft',
        version_no: 1,
        product_public_id: 'prod-1',
        change_scope: {},
        attribute_groups: [],
        can_reassign_confirmer: canReassign,
      },
    },
    {
      match: (url) => url.includes('/diff'),
      response: { change_set_public_id: 'change-set-1', changed_fields: [] },
    },
    {
      match: (url) => url.includes('/confirmer-candidates'),
      response: {
        items: [{ public_id: 'user-1', display_name: 'Owner' }],
        page: 1,
        page_size: 50,
        count,
      },
    },
    {
      match: (url) => url.includes('validate'),
      response: { can_publish: true, blocks: [] },
    },
  ])
}

function candidateCalls() {
  return vi
    .mocked(apiFetch)
    .mock.calls.map(([url]) => String(url))
    .filter((url) => url.includes('confirmer-candidates'))
}

async function mountLoadedView() {
  const wrapper = mount(ProductChangeSetView, { global: { stubs } })
  await flushPromises()
  return wrapper as VueWrapper & { vm: Exposed }
}

function exposed(wrapper: VueWrapper & { vm: Exposed }): Exposed {
  const fromExposed = (wrapper.vm as unknown as { $?: { exposed?: Exposed } }).$?.exposed
  return fromExposed ?? wrapper.vm
}

describe('ProductChangeSetView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    vi.useRealTimers()
  })

  it('loads change set detail and renders publication panel', async () => {
    mockInitialLoad()
    const wrapper = await mountLoadedView()
    expect(wrapper.get('[data-test="change-set-title"]').text()).toBe('Yogurt draft')
    expect(wrapper.get('[data-test="attribute-editor"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="change-set-diff"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="scope-sku-barcode"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="reassign-confirmer-id"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="publication-panel"]').text()).toBe('change-set-1')
    expect(candidateCalls()).toEqual([
      '/api/v1/product-change-sets/change-set-1/confirmer-candidates?page=1&page_size=50',
    ])
  })

  it('skips confirmer candidates when reassign is not allowed', async () => {
    mockInitialLoad({ canReassign: false })
    const wrapper = await mountLoadedView()
    expect(wrapper.find('[data-test="reassign-confirmer-id"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="reassign-confirmer"]').exists()).toBe(false)
    expect(candidateCalls()).toEqual([])
  })

  it('debounces confirmer remote search before requesting', async () => {
    mockInitialLoad({ count: 80 })
    const wrapper = await mountLoadedView()
    const api = exposed(wrapper)
    vi.useFakeTimers()
    mockApiByUrl([
      {
        match: (url) => url.includes('/confirmer-candidates'),
        response: { items: [], page: 1, page_size: 50, count: 0 },
      },
    ])

    api.searchConfirmerCandidates('Candidate 050')
    expect(candidateCalls()).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(299)
    expect(candidateCalls()).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()
    expect(candidateCalls().at(-1)).toContain('search=Candidate+050')
  })

  it('applies confirmer search results and reports load failures', async () => {
    mockInitialLoad({ count: 80 })
    const wrapper = await mountLoadedView()
    const api = exposed(wrapper)

    mockApiByUrl([
      {
        match: (url) => url.includes('search=Candidate'),
        response: {
          items: [{ public_id: 'user-50', display_name: 'Candidate 050' }],
          page: 1,
          page_size: 50,
          count: 1,
        },
      },
    ])
    await api.loadConfirmerCandidates({ reset: true, search: 'Candidate 050', page: 1 })
    expect(api.getConfirmerState().candidates.map((row) => row.display_name)).toEqual([
      'Candidate 050',
    ])

    mockApiByUrl([
      {
        match: (url) => url.includes('/confirmer-candidates'),
        error: { code: 'INTERNAL_ERROR', message: 'network down' },
      },
    ])
    await api.loadConfirmerCandidates({ reset: true, search: 'Candidate 050', page: 1 })
    expect(api.getConfirmerState().error).toBe('INTERNAL_ERROR: network down')
    expect(api.getConfirmerState().candidates.map((row) => row.display_name)).toEqual([
      'Candidate 050',
    ])
  })

  it('loads next confirmer page only after a successful response', async () => {
    mockInitialLoad({ count: 80 })
    const wrapper = await mountLoadedView()
    const api = exposed(wrapper)
    expect(api.getConfirmerState().page).toBe(1)
    expect(api.getConfirmerState().total).toBe(80)

    let pageTwoCalls = 0
    mockApiByUrl([
      {
        match: (url) => url.includes('page=2'),
        get response() {
          pageTwoCalls += 1
          if (pageTwoCalls === 1) {
            throw Object.assign(new Error('network down'), { code: 'INTERNAL_ERROR' })
          }
          return {
            items: [{ public_id: 'user-51', display_name: 'Candidate 051' }],
            page: 2,
            page_size: 50,
            count: 80,
          }
        },
      } as { match: (url: string) => boolean; response: unknown },
    ])

    await api.loadMoreConfirmerCandidates()
    expect(api.getConfirmerState().error).toBe('INTERNAL_ERROR: network down')
    expect(api.getConfirmerState().page).toBe(1)
    expect(candidateCalls().at(-1)).toContain('page=2')

    await api.loadMoreConfirmerCandidates()
    expect(pageTwoCalls).toBe(2)
    expect(candidateCalls().some((url) => url.includes('page=3'))).toBe(false)
    expect(api.getConfirmerState().page).toBe(2)
    expect(api.getConfirmerState().error).toBe('')
    expect(api.getConfirmerState().candidates.map((row) => row.display_name)).toEqual([
      'Owner',
      'Candidate 051',
    ])
  })

  it('keeps newer confirmer search results when an older request finishes later', async () => {
    mockInitialLoad({ count: 80 })
    const wrapper = await mountLoadedView()
    const api = exposed(wrapper)

    let releaseOld: (() => void) | undefined
    const oldGate = new Promise<void>((resolve) => {
      releaseOld = resolve
    })
    vi.mocked(apiFetch).mockImplementation(async (url: string) => {
      const href = String(url)
      if (href.includes('search=old')) {
        await oldGate
        return {
          items: [{ public_id: 'user-old', display_name: 'Stale Match' }],
          page: 1,
          page_size: 50,
          count: 1,
        }
      }
      if (href.includes('search=new')) {
        return {
          items: [{ public_id: 'user-new', display_name: 'Newest Match' }],
          page: 1,
          page_size: 50,
          count: 1,
        }
      }
      throw new Error(`unexpected url: ${href}`)
    })

    const older = api.loadConfirmerCandidates({ reset: true, search: 'old', page: 1 })
    const newer = api.loadConfirmerCandidates({ reset: true, search: 'new', page: 1 })
    await newer
    expect(api.getConfirmerState().candidates.map((row) => row.display_name)).toEqual([
      'Newest Match',
    ])
    releaseOld?.()
    await older
    await flushPromises()
    expect(api.getConfirmerState().candidates.map((row) => row.display_name)).toEqual([
      'Newest Match',
    ])
  })
})
