import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, inject, provide, type InjectionKey } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch, ApiError } from '@/api/client'
import ConfigurationListView from '@/modules/admin/ConfigurationListView.vue'

// el-table-column reads its row from the enclosing el-table row. These stubs
// reproduce that binding through provide/inject so the unit test never needs
// the real Element Plus table.
const ROW_KEY = Symbol('row') as InjectionKey<Record<string, unknown>>

const RowProvider = defineComponent({
  props: { row: { type: Object, required: true } },
  setup(props, { slots }) {
    provide(ROW_KEY, props.row as Record<string, unknown>)
    return () => h('div', { class: 'row' }, slots.default?.())
  },
})

const stubs = {
  'el-button': defineComponent({
    props: ['disabled', 'loading'],
    setup(props, { slots, attrs }) {
      return () =>
        h(
          'button',
          { ...attrs, disabled: Boolean(props.disabled) || Boolean(props.loading) },
          slots.default?.(),
        )
    },
  }),
  'el-alert': defineComponent({
    props: ['title'],
    setup(props) {
      return () => h('div', { class: 'alert' }, props.title as string)
    },
  }),
  'el-empty': defineComponent({
    props: ['description'],
    setup(props) {
      return () => h('div', { class: 'empty' }, props.description as string)
    },
  }),
  'el-table': defineComponent({
    props: ['data'],
    setup(props, { slots }) {
      return () =>
        h(
          'div',
          { class: 'table' },
          (props.data as Record<string, unknown>[]).map((row) =>
            h(RowProvider, { row }, { default: () => slots.default?.() }),
          ),
        )
    },
  }),
  'el-table-column': defineComponent({
    props: ['prop', 'label'],
    setup(props, { slots }) {
      const row = inject(ROW_KEY, {} as Record<string, unknown>)
      return () => {
        if (slots.default) return h('div', slots.default({ row }))
        const key = props.prop as string | undefined
        return h('div', key ? String(row[key] ?? '') : '')
      }
    },
  }),
  'el-tag': defineComponent({
    setup(_, { slots }) {
      return () => h('span', slots.default?.())
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

const DEFINITIONS = [
  { definition_code: 'TECHNICAL_FILE_CATALOG', name: '技术文件目录', description: '' },
]
const VERSIONS = [
  { public_id: 'v-1', version_number: 2, status: 'DRAFT', published_at: null },
  {
    public_id: 'v-0',
    version_number: 1,
    status: 'PUBLISHED',
    published_at: '2026-07-01T00:00:00Z',
  },
]
const PENDING = [
  {
    public_id: 'req-1',
    definition_code: 'TECHNICAL_FILE_CATALOG',
    version_public_id: 'v-1',
    version_number: 2,
    proposed_by: 'user-1',
    status: 'PENDING',
    expires_at: '2026-08-07T00:00:00Z',
  },
]

function routeFetch(overrides: Record<string, unknown> = {}) {
  return (url: string) => {
    if (url in overrides) {
      const value = overrides[url]
      return value instanceof Error ? Promise.reject(value) : Promise.resolve(value)
    }
    if (url === '/api/v1/configurations/definitions') return Promise.resolve(DEFINITIONS)
    if (url.endsWith('/versions')) return Promise.resolve(VERSIONS)
    if (url === '/api/v1/configurations/publication-requests') return Promise.resolve(PENDING)
    if (url.includes('/versions/') && url.endsWith('/publication-requests')) {
      return Promise.resolve({ public_id: 'req-2', status: 'PENDING' })
    }
    if (url.endsWith('/review')) return Promise.resolve({ public_id: 'req-1', status: 'APPROVED' })
    if (url === '/api/v1/configurations/versions/v-1') {
      return Promise.resolve({
        public_id: 'v-1',
        definition_code: 'TECHNICAL_FILE_CATALOG',
        version_number: 2,
        status: 'DRAFT',
        content_digest: 'abc123',
        content_json: { catalog_items: [] },
        validation_errors: [],
        diff_summary: { previous_version_number: 1 },
      })
    }
    // An unrouted URL means the view called something we did not agree on.
    return Promise.reject(new Error(`unexpected request: ${url}`))
  }
}

async function mountLoaded(fetchImpl = routeFetch()) {
  vi.mocked(apiFetch).mockImplementation(fetchImpl as never)
  const wrapper = mount(ConfigurationListView, { global: { stubs } })
  await flush()
  await flush()
  return wrapper
}

describe('ConfigurationListView', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
  })

  it('lists configuration definitions', async () => {
    const wrapper = await mountLoaded()
    expect(wrapper.text()).toContain('TECHNICAL_FILE_CATALOG')
  })

  it('shows an empty state when no definition exists', async () => {
    const wrapper = await mountLoaded(
      routeFetch({ '/api/v1/configurations/definitions': [] }) as never,
    )
    expect(wrapper.find('.empty').exists()).toBe(true)
  })

  it('surfaces permission errors with the trace id', async () => {
    const denied = new ApiError(404, {
      code: 'RESOURCE_NOT_FOUND',
      message: 'denied',
      details: {},
      trace_id: 'trace-config',
    })
    const wrapper = await mountLoaded(
      routeFetch({ '/api/v1/configurations/definitions': denied }) as never,
    )
    expect(wrapper.find('.alert').text()).toContain('trace-config')
  })

  it('loads the versions of the selected definition', async () => {
    const wrapper = await mountLoaded()
    await wrapper.find('[data-test="select-definition"]').trigger('click')
    await flush()
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/v1/configurations/definitions/TECHNICAL_FILE_CATALOG/versions',
    )
  })

  it('shows the diff summary and digest of the selected version', async () => {
    const wrapper = await mountLoaded()
    await wrapper.find('[data-test="select-definition"]').trigger('click')
    await flush()
    await wrapper.find('[data-test="select-version"]').trigger('click')
    await flush()
    expect(wrapper.find('[data-test="version-detail"]').text()).toContain('abc123')
  })

  it('reports validation errors on a failed draft', async () => {
    const wrapper = await mountLoaded(
      routeFetch({
        '/api/v1/configurations/versions/v-1': {
          public_id: 'v-1',
          definition_code: 'TECHNICAL_FILE_CATALOG',
          version_number: 2,
          status: 'FAILED',
          content_digest: 'abc123',
          content_json: null,
          validation_errors: ["'max_bytes' is a required property"],
          diff_summary: {},
        },
      }) as never,
    )
    await wrapper.find('[data-test="select-definition"]').trigger('click')
    await flush()
    await wrapper.find('[data-test="select-version"]').trigger('click')
    await flush()
    expect(wrapper.find('[data-test="validation-errors"]').text()).toContain('max_bytes')
  })

  it('says the content is withheld when the reader may not see it', async () => {
    const wrapper = await mountLoaded(
      routeFetch({
        '/api/v1/configurations/versions/v-1': {
          public_id: 'v-1',
          definition_code: 'TECHNICAL_FILE_CATALOG',
          version_number: 2,
          status: 'DRAFT',
          content_digest: 'abc123',
          content_json: null,
          validation_errors: [],
          diff_summary: {},
        },
      }) as never,
    )
    await wrapper.find('[data-test="select-definition"]').trigger('click')
    await flush()
    await wrapper.find('[data-test="select-version"]').trigger('click')
    await flush()
    expect(wrapper.find('[data-test="content-withheld"]').exists()).toBe(true)
  })

  it('lists publication requests waiting for a reviewer', async () => {
    const wrapper = await mountLoaded()
    expect(wrapper.find('[data-test="pending-requests"]').text()).toContain('req-1')
  })

  it('submits a publication request for the selected draft', async () => {
    const wrapper = await mountLoaded()
    await wrapper.find('[data-test="select-definition"]').trigger('click')
    await flush()
    await wrapper.find('[data-test="select-version"]').trigger('click')
    await flush()

    await wrapper.find('[data-test="request-publication"]').trigger('click')
    await flush()

    expect(apiFetch).toHaveBeenCalledWith(
      '/api/v1/configurations/versions/v-1/publication-requests',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('does not submit the same publication request twice on a double click', async () => {
    let resolveRequest: (value: unknown) => void = () => {}
    const pending = new Promise((resolve) => {
      resolveRequest = resolve
    })
    const wrapper = await mountLoaded(
      routeFetch({
        '/api/v1/configurations/versions/v-1/publication-requests': pending,
      }) as never,
    )
    await wrapper.find('[data-test="select-definition"]').trigger('click')
    await flush()
    await wrapper.find('[data-test="select-version"]').trigger('click')
    await flush()

    const button = wrapper.find('[data-test="request-publication"]')
    await button.trigger('click')
    await button.trigger('click')
    resolveRequest({ public_id: 'req-2', status: 'PENDING' })
    await flush()

    const submissions = vi
      .mocked(apiFetch)
      .mock.calls.filter(
        ([url]) => url === '/api/v1/configurations/versions/v-1/publication-requests',
      )
    expect(submissions).toHaveLength(1)
  })

  it('approves a pending request', async () => {
    const wrapper = await mountLoaded()

    await wrapper.find('[data-test="approve-request"]').trigger('click')
    await flush()

    expect(apiFetch).toHaveBeenCalledWith(
      '/api/v1/configurations/publication-requests/req-1/review',
      expect.objectContaining({ method: 'POST', json: { decision: 'APPROVED' } }),
    )
  })

  it('tells the reviewer to refresh and compare when the request already moved on', async () => {
    const conflict = new ApiError(409, {
      code: 'CONFIGURATION_PUBLICATION_REQUEST_NOT_PENDING',
      message: 'no longer pending',
      details: {},
      trace_id: 'trace-conflict',
    })
    const wrapper = await mountLoaded(
      routeFetch({
        '/api/v1/configurations/publication-requests/req-1/review': conflict,
      }) as never,
    )

    await wrapper.find('[data-test="approve-request"]').trigger('click')
    await flush()

    const text = wrapper.find('[data-test="conflict-notice"]').text()
    expect(text).toContain('刷新')
    expect(text).toContain('trace-conflict')
  })
})
