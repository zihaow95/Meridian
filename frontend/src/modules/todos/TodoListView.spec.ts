import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

import TodoListView from '@/modules/todos/TodoListView.vue'

describe('TodoListView', () => {
  it('renders the todo page title', () => {
    setActivePinia(createPinia())
    const wrapper = mount(TodoListView, {
      global: {
        plugins: [createPinia()],
        stubs: {
          'el-button': defineComponent({
            name: 'ElButtonStub',
            setup(_, { slots }) {
              return () => h('button', slots.default?.())
            },
          }),
          'el-table': defineComponent({
            name: 'ElTableStub',
            setup(_, { slots }) {
              return () => h('div', slots.default?.())
            },
          }),
          'el-table-column': defineComponent({
            name: 'ElTableColumnStub',
            setup(_, { slots }) {
              return () =>
                h(
                  'div',
                  slots.default?.({
                    row: { deep_link: '/demo', title: 't', status: 'OPEN' },
                  }),
                )
            },
          }),
        },
      },
    })
    expect(wrapper.text()).toContain('我的待办')
  })
})
