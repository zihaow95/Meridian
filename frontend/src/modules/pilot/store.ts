import { defineStore } from 'pinia'

import { apiFetch } from '@/api/client'

export type PilotBatch = {
  public_id: string
  name: string
  purpose: string
  status: string
  planned_participant_count: number
  planned_duration_days: number
  version_no: number
  started_at?: string | null
  completed_at?: string | null
  participants?: PilotParticipant[]
}

export type PilotParticipant = {
  public_id: string
  user_public_id: string
  display_name_snapshot: string
  employee_no_snapshot: string
  department_snapshot: string
}

export type PilotFeedback = {
  public_id: string
  batch_public_id: string
  title: string
  reproduction_summary: string
  severity: string
  status: string
  version_no: number
  assignee_public_id?: string | null
  target_version?: string
}

export const usePilotStore = defineStore('pilot', {
  state: () => ({
    batches: [] as PilotBatch[],
    selected: null as PilotBatch | null,
    feedback: [] as PilotFeedback[],
    loading: false,
    lastError: null as Error | null,
  }),
  actions: {
    async fetchBatches(): Promise<void> {
      this.loading = true
      this.lastError = null
      try {
        const page = await apiFetch<{ items: PilotBatch[] }>('/api/v1/pilot/batches')
        this.batches = page.items
      } catch (err) {
        this.batches = []
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
    async createBatch(payload: {
      name: string
      planned_participant_count?: number
      planned_duration_days?: number
    }): Promise<PilotBatch> {
      const batch = await apiFetch<PilotBatch>('/api/v1/pilot/batches', {
        method: 'POST',
        json: payload,
      })
      await this.fetchBatches()
      return batch
    },
    async loadBatch(publicId: string): Promise<void> {
      this.loading = true
      this.lastError = null
      try {
        this.selected = await apiFetch<PilotBatch>(`/api/v1/pilot/batches/${publicId}`)
        const page = await apiFetch<{ items: PilotFeedback[] }>(
          `/api/v1/pilot/batches/${publicId}/feedback`,
        )
        this.feedback = page.items
      } catch (err) {
        this.selected = null
        this.feedback = []
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
    async openFeedback(batchPublicId: string, title: string, summary: string): Promise<void> {
      await apiFetch(`/api/v1/pilot/batches/${batchPublicId}/feedback`, {
        method: 'POST',
        json: { title, reproduction_summary: summary },
      })
      await this.loadBatch(batchPublicId)
    },
  },
})
