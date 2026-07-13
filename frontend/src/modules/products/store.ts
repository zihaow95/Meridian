import { defineStore } from 'pinia'

import { apiFetch } from '@/api/client'
import type { components } from '@/api/generated/schema'

export type ProductSummary = components['schemas']['ProductSummary']
export type ProductDetail = components['schemas']['ProductDetail'] & {
  external_bindings?: ExternalBinding[]
}
export type ProductChangeSetDetail = components['schemas']['ProductChangeSetDetail']
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

export const useProductStore = defineStore('products', {
  state: () => ({
    loading: false,
    search: '',
    items: [] as ProductSummary[],
    detail: null as ProductDetail | null,
    changeSet: null as ProductChangeSetDetail | null,
    publicationValidation: null as PublicationValidation | null,
    importBatch: null as ImportBatchDetail | null,
    confirmResult: null as ConfirmImportBatchResponse | null,
  }),
  actions: {
    async fetchProducts(search = ''): Promise<void> {
      this.loading = true
      try {
        const query = search ? `?search=${encodeURIComponent(search)}` : ''
        const page = await apiFetch<{ items: ProductSummary[] }>(`/api/v1/products${query}`)
        this.items = page.items
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
    async publishLegacyBaseline(baselinePublicId: string, idempotencyKey: string): Promise<void> {
      await apiFetch(`/api/v1/legacy-baselines/${baselinePublicId}/publish`, {
        method: 'POST',
        json: { idempotency_key: idempotencyKey },
      })
    },
  },
})
