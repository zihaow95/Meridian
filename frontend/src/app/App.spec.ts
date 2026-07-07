import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { RouterView } from 'vue-router'
import { createPinia } from 'pinia'
import App from './App.vue'

describe('App shell', () => {
  it('identifies the formal Meridian application', () => {
    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterView: true },
        components: { RouterView },
      },
    })
    expect(wrapper.get('h1').text()).toBe('Project Meridian')
  })
})
