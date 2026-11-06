<script setup lang="ts">
/**
 * 设置页 /settings（UI 规范 4.7）：Provider 配置 + 画风预设管理。
 * API Key 通过环境变量配置，此处仅展示变量名。
 */
import { ref, onMounted } from 'vue'
import { ElAlert, ElDialog, ElForm, ElFormItem, ElInput, ElInputNumber, ElSwitch, ElTable, ElTableColumn } from 'element-plus'
import { ElMessage } from 'element-plus'
import {
  listProviderConfigs, updateProviderConfig, listStylePresets, createStylePreset,
  type ProviderConfig, type StylePreset,
} from '@/api/modules'

const configs = ref<ProviderConfig[]>([])
const presets = ref<StylePreset[]>([])
const presetDialog = ref(false)
const presetForm = ref({ name: '', style_prompt: '', negative_prompt: '' })

async function load() {
  configs.value = await listProviderConfigs()
  presets.value = await listStylePresets()
}

async function saveConfig(row: ProviderConfig) {
  await updateProviderConfig(row.capability, {
    provider: row.provider, mode: row.mode, model: row.model,
    timeout_seconds: row.timeout_seconds, max_retries: row.max_retries,
    daily_quota: row.daily_quota, enabled: row.enabled,
  })
  ElMessage.success(`${row.capability} 配置已更新`)
  await load()
}

async function addPreset() {
  await createStylePreset(presetForm.value)
  presetDialog.value = false
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2>设置</h2>

    <el-alert type="info" :closable="false" style="margin-bottom: 12px"
      title="API Key 通过环境变量配置（.env），此处仅展示变量名，不存储明文密钥" />

    <h3>Provider 配置</h3>
    <el-table :data="configs" style="margin-bottom: 24px">
      <el-table-column prop="capability" label="能力" width="90" />
      <el-table-column label="供应商" width="130">
        <template #default="{ row }"><el-input v-model="row.provider" size="small" /></template>
      </el-table-column>
      <el-table-column label="模式" width="130">
        <template #default="{ row }">
          <el-select v-model="row.mode" size="small">
            <el-option label="mock" value="mock" />
            <el-option label="record" value="record" />
            <el-option label="replay" value="replay" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="模型" width="140">
        <template #default="{ row }"><el-input v-model="row.model" size="small" /></template>
      </el-table-column>
      <el-table-column prop="api_key_ref" label="Key 变量名" width="160" />
      <el-table-column label="超时(s)" width="90">
        <template #default="{ row }"><el-input-number v-model="row.timeout_seconds" size="small" :min="1" controls-position="right" style="width: 70px" /></template>
      </el-table-column>
      <el-table-column label="日限额" width="90">
        <template #default="{ row }"><el-input-number v-model="row.daily_quota" size="small" :min="1" controls-position="right" style="width: 70px" /></template>
      </el-table-column>
      <el-table-column label="启用" width="70">
        <template #default="{ row }"><el-switch v-model="row.enabled" /></template>
      </el-table-column>
      <el-table-column label="操作" width="80">
        <template #default="{ row }">
          <el-button size="small" type="primary" text @click="saveConfig(row as ProviderConfig)">保存</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="header">
      <h3>画风预设</h3>
      <el-button type="primary" @click="presetDialog = true; presetForm = { name: '', style_prompt: '', negative_prompt: '' }">新建预设</el-button>
    </div>
    <el-table :data="presets">
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="style_prompt" label="固定正向词" min-width="220" show-overflow-tooltip />
      <el-table-column prop="negative_prompt" label="负面提示词" min-width="220" show-overflow-tooltip />
    </el-table>

    <el-dialog v-model="presetDialog" title="新建画风预设" width="520px">
      <el-form label-width="90px">
        <el-form-item label="名称" required><el-input v-model="presetForm.name" /></el-form-item>
        <el-form-item label="正向词"><el-input v-model="presetForm.style_prompt" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="负面词"><el-input v-model="presetForm.negative_prompt" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="presetDialog = false">取消</el-button>
        <el-button type="primary" @click="addPreset">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
</style>
