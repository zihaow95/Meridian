<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, apiFetch } from '@/api/client'

type ConfigurationDefinition = {
  definition_code: string
  name: string
  description: string
}

type ConfigurationVersionSummary = {
  public_id: string
  version_number: number
  status: string
  published_at: string | null
}

type ConfigurationVersionDetail = {
  public_id: string
  definition_code: string
  version_number: number
  status: string
  content_digest: string
  content_json: Record<string, unknown> | null
  validation_errors: string[]
  diff_summary: Record<string, unknown>
}

type PublicationRequest = {
  public_id: string
  definition_code: string
  version_public_id: string
  version_number: number
  proposed_by: string
  status: string
  expires_at: string
}

const definitions = ref<ConfigurationDefinition[]>([])
const versions = ref<ConfigurationVersionSummary[]>([])
const pendingRequests = ref<PublicationRequest[]>([])
const selectedDefinition = ref('')
const selectedVersion = ref<ConfigurationVersionDetail | null>(null)

const loading = ref(false)
const submitting = ref(false)
const reviewing = ref('')
const errorText = ref('')
const conflictText = ref('')

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    return `${err.code}: ${err.message} (trace ${err.traceId})`
  }
  return fallback
}

async function loadDefinitions(): Promise<void> {
  loading.value = true
  errorText.value = ''
  try {
    definitions.value = await apiFetch<ConfigurationDefinition[]>(
      '/api/v1/configurations/definitions',
    )
  } catch (err: unknown) {
    definitions.value = []
    errorText.value = describe(err, '加载配置定义失败')
  } finally {
    loading.value = false
  }
}

async function loadPendingRequests(): Promise<void> {
  try {
    pendingRequests.value = await apiFetch<PublicationRequest[]>(
      '/api/v1/configurations/publication-requests',
    )
  } catch {
    // A reader without review scope simply sees no queue.
    pendingRequests.value = []
  }
}

async function selectDefinition(definitionCode: string): Promise<void> {
  selectedDefinition.value = definitionCode
  selectedVersion.value = null
  errorText.value = ''
  try {
    versions.value = await apiFetch<ConfigurationVersionSummary[]>(
      `/api/v1/configurations/definitions/${definitionCode}/versions`,
    )
  } catch (err: unknown) {
    versions.value = []
    errorText.value = describe(err, '加载配置版本失败')
  }
}

async function selectVersion(publicId: string): Promise<void> {
  errorText.value = ''
  try {
    selectedVersion.value = await apiFetch<ConfigurationVersionDetail>(
      `/api/v1/configurations/versions/${publicId}`,
    )
  } catch (err: unknown) {
    selectedVersion.value = null
    errorText.value = describe(err, '加载配置版本详情失败')
  }
}

async function requestPublication(): Promise<void> {
  const version = selectedVersion.value
  if (version === null || submitting.value) return

  submitting.value = true
  conflictText.value = ''
  try {
    await apiFetch(`/api/v1/configurations/versions/${version.public_id}/publication-requests`, {
      method: 'POST',
    })
    await loadPendingRequests()
  } catch (err: unknown) {
    if (err instanceof ApiError && err.status === 409) {
      conflictText.value = `${err.message}，请刷新后比较最新版本再提交（trace ${err.traceId}）`
    } else {
      errorText.value = describe(err, '提交发布申请失败')
    }
  } finally {
    submitting.value = false
  }
}

async function review(requestPublicId: string, decision: 'APPROVED' | 'REJECTED'): Promise<void> {
  if (reviewing.value !== '') return

  reviewing.value = requestPublicId
  conflictText.value = ''
  try {
    await apiFetch(`/api/v1/configurations/publication-requests/${requestPublicId}/review`, {
      method: 'POST',
      json: { decision },
    })
    await loadPendingRequests()
  } catch (err: unknown) {
    if (err instanceof ApiError && err.status === 409) {
      conflictText.value = `${err.message}，请刷新后比较该申请的最新状态（trace ${err.traceId}）`
    } else {
      errorText.value = describe(err, '复核发布申请失败')
    }
  } finally {
    reviewing.value = ''
  }
}

async function load(): Promise<void> {
  await loadDefinitions()
  await loadPendingRequests()
}

onMounted(load)
</script>

<template>
  <div class="config">
    <div class="config__header">
      <h2>配置发布管理</h2>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="config__error"
    />

    <el-alert
      v-if="conflictText"
      data-test="conflict-notice"
      type="warning"
      :closable="false"
      :title="conflictText"
      show-icon
      class="config__error"
    />

    <el-empty
      v-if="!errorText && !loading && definitions.length === 0"
      description="暂无配置定义"
    />

    <el-table v-else-if="!errorText" :data="definitions" style="width: 100%">
      <el-table-column prop="definition_code" label="配置编码" width="240" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="description" label="描述" />
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button data-test="select-definition" @click="selectDefinition(row.definition_code)">
            查看版本
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <section v-if="selectedDefinition" class="config__section">
      <h3>{{ selectedDefinition }} 的版本</h3>
      <el-table :data="versions" style="width: 100%">
        <el-table-column prop="version_number" label="版本" width="100" />
        <el-table-column prop="status" label="状态" width="140" />
        <el-table-column prop="published_at" label="发布时间" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button data-test="select-version" @click="selectVersion(row.public_id)">
              查看详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="selectedVersion" data-test="version-detail" class="config__section">
      <h3>版本 {{ selectedVersion.version_number }}（{{ selectedVersion.status }}）</h3>
      <p>内容摘要：{{ selectedVersion.content_digest }}</p>
      <p data-test="diff-summary">差异：{{ JSON.stringify(selectedVersion.diff_summary) }}</p>

      <el-alert
        v-if="selectedVersion.validation_errors.length > 0"
        data-test="validation-errors"
        type="error"
        :closable="false"
        :title="selectedVersion.validation_errors.join('；')"
        show-icon
      />

      <p v-if="selectedVersion.content_json === null" data-test="content-withheld">
        当前账号无权查看该配置正文，仅显示摘要与状态。
      </p>
      <pre v-else data-test="content-json">{{
        JSON.stringify(selectedVersion.content_json, null, 2)
      }}</pre>

      <el-button
        data-test="request-publication"
        type="primary"
        :disabled="submitting"
        @click="requestPublication"
      >
        提交发布申请
      </el-button>
    </section>

    <section data-test="pending-requests" class="config__section">
      <h3>待复核的发布申请</h3>
      <el-empty v-if="pendingRequests.length === 0" description="暂无待复核申请" />
      <el-table v-else :data="pendingRequests" style="width: 100%">
        <el-table-column prop="public_id" label="申请编号" width="240" />
        <el-table-column prop="definition_code" label="配置编码" />
        <el-table-column prop="version_number" label="版本" width="100" />
        <el-table-column prop="expires_at" label="失效时间" />
        <el-table-column label="复核" width="200">
          <template #default="{ row }">
            <el-button
              data-test="approve-request"
              type="primary"
              :disabled="reviewing !== ''"
              @click="review(row.public_id, 'APPROVED')"
            >
              批准
            </el-button>
            <el-button
              data-test="reject-request"
              :disabled="reviewing !== ''"
              @click="review(row.public_id, 'REJECTED')"
            >
              驳回
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.config__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.config__error {
  margin-bottom: 1rem;
}

.config__section {
  margin-top: 1.5rem;
}
</style>
