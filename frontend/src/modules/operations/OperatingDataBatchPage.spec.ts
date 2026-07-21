import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ query: {}, params: {} }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import OperatingDataBatchPage from '@/modules/operations/OperatingDataBatchPage.vue'
import { useOperationsStore } from '@/modules/operations/store'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['loading', 'disabled', 'type'],
    setup(props, { slots, attrs }) {
      return () =>
        h(
          'button',
          {
            ...attrs,
            disabled: props.loading || props.disabled ? true : undefined,
            'data-loading': props.loading ? '1' : undefined,
          },
          slots.default?.(),
        )
    },
  }),
  'el-input': defineComponent({
    name: 'ElInputStub',
    props: ['modelValue', 'type'],
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
  'el-checkbox': defineComponent({
    name: 'ElCheckboxStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(props, { emit, attrs, slots }) {
      return () =>
        h('label', [
          h('input', {
            ...attrs,
            type: 'checkbox',
            checked: Boolean(props.modelValue),
            onChange: (event: Event) =>
              emit('update:modelValue', (event.target as HTMLInputElement).checked),
          }),
          slots.default?.(),
        ])
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
  'el-table': defineComponent({
    name: 'ElTableStub',
    props: ['data'],
    setup(props, { slots }) {
      const rows = (props.data as Array<Record<string, unknown>>) ?? []
      return () =>
        h(
          'div',
          { class: 'table', 'data-count': rows.length },
          rows.map((row) =>
            h('div', { class: 'row' }, [
              String(row.status ?? row.row_number ?? ''),
              slots.default?.(),
            ]),
          ),
        )
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup() {
      return () => h('div')
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
    props: ['label'],
    setup(props, { slots }) {
      return () => h('div', [h('span', props.label as string), slots.default?.()])
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

const batchPayload = {
  public_id: 'batch-1',
  batch_key: 'b-1',
  source_public_id: 'src-1',
  source_type: 'API',
  status: 'VALIDATED',
  total_count: 2,
  success_count: 1,
  warning_count: 0,
  error_count: 1,
  skipped_count: 0,
  added_count: 0,
  revision_count: 0,
  rows: [
    { row_number: 1, status: 'OK' },
    { row_number: 2, status: 'ERROR', error_code: 'UNMAPPED_SKU' },
  ],
}

describe('OperatingDataBatchPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('creates a batch and shows status plus error rows', async () => {
    vi.mocked(apiFetch).mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/operating-data/batches' && init?.method === 'POST') {
        return batchPayload
      }
      throw new Error(`unexpected ${url}`)
    })

    const wrapper = mount(OperatingDataBatchPage, { global: { stubs } })
    await wrapper.get('[data-test="source-public-id"]').setValue('src-1')
    await wrapper.get('[data-test="batch-key"]').setValue('b-1')
    await wrapper.get('[data-test="rows-json"]').setValue('[{"sku_code":"S1"}]')
    await wrapper.get('[data-test="create-batch"]').trigger('click')
    await flush()

    expect(useOperationsStore().batch?.public_id).toBe('batch-1')
    expect(wrapper.text()).toContain('VALIDATED')
    expect(wrapper.text()).toContain('ERROR')
  })

  it('confirms a batch with confirm_warnings and lists unmapped rows', async () => {
    const store = useOperationsStore()
    store.batch = { ...batchPayload }

    vi.mocked(apiFetch).mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/operating-data/batches/batch-1/confirm' && init?.method === 'POST') {
        return {
          public_id: 'batch-1',
          added_count: 1,
          revision_count: 0,
          skipped_count: 0,
          error_count: 1,
          warning_count: 0,
        }
      }
      if (url.startsWith('/api/v1/operating-data/unmapped')) {
        return { items: [{ row_number: 2, status: 'UNMAPPED' }] }
      }
      throw new Error(`unexpected ${url}`)
    })

    const wrapper = mount(OperatingDataBatchPage, { global: { stubs } })
    await wrapper.get('[data-test="confirm-warnings"]').setValue(true)
    await wrapper.get('[data-test="confirm-batch"]').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('added 1')
    await wrapper.get('[data-test="load-unmapped"]').trigger('click')
    await flush()
    expect(wrapper.text()).toContain('UNMAPPED')
  })
})
