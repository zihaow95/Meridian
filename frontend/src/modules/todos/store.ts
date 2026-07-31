import { defineStore } from 'pinia'

import { apiFetch } from '@/api/client'
import type { components } from '@/api/generated/schema'

export type TodoItem = {
  public_id: string
  title: string
  status: 'OPEN' | 'COMPLETED' | 'CANCELLED' | 'EXPIRED'
  category?: string | null
  level?: string | null
  due_at?: string | null
  deep_link: string
}

export type NotificationItem = components['schemas']['MyNotificationItem']
export type NotificationPage = components['schemas']['MyNotificationPage']

export const useTodoStore = defineStore('todos', {
  state: () => ({
    items: [] as TodoItem[],
    notifications: [] as NotificationItem[],
    unreadCount: 0,
    notificationPage: 1,
    notificationCount: 0,
    loading: false,
    notificationsLoading: false,
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
    async fetchMyNotifications(
      filters: {
        status?: string
        category?: string
        level?: string
        page?: number
      } = {},
    ): Promise<void> {
      this.notificationsLoading = true
      this.lastError = null
      try {
        const params = new URLSearchParams()
        if (filters.status) params.set('status', filters.status)
        if (filters.category) params.set('category', filters.category)
        if (filters.level) params.set('level', filters.level)
        if (filters.page) params.set('page', String(filters.page))
        const query = params.toString() ? `?${params.toString()}` : ''
        const page = await apiFetch<NotificationPage>(`/api/v1/notifications/my${query}`)
        this.notifications = page.items
        this.unreadCount = page.unread_count
        this.notificationPage = page.page
        this.notificationCount = page.count
      } catch (err) {
        this.notifications = []
        this.unreadCount = 0
        this.lastError = err as Error
        throw err
      } finally {
        this.notificationsLoading = false
      }
    },
    async markNotificationRead(publicId: string): Promise<void> {
      const updated = await apiFetch<NotificationItem>(`/api/v1/notifications/${publicId}/read`, {
        method: 'POST',
      })
      this.notifications = this.notifications.map((item) =>
        item.public_id === publicId ? updated : item,
      )
      await this.fetchMyNotifications({ page: this.notificationPage })
    },
    async closeNotification(publicId: string, closeReason = ''): Promise<void> {
      const updated = await apiFetch<NotificationItem>(`/api/v1/notifications/${publicId}/close`, {
        method: 'POST',
        json: { close_reason: closeReason },
      })
      this.notifications = this.notifications.map((item) =>
        item.public_id === publicId ? updated : item,
      )
      await this.fetchMyNotifications({ page: this.notificationPage })
    },
  },
})
