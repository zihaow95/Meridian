<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import { useAuthStore } from '@/modules/auth/store'
import DeliverablePanel from '@/modules/projects/DeliverablePanel.vue'
import StageGatePanel from '@/modules/projects/StageGatePanel.vue'
import TaskPanel from '@/modules/projects/TaskPanel.vue'
import { useProjectStore } from '@/modules/projects/store'

const route = useRoute()
const auth = useAuthStore()
const projects = useProjectStore()

const errorText = ref('')
const activeTab = ref('overview')

const publicId = computed(() => String(route.params.publicId))
const detail = computed(() => projects.detail)
const launchMode = computed(() => route.path.endsWith('/launch-gate'))
const actorPublicId = computed(() => auth.me?.public_id ?? '')
const currentStage = computed(() =>
  projects.stages.find((stage) => stage.stage_code === detail.value?.current_stage_code),
)
const stageGatePublicId = computed(() => currentStage.value?.public_id ?? '')

async function load(): Promise<void> {
  errorText.value = ''
  try {
    await projects.refreshWorkbench(publicId.value)
    if (launchMode.value) {
      activeTab.value = 'gate'
    }
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message} (trace ${err.traceId})`
    } else {
      errorText.value = '加载项目工作台失败'
    }
  }
}

onMounted(async () => {
  if (!auth.me) {
    try {
      await auth.fetchMe()
    } catch {
      // Router guard handles unauthenticated users.
    }
  }
  await load()
})
</script>

<template>
  <div class="workbench" data-test="project-workbench">
    <div class="workbench__header">
      <div>
        <h2>{{ detail?.name ?? '项目工作台' }}</h2>
        <p v-if="detail" class="workbench__meta">
          {{ detail.business_no }} · {{ detail.status }}
          <span v-if="detail.current_stage_code"> · {{ detail.current_stage_code }}</span>
        </p>
      </div>
      <el-button :loading="projects.loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="detail?.status === 'PUBLISH_PENDING_REPAIR'"
      type="warning"
      :closable="false"
      title="项目处于 PUBLISH_PENDING_REPAIR：首次上市产品发布未完成，请修复后重试。"
      show-icon
      class="workbench__banner"
    />

    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="workbench__banner"
    />

    <StageGatePanel
      v-if="launchMode && stageGatePublicId"
      :stage-gate-public-id="stageGatePublicId"
      launch-mode
      @completed="load"
    />

    <el-tabs v-else v-model="activeTab" class="workbench__tabs">
      <el-tab-pane label="概览" name="overview">
        <dl v-if="detail" class="workbench__overview">
          <div><dt>类型</dt><dd>{{ detail.project_type }}</dd></div>
          <div><dt>组长</dt><dd>{{ detail.leader_public_id }}</dd></div>
          <div v-if="detail.product_draft_public_id">
            <dt>产品草稿</dt><dd>{{ detail.product_draft_public_id }}</dd>
          </div>
        </dl>
      </el-tab-pane>

      <el-tab-pane label="阶段" name="stages">
        <ul class="workbench__list">
          <li v-for="stage in projects.stages" :key="stage.public_id">
            {{ stage.stage_code }} · {{ stage.name }} · {{ stage.status }}
          </li>
        </ul>
      </el-tab-pane>

      <el-tab-pane label="任务" name="tasks">
        <TaskPanel
          :project-public-id="publicId"
          :leader-public-id="detail?.leader_public_id ?? ''"
          :deputy-leader-public-id="detail?.deputy_leader_public_id ?? ''"
          :actor-public-id="actorPublicId"
          @changed="load"
        />
      </el-tab-pane>

      <el-tab-pane label="交付物" name="deliverables">
        <DeliverablePanel :project-public-id="publicId" @changed="load" />
      </el-tab-pane>

      <el-tab-pane label="阶段门" name="gate">
        <StageGatePanel
          v-if="stageGatePublicId"
          :stage-gate-public-id="stageGatePublicId"
          :launch-mode="detail?.current_stage_code === 'L2'"
          @completed="load"
        />
        <p v-else>当前阶段暂无阶段门。</p>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.workbench__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.workbench__meta {
  margin: 0.25rem 0 0;
  color: var(--el-text-color-secondary);
}

.workbench__banner {
  margin-bottom: 1rem;
}

.workbench__overview {
  display: grid;
  gap: 0.75rem;
}

.workbench__overview dt {
  font-size: 0.85rem;
  color: var(--el-text-color-secondary);
}

.workbench__overview dd {
  margin: 0.15rem 0 0;
}

.workbench__list {
  margin: 0;
  padding-left: 1.25rem;
}
</style>
