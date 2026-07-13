<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { ApiError } from '@/api/client'
import { useAuthStore } from '@/modules/auth/store'
import ProductPublicationPanel from '@/modules/products/ProductPublicationPanel.vue'
import { useProductStore, type AttributeGroup } from '@/modules/products/store'

const route = useRoute()
const products = useProductStore()
const auth = useAuthStore()
const errorText = ref('')
const statusMessage = ref('')
const effectiveFrom = ref(new Date().toISOString())
const skuCode = ref('SKU-UI-001')
const skuName = ref('SKU')
const skuSpecification = ref('120g')
const skuBarcode = ref('')
const channelCode = ref('TMALL')
const editGroupCode = ref('PRODUCT_DEFINITION')
const editValuesJson = ref('{"core_selling_points":"High protein"}')
const reassignConfirmerId = ref('')

const changeSetPublicId = computed(() => String(route.params.publicId))
const versionNo = computed(() => products.changeSet?.version_no ?? 1)
const attributeGroups = computed(() => products.changeSet?.attribute_groups ?? [])

function hydrateScopeFromChangeSet(): void {
  const scope = products.changeSet?.change_scope
  const skus = Array.isArray(scope?.skus) ? scope.skus : []
  const channels = Array.isArray(scope?.channels) ? scope.channels : []
  const firstSku = skus[0]
  const firstChannel = channels[0]
  if (typeof scope?.effective_from === 'string' && scope.effective_from) {
    effectiveFrom.value = scope.effective_from
  }
  if (firstSku) {
    skuCode.value = String(firstSku.sku_code || skuCode.value)
    skuName.value = String(firstSku.name || products.changeSet?.title || 'SKU')
    skuSpecification.value = String(firstSku.specification || skuSpecification.value)
    skuBarcode.value = String(firstSku.barcode || '')
  } else {
    skuName.value = products.changeSet?.title ?? 'SKU'
    skuCode.value = `SKU-${changeSetPublicId.value.slice(0, 8)}`
  }
  if (firstChannel?.channel_code) {
    channelCode.value = String(firstChannel.channel_code)
  }
}

async function load(): Promise<void> {
  errorText.value = ''
  try {
    if (!auth.me) {
      await auth.fetchMe()
    }
    reassignConfirmerId.value = auth.me?.public_id ?? ''
    await products.fetchChangeSet(changeSetPublicId.value)
    hydrateScopeFromChangeSet()
    await products.fetchChangeSetDiff(changeSetPublicId.value)
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '加载变更集失败'
    }
  }
}

async function saveScope(): Promise<void> {
  errorText.value = ''
  statusMessage.value = ''
  if (!skuBarcode.value.trim()) {
    errorText.value = '条码不能为空'
    return
  }
  try {
    await products.updateChangeSetScope(changeSetPublicId.value, {
      version_no: versionNo.value,
      effective_from: effectiveFrom.value,
      skus: [
        {
          sku_code: skuCode.value,
          name: skuName.value,
          barcode: skuBarcode.value.trim(),
          specification: skuSpecification.value,
        },
      ],
      channels: [
        {
          sku_code: skuCode.value,
          channel_code: channelCode.value,
          channel_status: 'ON_SALE',
        },
      ],
    })
    statusMessage.value = '范围已更新'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '更新范围失败'
    }
  }
}

async function saveAttributeGroup(): Promise<void> {
  errorText.value = ''
  statusMessage.value = ''
  try {
    const values = JSON.parse(editValuesJson.value) as Record<string, unknown>
    await products.editAttributeGroup(changeSetPublicId.value, {
      version_no: versionNo.value,
      group_code: editGroupCode.value,
      values,
    })
    await products.fetchChangeSetDiff(changeSetPublicId.value)
    statusMessage.value = '属性组已保存'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else if (err instanceof SyntaxError) {
      errorText.value = '属性 JSON 格式无效'
    } else {
      errorText.value = '保存属性组失败'
    }
  }
}

async function approveGroup(group: AttributeGroup): Promise<void> {
  errorText.value = ''
  try {
    await products.approveAttributeGroup(changeSetPublicId.value, {
      group_value_public_id: group.public_id,
      content_hash: group.content_hash,
    })
    statusMessage.value = `${group.group_code} 已确认`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '属性确认失败'
    }
  }
}

async function returnGroup(group: AttributeGroup): Promise<void> {
  errorText.value = ''
  try {
    await products.returnAttributeGroup(changeSetPublicId.value, {
      group_value_public_id: group.public_id,
      content_hash: group.content_hash,
      comment: 'Needs revision',
    })
    statusMessage.value = `${group.group_code} 已退回`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '属性退回失败'
    }
  }
}

async function reassignGroup(group: AttributeGroup): Promise<void> {
  errorText.value = ''
  if (!reassignConfirmerId.value.trim()) {
    errorText.value = '请填写确认人 public_id'
    return
  }
  try {
    await products.reassignConfirmer(changeSetPublicId.value, {
      group_value_public_id: group.public_id,
      confirmer_public_id: reassignConfirmerId.value.trim(),
      reason: 'UI reassign',
    })
    statusMessage.value = `${group.group_code} 已改派确认人`
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '改派确认人失败'
    }
  }
}

async function submitForConfirmation(): Promise<void> {
  errorText.value = ''
  try {
    await products.submitChangeSet(changeSetPublicId.value)
    statusMessage.value = '已提交确认'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '提交失败'
    }
  }
}

async function approveChangeSet(): Promise<void> {
  errorText.value = ''
  try {
    await products.approveChangeSet(changeSetPublicId.value)
    await products.validatePublication(changeSetPublicId.value)
    statusMessage.value = '变更集已批准'
  } catch (err: unknown) {
    if (err instanceof ApiError) {
      errorText.value = `${err.code}: ${err.message}`
    } else {
      errorText.value = '批准失败'
    }
  }
}

onMounted(load)
</script>

<template>
  <div class="product-change-set" v-loading="products.loading">
    <el-alert
      v-if="errorText"
      type="error"
      :closable="false"
      :title="errorText"
      show-icon
      class="product-change-set__error"
    />
    <el-alert
      v-if="statusMessage"
      type="success"
      :closable="false"
      :title="statusMessage"
      show-icon
      class="product-change-set__error"
      data-test="change-set-status-message"
    />

    <template v-if="products.changeSet">
      <h2 data-test="change-set-title">{{ products.changeSet.title }}</h2>
      <p class="product-change-set__meta">
        <span data-test="change-set-status">{{ products.changeSet.status }}</span>
        <span>{{ products.changeSet.change_type }}</span>
        <span>v{{ products.changeSet.version_no }}</span>
      </p>

      <el-card class="product-change-set__scope" data-test="attribute-editor">
        <template #header>属性组编辑</template>
        <el-form label-width="120px">
          <el-form-item label="属性组">
            <el-input v-model="editGroupCode" data-test="edit-group-code" />
          </el-form-item>
          <el-form-item label="字段 JSON">
            <el-input
              v-model="editValuesJson"
              type="textarea"
              :rows="3"
              data-test="edit-group-values"
            />
          </el-form-item>
          <el-button data-test="save-attribute-group" type="primary" @click="saveAttributeGroup">
            保存属性组
          </el-button>
        </el-form>

        <el-table
          v-if="attributeGroups.length"
          :data="attributeGroups"
          data-test="attribute-groups"
          class="product-change-set__groups"
        >
          <el-table-column prop="group_code" label="编码" width="180" />
          <el-table-column prop="group_name" label="名称" />
          <el-table-column prop="confirmation_status" label="确认状态" width="140" />
          <el-table-column label="确认人" width="220">
            <template #default="{ row }">
              <span data-test="assigned-confirmer">
                {{ (row as AttributeGroup).assigned_confirmer_public_id || '未分配' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="280">
            <template #default="{ row }">
              <el-button
                size="small"
                data-test="reassign-confirmer"
                @click="reassignGroup(row as AttributeGroup)"
              >
                改派
              </el-button>
              <el-button
                size="small"
                data-test="approve-attribute-group"
                @click="approveGroup(row as AttributeGroup)"
              >
                确认
              </el-button>
              <el-button
                size="small"
                data-test="return-attribute-group"
                @click="returnGroup(row as AttributeGroup)"
              >
                退回
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-form label-width="120px" class="product-change-set__reassign">
          <el-form-item label="确认人 ID">
            <el-input
              v-model="reassignConfirmerId"
              data-test="reassign-confirmer-id"
              placeholder="确认人 public_id"
            />
          </el-form-item>
        </el-form>
      </el-card>

      <el-card class="product-change-set__scope" data-test="change-set-diff">
        <template #header>差异</template>
        <ul v-if="products.changeSetDiff?.changed_fields?.length">
          <li
            v-for="field in products.changeSetDiff.changed_fields"
            :key="`${field.group_code}:${field.field_code}`"
            data-test="diff-field"
          >
            {{ field.group_code }}.{{ field.field_code }}: {{ field.old_value }} →
            {{ field.new_value }}
          </li>
        </ul>
        <p v-else data-test="diff-empty">暂无差异</p>
      </el-card>

      <el-card class="product-change-set__scope" data-test="scope-editor">
        <template #header>范围与生效时间</template>
        <el-form label-width="120px">
          <el-form-item label="生效时间">
            <el-input v-model="effectiveFrom" data-test="effective-from" />
          </el-form-item>
          <el-form-item label="SKU 编码">
            <el-input v-model="skuCode" data-test="scope-sku-code" />
          </el-form-item>
          <el-form-item label="SKU 名称">
            <el-input v-model="skuName" data-test="scope-sku-name" />
          </el-form-item>
          <el-form-item label="规格">
            <el-input v-model="skuSpecification" data-test="scope-sku-specification" />
          </el-form-item>
          <el-form-item label="条码">
            <el-input v-model="skuBarcode" data-test="scope-sku-barcode" />
          </el-form-item>
          <el-form-item label="渠道">
            <el-input v-model="channelCode" data-test="scope-channel-code" />
          </el-form-item>
          <el-button data-test="save-scope" type="primary" @click="saveScope">保存范围</el-button>
        </el-form>
      </el-card>

      <div class="product-change-set__workflow">
        <el-button data-test="submit-confirmation" @click="submitForConfirmation">
          提交确认
        </el-button>
        <el-button data-test="approve-change-set" type="success" @click="approveChangeSet">
          批准变更集
        </el-button>
      </div>

      <ProductPublicationPanel :change-set-public-id="changeSetPublicId" />
    </template>
  </div>
</template>

<style scoped>
.product-change-set__meta {
  display: flex;
  gap: 1rem;
  color: #666;
  margin-bottom: 1rem;
}

.product-change-set__error,
.product-change-set__scope,
.product-change-set__workflow,
.product-change-set__groups,
.product-change-set__reassign {
  margin-bottom: 1rem;
}

.product-change-set__workflow {
  display: flex;
  gap: 0.75rem;
}
</style>
