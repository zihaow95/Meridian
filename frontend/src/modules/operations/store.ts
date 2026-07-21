import { defineStore } from 'pinia'

import { ApiError, apiFetch } from '@/api/client'
import type { components } from '@/api/generated/schema'

export type OperatingIngestionBatch = components['schemas']['OperatingIngestionBatch']
export type OperatingIngestionBatchConfirmRequest =
  components['schemas']['OperatingIngestionBatchConfirmRequest']
export type OperatingIngestionBatchConfirmResponse =
  components['schemas']['OperatingIngestionBatchConfirmResponse']
export type OperatingIngestionBatchCreateRequest =
  components['schemas']['OperatingIngestionBatchCreateRequest']
export type OperatingManualValue = components['schemas']['OperatingManualValue']
export type OperatingManualValueCreateRequest =
  components['schemas']['OperatingManualValueCreateRequest']
export type OperatingManualValueRevokeRequest =
  components['schemas']['OperatingManualValueRevokeRequest']
export type OperatingSummaryResponse = components['schemas']['OperatingSummaryResponse']
export type OperatingUnmappedRowsResponse = components['schemas']['OperatingUnmappedRowsResponse']
export type OperatingDataExportRequest = components['schemas']['OperatingDataExportRequest']
export type OperatingDataExportResponse = components['schemas']['OperatingDataExportResponse']
export type RiskSignal = components['schemas']['RiskSignal']
export type RiskSignalCloseRequest = components['schemas']['RiskSignalCloseRequest']
export type RiskSignalEscalateRequest = components['schemas']['RiskSignalEscalateRequest']
export type RiskSignalEscalateResponse = components['schemas']['RiskSignalEscalateResponse']
export type OperatingIssue = components['schemas']['OperatingIssue'] & {
  linked_opportunity_id?: string | null
  linked_project_id?: string | null
  linked_product_version_id?: string | null
}
export type OperatingIssueDecisionRequest =
  components['schemas']['OperatingIssueDecisionRequest']
export type OperatingIssueDecisionResponse =
  components['schemas']['OperatingIssueDecisionResponse']
export type OperatingIssueIterationProposalRequest =
  components['schemas']['OperatingIssueIterationProposalRequest']
export type RetirementPlan = components['schemas']['RetirementPlan']
export type RetirementPlanCreateRequest = components['schemas']['RetirementPlanCreateRequest']
export type RetirementPlanValidateResponse =
  components['schemas']['RetirementPlanValidateResponse']
export type RetirementPlanSubmitRequest = components['schemas']['RetirementPlanSubmitRequest']
export type RetirementPlanSubmitResponse = components['schemas']['RetirementPlanSubmitResponse']
export type RetirementPlanExecuteRequest = components['schemas']['RetirementPlanExecuteRequest']
export type RetirementManagementRequest = components['schemas']['RetirementManagementRequest']
export type RetirementFinalRequest = components['schemas']['RetirementFinalRequest']

export type OperatingSummaryItem = {
  grain_type?: string
  grain_public_id?: string
  channel_public_id?: string | null
  metric_code?: string
  coverage_rate?: string
  status?: string
  value?: string | null
  has_manual_value?: boolean
  contributors?: unknown[]
  [key: string]: unknown
}

export type OperatingIssueDetail = {
  public_id: string
  business_no?: string
  title?: string
  status?: string
  version_no?: number
  product_public_id?: string
  phenomenon_summary?: string
  data_snapshot_public_id?: string | null
  linked_opportunity_id?: string | null
  linked_project_id?: string | null
  linked_product_version_id?: string | null
  signals?: Array<{
    signal_public_id: string
    is_primary?: boolean
    active_primary_slot?: number | null
    unlinked_at?: string | null
  }>
  decisions?: Array<{
    public_id: string
    recommendation_type: string
    action_summary: string
    decided_at?: string
  }>
  [key: string]: unknown
}

function isConflict(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 409
}

export const useOperationsStore = defineStore('operations', {
  state: () => ({
    loading: false,
    conflictHint: '',
    batch: null as OperatingIngestionBatch | null,
    confirmResult: null as OperatingIngestionBatchConfirmResponse | null,
    unmappedRows: [] as unknown[],
    manualValue: null as OperatingManualValue | null,
    productSummary: null as OperatingSummaryResponse | null,
    skuSummary: null as OperatingSummaryResponse | null,
    riskSignals: [] as RiskSignal[],
    riskFilterStatus: '' as string,
    lastEscalation: null as RiskSignalEscalateResponse | null,
    issues: [] as OperatingIssue[],
    currentIssue: null as OperatingIssue | null,
    currentIssueDetail: null as OperatingIssueDetail | null,
    lastDecision: null as OperatingIssueDecisionResponse | null,
    retirementPlan: null as RetirementPlan | null,
    retirementValidation: null as RetirementPlanValidateResponse | null,
    retirementSubmit: null as RetirementPlanSubmitResponse | null,
    lastGateDecision: null as Record<string, unknown> | null,
    exportTicket: null as OperatingDataExportResponse | null,
  }),
  getters: {
    productSummaryItems(state): OperatingSummaryItem[] {
      return (state.productSummary?.items as OperatingSummaryItem[] | undefined) ?? []
    },
    skuSummaryItems(state): OperatingSummaryItem[] {
      return (state.skuSummary?.items as OperatingSummaryItem[] | undefined) ?? []
    },
  },
  actions: {
    clearConflictHint(): void {
      this.conflictHint = ''
    },

    async createBatch(payload: OperatingIngestionBatchCreateRequest): Promise<OperatingIngestionBatch> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.batch = await apiFetch<OperatingIngestionBatch>('/api/v1/operating-data/batches', {
          method: 'POST',
          json: payload,
        })
        return this.batch
      } finally {
        this.loading = false
      }
    },

    async fetchBatch(publicId: string): Promise<void> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.batch = await apiFetch<OperatingIngestionBatch>(
          `/api/v1/operating-data/batches/${publicId}`,
        )
      } finally {
        this.loading = false
      }
    },

    async confirmBatch(
      publicId: string,
      payload: OperatingIngestionBatchConfirmRequest,
    ): Promise<OperatingIngestionBatchConfirmResponse> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.confirmResult = await apiFetch<OperatingIngestionBatchConfirmResponse>(
          `/api/v1/operating-data/batches/${publicId}/confirm`,
          { method: 'POST', json: payload },
        )
        if (this.batch && this.batch.public_id === publicId) {
          this.batch = {
            ...this.batch,
            added_count: this.confirmResult.added_count,
            revision_count: this.confirmResult.revision_count,
            skipped_count: this.confirmResult.skipped_count,
            error_count: this.confirmResult.error_count,
            warning_count: this.confirmResult.warning_count,
            status: 'CONFIRMED',
          }
        }
        return this.confirmResult
      } catch (err) {
        if (isConflict(err)) {
          this.conflictHint = '数据已变更，请刷新后比较再提交。'
          try {
            await this.fetchBatch(publicId)
          } catch {
            // Keep conflict guidance even if refresh fails.
          }
        }
        throw err
      } finally {
        this.loading = false
      }
    },

    async retryBatch(publicId: string): Promise<OperatingIngestionBatch> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.batch = await apiFetch<OperatingIngestionBatch>(
          `/api/v1/operating-data/batches/${publicId}/retry`,
          { method: 'POST' },
        )
        return this.batch
      } finally {
        this.loading = false
      }
    },

    async fetchUnmappedRows(batchPublicId?: string): Promise<void> {
      this.loading = true
      try {
        const params = new URLSearchParams()
        if (batchPublicId) params.set('batch_public_id', batchPublicId)
        const query = params.toString() ? `?${params.toString()}` : ''
        const result = await apiFetch<OperatingUnmappedRowsResponse>(
          `/api/v1/operating-data/unmapped${query}`,
        )
        this.unmappedRows = result.items ?? []
      } finally {
        this.loading = false
      }
    },

    async createManualOverride(
      payload: OperatingManualValueCreateRequest,
    ): Promise<OperatingManualValue> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.manualValue = await apiFetch<OperatingManualValue>(
          '/api/v1/operating-values/overrides',
          { method: 'POST', json: payload },
        )
        return this.manualValue
      } finally {
        this.loading = false
      }
    },

    async revokeManualOverride(
      publicId: string,
      payload: OperatingManualValueRevokeRequest,
    ): Promise<OperatingManualValue> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.manualValue = await apiFetch<OperatingManualValue>(
          `/api/v1/operating-values/overrides/${publicId}/revoke`,
          { method: 'POST', json: payload },
        )
        return this.manualValue
      } catch (err) {
        if (isConflict(err)) {
          this.conflictHint = '数据已变更，请刷新后比较再提交。'
        }
        throw err
      } finally {
        this.loading = false
      }
    },

    async fetchProductSummary(
      productPublicId: string,
      query: {
        period_start: string
        period_end: string
        period_granularity?: string
        metric_codes?: string
        include_drilldown?: boolean
      },
    ): Promise<void> {
      this.loading = true
      try {
        const params = new URLSearchParams()
        params.set('period_start', query.period_start)
        params.set('period_end', query.period_end)
        if (query.period_granularity) params.set('period_granularity', query.period_granularity)
        if (query.metric_codes) params.set('metric_codes', query.metric_codes)
        if (query.include_drilldown) params.set('include_drilldown', 'true')
        this.productSummary = await apiFetch<OperatingSummaryResponse>(
          `/api/v1/products/${productPublicId}/operating-summary?${params.toString()}`,
        )
      } finally {
        this.loading = false
      }
    },

    async fetchSkuSummary(
      skuPublicId: string,
      query: {
        period_start: string
        period_end: string
        period_granularity?: string
        metric_codes?: string
        include_drilldown?: boolean
      },
    ): Promise<void> {
      this.loading = true
      try {
        const params = new URLSearchParams()
        params.set('period_start', query.period_start)
        params.set('period_end', query.period_end)
        if (query.period_granularity) params.set('period_granularity', query.period_granularity)
        if (query.metric_codes) params.set('metric_codes', query.metric_codes)
        if (query.include_drilldown) params.set('include_drilldown', 'true')
        this.skuSummary = await apiFetch<OperatingSummaryResponse>(
          `/api/v1/skus/${skuPublicId}/operating-summary?${params.toString()}`,
        )
      } finally {
        this.loading = false
      }
    },

    async createExport(payload: OperatingDataExportRequest): Promise<OperatingDataExportResponse> {
      this.loading = true
      try {
        this.exportTicket = await apiFetch<OperatingDataExportResponse>(
          '/api/v1/operating-data/exports',
          { method: 'POST', json: payload },
        )
        return this.exportTicket
      } finally {
        this.loading = false
      }
    },

    async fetchRiskSignals(status?: string): Promise<void> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.riskFilterStatus = status ?? ''
        const params = new URLSearchParams()
        if (status) params.set('status', status)
        const query = params.toString() ? `?${params.toString()}` : ''
        const result = await apiFetch<{ items: RiskSignal[] }>(`/api/v1/risk-signals${query}`)
        this.riskSignals = result.items ?? []
      } finally {
        this.loading = false
      }
    },

    async viewRiskSignal(publicId: string): Promise<void> {
      this.clearConflictHint()
      const updated = await apiFetch<RiskSignal>(`/api/v1/risk-signals/${publicId}/view`, {
        method: 'POST',
      })
      this.riskSignals = this.riskSignals.map((row) =>
        row.public_id === publicId ? updated : row,
      )
    },

    async closeRiskSignal(publicId: string, payload: RiskSignalCloseRequest): Promise<void> {
      this.clearConflictHint()
      try {
        const updated = await apiFetch<RiskSignal>(`/api/v1/risk-signals/${publicId}/close`, {
          method: 'POST',
          json: payload,
        })
        this.riskSignals = this.riskSignals.map((row) =>
          row.public_id === publicId ? updated : row,
        )
      } catch (err) {
        if (isConflict(err)) {
          this.conflictHint = '信号状态已变更，请刷新后比较再操作。'
          await this.fetchRiskSignals(this.riskFilterStatus || undefined)
        }
        throw err
      }
    },

    async escalateRiskSignal(
      publicId: string,
      payload: RiskSignalEscalateRequest,
    ): Promise<RiskSignalEscalateResponse> {
      this.clearConflictHint()
      try {
        this.lastEscalation = await apiFetch<RiskSignalEscalateResponse>(
          `/api/v1/risk-signals/${publicId}/escalate`,
          { method: 'POST', json: payload },
        )
        return this.lastEscalation
      } catch (err) {
        if (isConflict(err)) {
          this.conflictHint = '信号状态已变更，请刷新后比较再操作。'
          await this.fetchRiskSignals(this.riskFilterStatus || undefined)
        }
        throw err
      }
    },

    async fetchIssues(status?: string): Promise<void> {
      this.loading = true
      try {
        const params = new URLSearchParams()
        if (status) params.set('status', status)
        const query = params.toString() ? `?${params.toString()}` : ''
        const result = await apiFetch<{ items: OperatingIssue[] }>(
          `/api/v1/operating-issues${query}`,
        )
        this.issues = result.items ?? []
      } finally {
        this.loading = false
      }
    },

    async fetchIssue(publicId: string): Promise<void> {
      this.loading = true
      this.clearConflictHint()
      try {
        await this.fetchIssues()
        const found = this.issues.find((row) => row.public_id === publicId) ?? null
        this.currentIssue = found
        if (found && !this.currentIssueDetail) {
          this.currentIssueDetail = { ...found, signals: [], decisions: [] }
        } else if (found && this.currentIssueDetail?.public_id === publicId) {
          this.currentIssueDetail = {
            ...this.currentIssueDetail,
            ...found,
          }
        } else if (found) {
          this.currentIssueDetail = { ...found, signals: [], decisions: [] }
        } else {
          this.currentIssueDetail = null
        }
      } finally {
        this.loading = false
      }
    },

    async recordIssueDecision(
      publicId: string,
      payload: OperatingIssueDecisionRequest,
    ): Promise<OperatingIssueDecisionResponse> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.lastDecision = await apiFetch<OperatingIssueDecisionResponse>(
          `/api/v1/operating-issues/${publicId}/decisions`,
          { method: 'POST', json: payload },
        )
        const detail = this.lastDecision.issue as OperatingIssueDetail
        this.currentIssueDetail = detail
        if (detail.public_id) {
          this.currentIssue = {
            public_id: String(detail.public_id),
            business_no: String(detail.business_no ?? this.currentIssue?.business_no ?? ''),
            title: String(detail.title ?? this.currentIssue?.title ?? ''),
            status: String(detail.status ?? this.currentIssue?.status ?? ''),
            version_no: Number(detail.version_no ?? this.currentIssue?.version_no ?? 0),
            product_public_id: String(
              detail.product_public_id ?? this.currentIssue?.product_public_id ?? '',
            ),
            phenomenon_summary: String(
              detail.phenomenon_summary ?? this.currentIssue?.phenomenon_summary ?? '',
            ),
            linked_opportunity_id: detail.linked_opportunity_id ?? null,
            linked_project_id: detail.linked_project_id ?? null,
            linked_product_version_id: detail.linked_product_version_id ?? null,
          }
        }
        return this.lastDecision
      } catch (err) {
        if (isConflict(err)) {
          this.conflictHint = '议题版本已变更，请刷新后比较再提交。'
          await this.fetchIssue(publicId)
        }
        throw err
      } finally {
        this.loading = false
      }
    },

    async convertIssueToIteration(
      publicId: string,
      payload: OperatingIssueIterationProposalRequest,
    ): Promise<OperatingIssue> {
      this.loading = true
      this.clearConflictHint()
      try {
        const issue = await apiFetch<OperatingIssue>(
          `/api/v1/operating-issues/${publicId}/iteration-proposal`,
          { method: 'POST', json: payload },
        )
        this.currentIssue = issue
        this.currentIssueDetail = {
          ...(this.currentIssueDetail ?? { public_id: issue.public_id }),
          ...issue,
        }
        return issue
      } catch (err) {
        if (isConflict(err)) {
          this.conflictHint = '议题状态已变更，请刷新后比较再提交。'
          await this.fetchIssue(publicId)
        }
        throw err
      } finally {
        this.loading = false
      }
    },

    async createRetirementPlan(payload: RetirementPlanCreateRequest): Promise<RetirementPlan> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.retirementPlan = await apiFetch<RetirementPlan>('/api/v1/retirement-plans', {
          method: 'POST',
          json: payload,
        })
        return this.retirementPlan
      } finally {
        this.loading = false
      }
    },

    bindRetirementPlanPublicId(publicId: string): void {
      if (this.retirementPlan?.public_id === publicId) return
      this.retirementPlan = {
        public_id: publicId,
        status: this.retirementPlan?.status ?? 'UNKNOWN',
        product_public_id: this.retirementPlan?.product_public_id ?? '',
        issue_public_id: this.retirementPlan?.issue_public_id ?? '',
        stage_gate_public_id: this.retirementPlan?.stage_gate_public_id ?? null,
        content_hash: this.retirementPlan?.content_hash ?? '',
      }
    },

    async validateRetirementPlan(publicId: string): Promise<RetirementPlanValidateResponse> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.retirementValidation = await apiFetch<RetirementPlanValidateResponse>(
          `/api/v1/retirement-plans/${publicId}/validate`,
          { method: 'POST' },
        )
        return this.retirementValidation
      } finally {
        this.loading = false
      }
    },

    async submitRetirementPlan(
      publicId: string,
      payload: RetirementPlanSubmitRequest,
    ): Promise<RetirementPlanSubmitResponse> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.retirementSubmit = await apiFetch<RetirementPlanSubmitResponse>(
          `/api/v1/retirement-plans/${publicId}/submit`,
          { method: 'POST', json: payload },
        )
        return this.retirementSubmit
      } catch (err) {
        if (isConflict(err)) {
          this.conflictHint = '退市计划已变更，请刷新后比较再提交。'
        }
        throw err
      } finally {
        this.loading = false
      }
    },

    async recordRetirementManagementConclusion(
      stageGatePublicId: string,
      payload: RetirementManagementRequest,
    ): Promise<Record<string, unknown>> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.lastGateDecision = await apiFetch<Record<string, unknown>>(
          `/api/v1/stage-gates/${stageGatePublicId}/retirement-management-conclusion`,
          { method: 'POST', json: payload },
        )
        return this.lastGateDecision
      } finally {
        this.loading = false
      }
    },

    async recordRetirementFinalDecision(
      stageGatePublicId: string,
      payload: RetirementFinalRequest,
    ): Promise<Record<string, unknown>> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.lastGateDecision = await apiFetch<Record<string, unknown>>(
          `/api/v1/stage-gates/${stageGatePublicId}/retirement-final-decision`,
          { method: 'POST', json: payload },
        )
        return this.lastGateDecision
      } finally {
        this.loading = false
      }
    },

    async executeRetirementPlan(
      publicId: string,
      payload: RetirementPlanExecuteRequest = {},
    ): Promise<RetirementPlan> {
      this.loading = true
      this.clearConflictHint()
      try {
        this.retirementPlan = await apiFetch<RetirementPlan>(
          `/api/v1/retirement-plans/${publicId}/execute`,
          { method: 'POST', json: payload },
        )
        return this.retirementPlan
      } catch (err) {
        if (isConflict(err)) {
          this.conflictHint = '退市执行状态已变更，请刷新后比较再重试。'
        }
        throw err
      } finally {
        this.loading = false
      }
    },
  },
})
