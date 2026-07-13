import { defineStore } from 'pinia'

import { apiFetch } from '@/api/client'
import type { components } from '@/api/generated/schema'

export type ProductSummary = components['schemas']['ProductSummary']
export type ProductDetail = components['schemas']['ProductDetail'] & {
  external_bindings?: ExternalBinding[]
  versions?: Array<{
    public_id: string
    version_code: string
    version_name: string
    status: string
    skus: Array<{
      public_id: string
      sku_code: string
      name: string
      specification: string
      barcode?: string
      channels?: Array<{ channel_code: string; channel_status: string }>
    }>
  }>
}
export type ProductChangeSetDetail = components['schemas']['ProductChangeSetDetail'] & {
  attribute_groups?: AttributeGroup[]
  change_scope?: {
    effective_from?: string
    skus?: Array<Record<string, unknown>>
    channels?: Array<Record<string, unknown>>
    scopes?: Array<Record<string, unknown>>
  }
}
export type PublicationValidation = components['schemas']['PublicationValidation']
export type ImportBatchDetail = components['schemas']['ImportBatchDetail']
export type ConfirmImportBatchResponse = components['schemas']['ConfirmImportBatchResponse']

export type ExternalBinding = {
  public_id: string
  source_system: string
  object_type: string
  external_id: string
  binding_status: string
}

export type AttributeGroup = {
  public_id: string
  group_code: string
  group_name: string
  requires_confirmation: boolean
  content_hash: string
  values_json: Record<string, unknown>
  confirmation_status: string
  assigned_confirmer_public_id?: string | null
}

export type PublishLegacyBaselineResponse = {
  change_set_public_id: string
  product_version_public_id: string
  product_public_id: string
  product_name: string
  product_lifecycle_status: string
}

export type ProductSearchPage = {
  items: ProductSummary[]
  page: number
  page_size: number
  count: number
}

export type ChangeSetDiff = {
  change_set_public_id: string
  changed_fields: Array<{
    group_code: string
    field_code: string
    field_name: string
    old_value: unknown
    new_value: unknown
  }>
}

export const useProductStore = defineStore('products', {
  state: () => ({
    loading: false,
    search: '',
    items: [] as ProductSummary[],
    page: 1,
    pageSize: 20,
    totalCount: 0,
    detail: null as ProductDetail | null,
    changeSet: null as ProductChangeSetDetail | null,
    changeSetDiff: null as ChangeSetDiff | null,
    publicationValidation: null as PublicationValidation | null,
    importBatch: null as ImportBatchDetail | null,
    confirmResult: null as ConfirmImportBatchResponse | null,
  }),
  actions: {
    async fetchProducts(
      search = '',
      filters: {
        brand_code?: string
        category_code?: string
        lifecycle_status?: string
        owner_public_id?: string
        sku_code?: string
        external_id?: string
        channel_code?: string
        page?: number
        page_size?: number
      } = {},
    ): Promise<void> {
      this.loading = true
      try {
        const params = new URLSearchParams()
        if (search) params.set('search', search)
        const page = filters.page ?? this.page
        const pageSize = filters.page_size ?? this.pageSize
        params.set('page', String(page))
        params.set('page_size', String(pageSize))
        for (const [key, value] of Object.entries(filters)) {
          if (key === 'page' || key === 'page_size') continue
          if (value) params.set(key, String(value))
        }
        const query = params.toString() ? `?${params.toString()}` : ''
        const result = await apiFetch<ProductSearchPage>(`/api/v1/products${query}`)
        this.items = result.items
        this.page = result.page
        this.pageSize = result.page_size
        this.totalCount = result.count
        this.search = search
      } finally {
        this.loading = false
      }
    },
    async fetchProductDetail(publicId: string): Promise<void> {
      this.loading = true
      try {
        this.detail = await apiFetch<ProductDetail>(`/api/v1/products/${publicId}`)
      } finally {
        this.loading = false
      }
    },
    async createChangeSet(
      productPublicId: string,
      payload: { change_type: string; title?: string; base_version_public_id?: string },
    ): Promise<ProductChangeSetDetail> {
      const changeSet = await apiFetch<ProductChangeSetDetail>(
        `/api/v1/products/${productPublicId}/change-sets`,
        { method: 'POST', json: payload },
      )
      this.changeSet = changeSet
      return changeSet
    },
    async fetchChangeSet(publicId: string): Promise<void> {
      this.loading = true
      try {
        this.changeSet = await apiFetch<ProductChangeSetDetail>(
          `/api/v1/product-change-sets/${publicId}`,
        )
      } finally {
        this.loading = false
      }
    },
    async fetchChangeSetDiff(publicId: string): Promise<ChangeSetDiff> {
      const diff = await apiFetch<ChangeSetDiff>(`/api/v1/product-change-sets/${publicId}/diff`)
      this.changeSetDiff = diff
      return diff
    },
    async editAttributeGroup(
      changeSetPublicId: string,
      payload: { version_no: number; group_code: string; values: Record<string, unknown> },
    ): Promise<void> {
      this.changeSet = await apiFetch<ProductChangeSetDetail>(
        `/api/v1/product-change-sets/${changeSetPublicId}/edit-group`,
        { method: 'POST', json: payload },
      )
    },
    async approveAttributeGroup(
      changeSetPublicId: string,
      payload: { group_value_public_id: string; content_hash: string; comment?: string },
    ): Promise<void> {
      this.changeSet = await apiFetch<ProductChangeSetDetail>(
        `/api/v1/product-change-sets/${changeSetPublicId}/approve-attribute-group`,
        { method: 'POST', json: payload },
      )
    },
    async returnAttributeGroup(
      changeSetPublicId: string,
      payload: { group_value_public_id: string; content_hash: string; comment?: string },
    ): Promise<void> {
      this.changeSet = await apiFetch<ProductChangeSetDetail>(
        `/api/v1/product-change-sets/${changeSetPublicId}/return-attribute-group`,
        { method: 'POST', json: payload },
      )
    },
    async reassignConfirmer(
      changeSetPublicId: string,
      payload: { group_value_public_id: string; confirmer_public_id: string; reason?: string },
    ): Promise<void> {
      this.changeSet = await apiFetch<ProductChangeSetDetail>(
        `/api/v1/product-change-sets/${changeSetPublicId}/reassign-confirmer`,
        { method: 'POST', json: payload },
      )
    },
    async submitChangeSet(changeSetPublicId: string): Promise<void> {
      this.changeSet = await apiFetch<ProductChangeSetDetail>(
        `/api/v1/product-change-sets/${changeSetPublicId}/submit-confirmation`,
        { method: 'POST' },
      )
    },
    async approveChangeSet(changeSetPublicId: string): Promise<void> {
      this.changeSet = await apiFetch<ProductChangeSetDetail>(
        `/api/v1/product-change-sets/${changeSetPublicId}/approve`,
        { method: 'POST' },
      )
    },
    async updateChangeSetScope(
      changeSetPublicId: string,
      payload: {
        version_no: number
        skus?: unknown[]
        channels?: unknown[]
        scopes?: unknown[]
        effective_from?: string
      },
    ): Promise<void> {
      this.changeSet = await apiFetch<ProductChangeSetDetail>(
        `/api/v1/product-change-sets/${changeSetPublicId}/update-scope`,
        { method: 'POST', json: payload },
      )
    },
    async validatePublication(changeSetPublicId: string): Promise<PublicationValidation> {
      const result = await apiFetch<PublicationValidation>(
        `/api/v1/product-change-sets/${changeSetPublicId}/validate-publication`,
        { method: 'POST' },
      )
      this.publicationValidation = result
      return result
    },
    async publishChangeSet(changeSetPublicId: string, idempotencyKey: string): Promise<void> {
      await apiFetch(`/api/v1/product-change-sets/${changeSetPublicId}/publish`, {
        method: 'POST',
        json: { idempotency_key: idempotencyKey },
      })
    },
    async upsertExternalBinding(
      productPublicId: string,
      payload: { source_system: string; object_type: string; external_id: string },
    ): Promise<ExternalBinding> {
      const binding = await apiFetch<ExternalBinding>(
        `/api/v1/products/${productPublicId}/external-bindings`,
        { method: 'POST', json: payload },
      )
      if (this.detail?.public_id === productPublicId) {
        await this.fetchProductDetail(productPublicId)
      }
      return binding
    },
    async createImportBatch(
      csvContent: string,
      sourceFilename: string,
    ): Promise<ImportBatchDetail> {
      this.loading = true
      try {
        this.importBatch = await apiFetch<ImportBatchDetail>('/api/v1/product-import-batches', {
          method: 'POST',
          json: { csv_content: csvContent, source_filename: sourceFilename },
        })
        return this.importBatch
      } finally {
        this.loading = false
      }
    },
    async createImportBatchFromFile(file: File): Promise<ImportBatchDetail> {
      this.loading = true
      try {
        const body = new FormData()
        body.append('file', file)
        this.importBatch = await apiFetch<ImportBatchDetail>('/api/v1/product-import-batches', {
          method: 'POST',
          body,
        })
        return this.importBatch
      } finally {
        this.loading = false
      }
    },
    async downloadImportTemplate(): Promise<void> {
      const response = await fetch('/api/v1/product-import-template', {
        credentials: 'include',
      })
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`)
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'legacy-product-import.xlsx'
      anchor.click()
      URL.revokeObjectURL(url)
    },
    async decideImportItem(
      batchPublicId: string,
      payload: { row_number: number; decision: string; target_product_public_id?: string },
    ): Promise<void> {
      await apiFetch(`/api/v1/product-import-batches/${batchPublicId}/decide-item`, {
        method: 'POST',
        json: payload,
      })
      this.importBatch = await apiFetch<ImportBatchDetail>(
        `/api/v1/product-import-batches/${batchPublicId}`,
      )
    },
    async confirmImportBatch(batchPublicId: string, idempotencyKey: string): Promise<void> {
      this.confirmResult = await apiFetch<ConfirmImportBatchResponse>(
        `/api/v1/product-import-batches/${batchPublicId}/confirm`,
        {
          method: 'POST',
          json: { idempotency_key: idempotencyKey },
        },
      )
    },
    async publishLegacyBaseline(
      baselinePublicId: string,
      idempotencyKey: string,
    ): Promise<PublishLegacyBaselineResponse> {
      return apiFetch<PublishLegacyBaselineResponse>(
        `/api/v1/legacy-baselines/${baselinePublicId}/publish`,
        {
          method: 'POST',
          json: { idempotency_key: idempotencyKey },
        },
      )
    },
  },
})
