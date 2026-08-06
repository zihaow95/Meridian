<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError } from '@/api/client'
import { usePilotStore } from '@/modules/pilot/store'

const pilot = usePilotStore()
const errorText = ref('')
const batchName = ref('内部验收批次')
const selectedId = ref('')
const feedbackTitle = ref('')
const feedbackSummary = ref('')

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await pilot.fetchBatches()
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载试用批次失败'
    }
  }
}

async function createBatch(): Promise<void> {
  errorText.value = ''
  try {
    const batch = await pilot.createBatch({ name: batchName.value.trim() })
    selectedId.value = batch.public_id
    await pilot.loadBatch(batch.public_id)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '创建批次失败'
    }
  }
}

async function selectBatch(publicId: string): Promise<void> {
  selectedId.value = publicId
  errorText.value = ''
  try {
    await pilot.loadBatch(publicId)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载批次详情失败'
    }
  }
}

async function submitFeedback(): Promise<void> {
  if (!selectedId.value) return
  errorText.value = ''
  try {
    await pilot.openFeedback(selectedId.value, feedbackTitle.value, feedbackSummary.value)
    feedbackTitle.value = ''
    feedbackSummary.value = ''
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '提交反馈失败'
    }
  }
}

onMounted(load)
</script>

<template>
  <div class="pilot" data-test="pilot-batch-view">
    <header class="pilot__header">
      <h1>试用批次（非生产内部验收）</h1>
      <p>阶段6仅验证软件反馈闭环，不代表真实业务试用完成。</p>
    </header>

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="pilot__error"
    />

    <section class="pilot__create">
      <el-input v-model="batchName" placeholder="批次名称" data-test="pilot-batch-name" />
      <el-button type="primary" data-test="pilot-batch-create" @click="createBatch">
        创建内部验收批次
      </el-button>
    </section>

    <section class="pilot__list">
      <h2>批次列表</h2>
      <ul>
        <li v-for="batch in pilot.batches" :key="batch.public_id">
          <button type="button" @click="selectBatch(batch.public_id)">
            {{ batch.name }} · {{ batch.status }}
          </button>
        </li>
      </ul>
    </section>

    <section v-if="pilot.selected" class="pilot__detail" data-test="pilot-batch-detail">
      <h2>{{ pilot.selected.name }}</h2>
      <p>
        状态：{{ pilot.selected.status }} · 计划人数 {{ pilot.selected.planned_participant_count }}
      </p>

      <h3>反馈</h3>
      <ul data-test="pilot-feedback-list">
        <li v-for="item in pilot.feedback" :key="item.public_id">
          {{ item.title }} · {{ item.severity || '未分级' }} · {{ item.status }}
        </li>
      </ul>

      <div class="pilot__feedback-form">
        <el-input v-model="feedbackTitle" placeholder="标题" data-test="pilot-feedback-title" />
        <el-input
          v-model="feedbackSummary"
          type="textarea"
          placeholder="复现摘要（勿粘贴敏感产品正文）"
          data-test="pilot-feedback-summary"
        />
        <el-button data-test="pilot-feedback-submit" @click="submitFeedback">提交反馈</el-button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pilot {
  display: grid;
  gap: 1.25rem;
  padding: 1rem;
}

.pilot__header h1 {
  margin: 0 0 0.35rem;
  font-size: 1.35rem;
}

.pilot__header p,
.pilot__detail p {
  margin: 0;
  color: #555;
}

.pilot__create,
.pilot__feedback-form {
  display: grid;
  gap: 0.75rem;
  max-width: 36rem;
}

.pilot__list ul,
.pilot__detail ul {
  padding-left: 1.1rem;
}

.pilot__list button {
  background: none;
  border: none;
  color: #1a5fb4;
  cursor: pointer;
  padding: 0.15rem 0;
  text-align: left;
}
</style>
