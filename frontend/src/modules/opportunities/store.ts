import { defineStore } from 'pinia'

import { apiFetch } from '@/api/client'

export type ProposalVersion = {
  public_id: string
  version_number: number
  version_status: string
  market_analysis: string
  core_selling_points: string
  target_users_needs: string
  suggested_retail_price: string | null
  submitted_at: string | null
  locked_at: string | null
}

export type OpportunitySummary = {
  public_id: string
  business_no: string
  title: string
  public_summary: string
  initial_type: string
  proposal_status: string
  version_no: number
  updated_at: string
}

export type OpportunityDetail = OpportunitySummary & {
  quota_owner_type: string
  current_version: ProposalVersion | null
}

export type StageGateSummary = {
  public_id: string
  stage_code: string
  cycle_number: number
  status: string
  subject_type: string
  subject_public_id: string
}

export type MajorGateDecisionResult = {
  public_id: string
  stage_gate_public_id: string
  management_conclusion: string
  final_decision: string
  has_conclusion_difference: boolean
  decision_summary: string
}

export type CreateOpportunityPayload = {
  title: string
  initial_type?: string
  public_summary?: string
  market_analysis?: string
  core_selling_points?: string
  target_users_needs?: string
  suggested_retail_price?: string
}

export type LifecycleBoardItem = {
  item_type: 'OPPORTUNITY' | 'PROJECT'
  public_id: string
  business_no: string
  title: string
  lifecycle_stage: string
  status: string
  owner_public_id: string
  owner_display_name: string
  candidate_public_id: string | null
  updated_at: string
}

export type LifecycleBoardPage = {
  items: LifecycleBoardItem[]
  page: number
  page_size: number
  total_count: number
  has_more: boolean
}

export type ProposalQuota = {
  quarter: string
  owner_type: string
  owner_public_id: string
  counted_submissions: number
  minimum_count: number
  enforcement_mode: string
  is_below_minimum: boolean
  deficit: number
}

export const useOpportunityStore = defineStore('opportunities', {
  state: () => ({
    items: [] as OpportunitySummary[],
    poolItems: [] as OpportunitySummary[],
    lifecycleBoard: [] as LifecycleBoardItem[],
    current: null as OpportunityDetail | null,
    versions: [] as ProposalVersion[],
    activeStageGate: null as StageGateSummary | null,
    lastDecision: null as MajorGateDecisionResult | null,
    loading: false,
    lastError: null as Error | null,
  }),
  getters: {
    drafts: (state) =>
      state.items.filter((item) => ['DRAFT', 'NEEDS_INFO'].includes(item.proposal_status)),
    ownedActive: (state) =>
      state.items.filter((item) =>
        ['SUBMITTED', 'IN_REVIEW', 'CASE_APPROVED'].includes(item.proposal_status),
      ),
  },
  actions: {
    async fetchMyOpportunities(): Promise<void> {
      this.loading = true
      this.lastError = null
      try {
        this.items = await apiFetch<OpportunitySummary[]>('/api/v1/opportunities')
      } catch (err) {
        this.items = []
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
    async fetchOpportunityPool(): Promise<void> {
      this.loading = true
      this.lastError = null
      try {
        this.poolItems = await apiFetch<OpportunitySummary[]>('/api/v1/opportunity-pool')
      } catch (err) {
        this.poolItems = []
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
    async fetchCurrentQuota(): Promise<ProposalQuota> {
      return apiFetch<ProposalQuota>('/api/v1/proposal-quotas/current')
    },
    async fetchLifecycleBoard(filters?: {
      lifecycle_stage?: string
      status?: string
      owner?: string
      page?: number
      page_size?: number
    }): Promise<LifecycleBoardPage> {
      this.loading = true
      this.lastError = null
      const params = new URLSearchParams()
      if (filters?.lifecycle_stage) params.set('lifecycle_stage', filters.lifecycle_stage)
      if (filters?.status) params.set('status', filters.status)
      if (filters?.owner) params.set('owner', filters.owner)
      if (filters?.page) params.set('page', String(filters.page))
      if (filters?.page_size) params.set('page_size', String(filters.page_size))
      const query = params.toString()
      const path = query ? `/api/v1/lifecycle-board?${query}` : '/api/v1/lifecycle-board'
      try {
        const page = await apiFetch<LifecycleBoardPage>(path)
        this.lifecycleBoard = page.items
        return page
      } catch (err) {
        this.lifecycleBoard = []
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
    async fetchDetail(publicId: string): Promise<OpportunityDetail> {
      this.loading = true
      this.lastError = null
      try {
        const detail = await apiFetch<OpportunityDetail>(`/api/v1/opportunities/${publicId}`)
        this.current = detail
        return detail
      } catch (err) {
        this.current = null
        this.lastError = err as Error
        throw err
      } finally {
        this.loading = false
      }
    },
    async fetchVersions(publicId: string): Promise<void> {
      this.versions = await apiFetch<ProposalVersion[]>(
        `/api/v1/opportunities/${publicId}/versions`,
      )
    },
    async createOpportunity(payload: CreateOpportunityPayload): Promise<OpportunityDetail> {
      const detail = await apiFetch<OpportunityDetail>('/api/v1/opportunities', {
        method: 'POST',
        json: payload,
      })
      this.current = detail
      return detail
    },
    async updateOpportunity(
      publicId: string,
      payload: Partial<CreateOpportunityPayload>,
    ): Promise<OpportunityDetail> {
      const detail = await apiFetch<OpportunityDetail>(`/api/v1/opportunities/${publicId}`, {
        method: 'PATCH',
        json: payload,
      })
      this.current = detail
      return detail
    },
    async submitOpportunity(
      publicId: string,
      versionNo: number,
      idempotencyKey: string,
    ): Promise<OpportunitySummary> {
      return apiFetch<OpportunitySummary>(`/api/v1/opportunities/${publicId}/submit`, {
        method: 'POST',
        json: { version_no: versionNo, idempotency_key: idempotencyKey },
      })
    },
    async withdrawOpportunity(publicId: string, versionNo: number): Promise<OpportunitySummary> {
      return apiFetch<OpportunitySummary>(`/api/v1/opportunities/${publicId}/withdraw`, {
        method: 'POST',
        json: { version_no: versionNo },
      })
    },
    async openProposalReviewCycle(publicId: string): Promise<StageGateSummary> {
      const gate = await apiFetch<StageGateSummary>(
        `/api/v1/opportunities/${publicId}/review-cycles`,
        { method: 'POST', json: {} },
      )
      this.activeStageGate = gate
      return gate
    },
    async recordMajorDecision(
      stageGatePublicId: string,
      payload: {
        management_conclusion: string
        final_decision: string
        decision_summary: string
        idempotency_key: string
        defer_reason?: string
        restart_trigger?: string
        next_review_quarter?: string
      },
    ): Promise<MajorGateDecisionResult> {
      const decision = await apiFetch<MajorGateDecisionResult>(
        `/api/v1/stage-gates/${stageGatePublicId}/major-decision`,
        { method: 'POST', json: payload },
      )
      this.lastDecision = decision
      return decision
    },
  },
})
