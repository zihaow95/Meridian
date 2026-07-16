import { defineStore } from 'pinia'

import { apiFetch } from '@/api/client'
import type { components } from '@/api/generated/schema'

export type ProjectListItem = components['schemas']['ProjectListItem']
export type ProjectListResponse = components['schemas']['ProjectListResponse']
export type ProjectWorkbenchDetail = components['schemas']['ProjectWorkbenchDetail']
export type WorkbenchStagesResponse = components['schemas']['WorkbenchStagesResponse']
export type WorkbenchTasksResponse = components['schemas']['WorkbenchTasksResponse']
export type WorkbenchDeliverablesResponse = components['schemas']['WorkbenchDeliverablesResponse']
export type TaskCommandResponse = components['schemas']['TaskCommandResponse']
export type StageGateValidateResponse = components['schemas']['StageGateValidateResponse']
export type StageGateSubmissionResponse = components['schemas']['StageGateSubmissionResponse']
export type StageGateDecisionResponse = components['schemas']['StageGateDecisionResponse']
export type WorkbenchStageItem = components['schemas']['WorkbenchStageItem']
export type WorkbenchTaskItem = components['schemas']['WorkbenchTaskItem']
export type WorkbenchDeliverableItem = components['schemas']['WorkbenchDeliverableItem']

export const useProjectStore = defineStore('projects', {
  state: () => ({
    loading: false,
    page: 1,
    pageSize: 20,
    totalCount: 0,
    statusFilter: '',
    items: [] as ProjectListItem[],
    detail: null as ProjectWorkbenchDetail | null,
    stages: [] as WorkbenchStageItem[],
    tasks: [] as WorkbenchTaskItem[],
    deliverables: [] as WorkbenchDeliverableItem[],
    gateValidation: null as StageGateValidateResponse | null,
    lastGateDecision: null as StageGateDecisionResponse | null,
  }),
  actions: {
    async fetchProjects(
      filters: { status?: string; page?: number; page_size?: number } = {},
    ): Promise<void> {
      this.loading = true
      try {
        const params = new URLSearchParams()
        const page = filters.page ?? this.page
        const pageSize = filters.page_size ?? this.pageSize
        params.set('page', String(page))
        params.set('page_size', String(pageSize))
        const status = filters.status ?? this.statusFilter
        if (status) params.set('status', status)
        const query = params.toString() ? `?${params.toString()}` : ''
        const result = await apiFetch<ProjectListResponse>(`/api/v1/projects${query}`)
        this.items = result.items
        this.page = result.page
        this.pageSize = result.page_size
        this.totalCount = result.count
        this.statusFilter = status
      } finally {
        this.loading = false
      }
    },
    async fetchProjectDetail(publicId: string): Promise<void> {
      this.loading = true
      try {
        this.detail = await apiFetch<ProjectWorkbenchDetail>(`/api/v1/projects/${publicId}`)
      } finally {
        this.loading = false
      }
    },
    async fetchStages(publicId: string): Promise<void> {
      const result = await apiFetch<WorkbenchStagesResponse>(`/api/v1/projects/${publicId}/stages`)
      this.stages = result.items
    },
    async fetchTasks(publicId: string): Promise<void> {
      const result = await apiFetch<WorkbenchTasksResponse>(`/api/v1/projects/${publicId}/tasks`)
      this.tasks = result.items
    },
    async fetchDeliverables(publicId: string): Promise<void> {
      const result = await apiFetch<WorkbenchDeliverablesResponse>(
        `/api/v1/projects/${publicId}/deliverables`,
      )
      this.deliverables = result.items
    },
    async refreshWorkbench(publicId: string): Promise<void> {
      await Promise.all([
        this.fetchProjectDetail(publicId),
        this.fetchStages(publicId),
        this.fetchTasks(publicId),
        this.fetchDeliverables(publicId),
      ])
    },
    async assignTask(
      taskPublicId: string,
      payload: { user_public_id: string; version_no: number },
    ): Promise<TaskCommandResponse> {
      const result = await apiFetch<TaskCommandResponse>(`/api/v1/tasks/${taskPublicId}/assign`, {
        method: 'POST',
        json: payload,
      })
      const index = this.tasks.findIndex((task) => task.public_id === taskPublicId)
      if (index >= 0) {
        this.tasks[index] = {
          ...this.tasks[index],
          responsible_user_public_id: result.responsible_user_public_id ?? null,
          version_no: result.version_no ?? this.tasks[index].version_no + 1,
        }
      }
      return result
    },
    async transitionTask(
      taskPublicId: string,
      payload: { status: string; version_no: number },
    ): Promise<TaskCommandResponse> {
      const result = await apiFetch<TaskCommandResponse>(
        `/api/v1/tasks/${taskPublicId}/transition`,
        {
          method: 'POST',
          json: payload,
        },
      )
      const index = this.tasks.findIndex((task) => task.public_id === taskPublicId)
      if (index >= 0 && result.status && result.version_no !== undefined) {
        this.tasks[index] = {
          ...this.tasks[index],
          status: result.status,
          version_no: result.version_no,
        }
      }
      return result
    },
    async validateStageGate(stageGatePublicId: string): Promise<StageGateValidateResponse> {
      const result = await apiFetch<StageGateValidateResponse>(
        `/api/v1/stage-gates/${stageGatePublicId}/validate`,
        { method: 'POST' },
      )
      this.gateValidation = result
      return result
    },
    async submitStageGate(
      stageGatePublicId: string,
      idempotencyKey: string,
    ): Promise<StageGateSubmissionResponse> {
      return apiFetch<StageGateSubmissionResponse>(
        `/api/v1/stage-gates/${stageGatePublicId}/submissions`,
        {
          method: 'POST',
          json: { idempotency_key: idempotencyKey },
        },
      )
    },
    async recordNormalGateDecision(
      stageGatePublicId: string,
      payload: {
        result: string
        idempotency_key: string
        decision_summary?: string
        exception_rationale?: string
      },
    ): Promise<StageGateDecisionResponse> {
      const result = await apiFetch<StageGateDecisionResponse>(
        `/api/v1/stage-gates/${stageGatePublicId}/decision`,
        { method: 'POST', json: payload },
      )
      this.lastGateDecision = result
      return result
    },
    async recordFirstLaunchManagementConclusion(
      stageGatePublicId: string,
      payload: {
        management_conclusion: string
        idempotency_key: string
        decision_summary?: string
      },
    ): Promise<StageGateDecisionResponse> {
      return apiFetch<StageGateDecisionResponse>(
        `/api/v1/stage-gates/${stageGatePublicId}/first-launch-management-conclusion`,
        { method: 'POST', json: payload },
      )
    },
    async recordFirstLaunchFinalDecision(
      stageGatePublicId: string,
      payload: {
        final_decision: string
        idempotency_key: string
        decision_summary?: string
      },
    ): Promise<StageGateDecisionResponse> {
      const result = await apiFetch<StageGateDecisionResponse>(
        `/api/v1/stage-gates/${stageGatePublicId}/first-launch-final-decision`,
        { method: 'POST', json: payload },
      )
      this.lastGateDecision = result
      return result
    },
    async retryPublishRepair(projectPublicId: string): Promise<{ status: string }> {
      return apiFetch<{ status: string }>(`/api/v1/projects/${projectPublicId}/publish-repair`, {
        method: 'POST',
        json: {},
      })
    },
  },
})
