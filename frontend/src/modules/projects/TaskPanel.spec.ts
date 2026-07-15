import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch, ApiError } from '@/api/client'
import TaskPanel from '@/modules/projects/TaskPanel.vue'
import { useProjectStore } from '@/modules/projects/store'

const stubs = {
  'el-table': defineComponent({
    name: 'ElTableStub',
    props: ['data'],
    setup(props) {
      return () => {
        const rows = (props.data as Array<{ name: string; task_code: string }>) ?? []
        return h(
          'div',
          { class: 'table' },
          rows.map((row) => h('div', { 'data-test': 'task-row' }, `${row.task_code} ${row.name}`)),
        )
      }
    },
  }),
  'el-table-column': defineComponent({
    name: 'ElTableColumnStub',
    setup(_, { slots }) {
      return () =>
        h(
          'div',
          slots.default?.({
            row: {
              public_id: 'task-1',
              task_code: 'T-001',
              name: 'Core task',
              status: 'NOT_STARTED',
              version_no: 1,
              responsible_user_public_id: null,
              is_core: true,
            },
          }),
        )
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

describe('TaskPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
  })

  it('renders tasks loaded from the store', async () => {
    const store = useProjectStore()
    store.tasks = [
      {
        public_id: 'task-1',
        task_code: 'T-001',
        name: 'Core task',
        stage_code: 'D3',
        status: 'NOT_STARTED',
        is_core: true,
        version_no: 1,
        responsible_user_public_id: null,
        responsible_department_public_id: 'dept-1',
      },
    ]

    const wrapper = mount(TaskPanel, {
      props: { projectPublicId: 'proj-1', leaderPublicId: 'leader-1', actorPublicId: 'leader-1' },
      global: { stubs },
    })
    await flush()

    expect(wrapper.text()).toContain('T-001')
    expect(wrapper.text()).toContain('Core task')
  })

  it('shows TASK_VERSION_CONFLICT when assign returns 409', async () => {
    const store = useProjectStore()
    store.tasks = [
      {
        public_id: 'task-1',
        task_code: 'T-001',
        name: 'Core task',
        stage_code: 'D3',
        status: 'NOT_STARTED',
        is_core: true,
        version_no: 1,
        responsible_user_public_id: null,
        responsible_department_public_id: 'dept-1',
      },
    ]

    vi.mocked(apiFetch).mockRejectedValue(
      new ApiError(409, {
        code: 'TASK_VERSION_CONFLICT',
        message: 'The task was updated by another operation.',
        details: {},
        trace_id: 'trace-task-409',
      }),
    )

    const wrapper = mount(TaskPanel, {
      props: { projectPublicId: 'proj-1', leaderPublicId: 'leader-1', actorPublicId: 'leader-1' },
      global: { stubs },
    })
    await flush()

    await wrapper.get('input').setValue('worker-1')
    await wrapper.get('[data-test="assign-task"]').trigger('click')
    await flush()

    expect(wrapper.find('.alert').text()).toContain('TASK_VERSION_CONFLICT')
  })

  it('hides assign action for non-leader actors', async () => {
    const store = useProjectStore()
    store.tasks = [
      {
        public_id: 'task-1',
        task_code: 'T-001',
        name: 'Core task',
        stage_code: 'D3',
        status: 'NOT_STARTED',
        is_core: true,
        version_no: 1,
        responsible_user_public_id: 'worker-1',
        responsible_department_public_id: 'dept-1',
      },
    ]

    const wrapper = mount(TaskPanel, {
      props: { projectPublicId: 'proj-1', leaderPublicId: 'leader-1', actorPublicId: 'worker-2' },
      global: { stubs },
    })
    await flush()

    expect(wrapper.find('[data-test="assign-task"]').exists()).toBe(false)
  })
})
