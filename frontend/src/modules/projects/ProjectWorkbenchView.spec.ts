import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, ref } from 'vue'

const routeParams = ref({ publicId: 'proj-1' })
const routePath = ref('/projects/proj-1')

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ params: routeParams.value, path: routePath.value, query: {} }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch, ApiError } from '@/api/client'
import ProjectWorkbenchView from '@/modules/projects/ProjectWorkbenchView.vue'

const stubs = {
  TaskPanel: defineComponent({
    name: 'TaskPanelStub',
    props: ['projectPublicId', 'leaderPublicId'],
    setup(props) {
      return () => h('div', { 'data-test': 'task-panel' }, props.projectPublicId as string)
    },
  }),
  DeliverablePanel: defineComponent({
    name: 'DeliverablePanelStub',
    props: ['projectPublicId'],
    setup(props) {
      return () => h('div', { 'data-test': 'deliverable-panel' }, props.projectPublicId as string)
    },
  }),
  StageGatePanel: defineComponent({
    name: 'StageGatePanelStub',
    props: ['launchMode'],
    setup() {
      return () => h('div', { 'data-test': 'stage-gate-panel' })
    },
  }),
  'el-tabs': defineComponent({
    name: 'ElTabsStub',
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(_, { slots }) {
      return () => h('div', { class: 'tabs' }, slots.default?.())
    },
  }),
  'el-tab-pane': defineComponent({
    name: 'ElTabPaneStub',
    props: ['label', 'name'],
    setup(props, { slots }) {
      return () => h('section', { 'data-tab': props.name as string }, slots.default?.())
    },
  }),
  'el-button': defineComponent({
    name: 'ElButtonStub',
    props: ['loading'],
    setup(_, { slots, attrs }) {
      return () => h('button', attrs, slots.default?.())
    },
  }),
  'el-alert': defineComponent({
    name: 'ElAlertStub',
    props: ['title', 'type'],
    setup(props) {
      return () => h('div', { class: 'alert', 'data-type': props.type as string }, props.title as string)
    },
  }),
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

const detailPayload = {
  public_id: 'proj-1',
  business_no: 'PRJ-001',
  name: 'Execution project',
  project_type: 'NEW_PRODUCT',
  status: 'EXECUTING',
  candidate_public_id: null,
  leader_public_id: 'leader-1',
  deputy_leader_public_id: null,
  product_asset_public_id: null,
  product_draft_public_id: null,
  current_stage_code: 'D3',
  opportunity_sources: [],
}

function mockWorkbenchApis(status = 'EXECUTING'): void {
  vi.mocked(apiFetch).mockImplementation(async (url: string) => {
    if (url === '/api/v1/projects/proj-1') {
      return { ...detailPayload, status }
    }
    if (url === '/api/v1/projects/proj-1/stages') {
      return {
        items: [
          {
            public_id: 'stage-1',
            stage_code: 'D3',
            name: '开发',
            sequence_no: 3,
            status: 'IN_PROGRESS',
            gate_code: 'G3',
            gate_type: 'NORMAL',
            handling_mode: 'STANDARD',
            planned_end_at: null,
          },
        ],
      }
    }
    if (url === '/api/v1/projects/proj-1/tasks') return { items: [] }
    if (url === '/api/v1/projects/proj-1/deliverables') return { items: [] }
    throw new Error(`Unexpected url ${url}`)
  })
}

describe('ProjectWorkbenchView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    routeParams.value = { publicId: 'proj-1' }
    routePath.value = '/projects/proj-1'
  })

  it('loads project detail and renders execution tabs', async () => {
    mockWorkbenchApis()
    const wrapper = mount(ProjectWorkbenchView, { global: { stubs } })
    await flush()

    expect(wrapper.text()).toContain('Execution project')
    expect(wrapper.find('[data-test="task-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="deliverable-panel"]').exists()).toBe(true)
  })

  it('shows publish pending repair banner when project status requires repair', async () => {
    mockWorkbenchApis('PUBLISH_PENDING_REPAIR')
    const wrapper = mount(ProjectWorkbenchView, { global: { stubs } })
    await flush()

    expect(wrapper.text()).toContain('PUBLISH_PENDING_REPAIR')
    expect(wrapper.find('.alert[data-type="warning"]').exists()).toBe(true)
  })

  it('shows launch gate panel on launch-gate route', async () => {
    routePath.value = '/projects/proj-1/launch-gate'
    mockWorkbenchApis()
    const wrapper = mount(ProjectWorkbenchView, { global: { stubs } })
    await flush()

    expect(wrapper.find('[data-test="stage-gate-panel"]').exists()).toBe(true)
  })

  it('shows trace id when project detail is forbidden', async () => {
    vi.mocked(apiFetch).mockRejectedValue(
      new ApiError(404, {
        code: 'RESOURCE_NOT_FOUND',
        message: 'Project not visible',
        details: {},
        trace_id: 'trace-proj-404',
      }),
    )

    const wrapper = mount(ProjectWorkbenchView, { global: { stubs } })
    await flush()

    expect(wrapper.find('.alert').text()).toContain('RESOURCE_NOT_FOUND')
    expect(wrapper.find('.alert').text()).toContain('trace-proj-404')
  })
})
