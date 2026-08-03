import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn() }),
}))

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client')
  return { ...actual, apiFetch: vi.fn() }
})

import { apiFetch } from '@/api/client'
import LoginView from '@/modules/auth/LoginView.vue'

const stubs = {
  'el-button': defineComponent({
    name: 'ElButtonStub',
    setup(_, { slots, attrs }) {
      return () => h('button', attrs, slots.default?.())
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
  'el-divider': defineComponent({
    name: 'ElDividerStub',
    setup() {
      return () => h('hr')
    },
  }),
}

describe('LoginView pilot password login', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(apiFetch).mockReset()
    vi.stubEnv('DEV', true)
    vi.stubEnv('PROD', false)
    vi.stubEnv('VITE_ENABLE_PILOT_PASSWORD_LOGIN', 'true')
  })

  it('shows the pilot form only when the backend capability is on', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      pilot_password_login: true,
      dev_login: false,
    })

    const wrapper = mount(LoginView, { global: { stubs } })
    await flushPromises()

    expect(wrapper.get('[data-test="pilot-login"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('非生产')
  })

  it('hides the pilot form when the backend capability is off', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      pilot_password_login: false,
      dev_login: false,
    })

    const wrapper = mount(LoginView, { global: { stubs } })
    await flushPromises()

    expect(wrapper.find('[data-test="pilot-login"]').exists()).toBe(false)
  })

  it('hides the pilot form when the vite flag explicitly disables it', async () => {
    vi.stubEnv('VITE_ENABLE_PILOT_PASSWORD_LOGIN', 'false')
    vi.mocked(apiFetch).mockResolvedValue({
      pilot_password_login: true,
      dev_login: false,
    })

    const wrapper = mount(LoginView, { global: { stubs } })
    await flushPromises()

    expect(wrapper.find('[data-test="pilot-login"]').exists()).toBe(false)
  })
})
