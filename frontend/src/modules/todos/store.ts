import { defineStore } from 'pinia'

import { apiFetch } from '@/api/client'

export type TodoItem = {
  public_id: string
  title: string
  status: 'OPEN' | 'COMPLETED' | 'CANCELLED' | 'EXPIRED'
  due_at?: string | null
  deep_link: string
}

export const useTodoStore = defineStore('todos', {
  state: () => ({
    items: [] as TodoItem[],
    loading: false,
    lastError: null as Error | null,
  }),
  actions: {
    async fetchMyTodos(status?: TodoItem['status']): Promise<void> {
      this.loading = true
      this.lastError = null
      try {
        const query = status ? `?status=${status}` : ''
        this.items = await apiFetch<TodoItem[]>(`/api/v1/todos/my${query}`)
      } catch (err) {
        this.items = []
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
  },
})
