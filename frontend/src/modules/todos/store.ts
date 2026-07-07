import { defineStore } from 'pinia'

export type TodoItem = {
  id: string
  title: string
  status: 'OPEN' | 'COMPLETED' | 'CANCELLED' | 'EXPIRED'
  due_at?: string | null
  deep_link: string
}

export const useTodoStore = defineStore('todos', {
  state: () => ({
    items: [] as TodoItem[],
    loading: false,
  }),
  actions: {
    // Phase 1: backend todo list API will follow; keep UI functional with local placeholder.
    async fetchMyTodos(): Promise<void> {
      this.loading = true
      try {
        this.items = [
          {
            id: 'demo-1',
            title: '（示例）平台内核待办：检查权限与审计闭环',
            status: 'OPEN',
            due_at: null,
            deep_link: '/admin/audit',
          },
        ]
      } finally {
        this.loading = false
      }
    },
  },
})
