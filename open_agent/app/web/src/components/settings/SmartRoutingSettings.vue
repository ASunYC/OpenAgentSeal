<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('智能路由', 'Smart Routing') }}</h3>
      <p>{{ t('按输入模态自动选择模型', 'Automatically choose models by input modality') }}</p>
    </div>

    <section class="routing-card">
      <label class="switch-row">
        <span>
          <strong>{{ t('启用智能路由', 'Enable smart routing') }}</strong>
          <small>{{ t('文本、图片、音频可以走不同模型', 'Text, images, and audio can use different models') }}</small>
        </span>
        <input v-model="config.enabled" type="checkbox" />
      </label>

      <div class="routing-grid">
        <label v-for="item in routeItems" :key="item.key" class="route-field">
          <span>{{ item.label }}</span>
          <select v-model="config[item.key]">
            <option value="">{{ t('不指定', 'Not set') }}</option>
            <option v-for="model in models" :key="model.id" :value="model.id">
              {{ model.display_name || model.name }}
            </option>
          </select>
        </label>
      </div>

      <div class="actions">
        <button class="btn-save" :disabled="saving" @click="save">
          {{ saving ? t('保存中...', 'Saving...') : t('保存配置', 'Save') }}
        </button>
        <span v-if="message" class="save-message">{{ message }}</span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/api'
import { useSettingsStore } from '@/stores/settings'
import type { ModelConfig, SmartRoutingConfig } from '@/types'

const settingsStore = useSettingsStore()
const t = (zh: string, en: string) => settingsStore.settings.language === 'zh-CN' ? zh : en

const models = ref<ModelConfig[]>([])
const saving = ref(false)
const message = ref('')
const config = reactive<SmartRoutingConfig>({
  enabled: false,
  text_model_id: '',
  vision_model_id: '',
  audio_model_id: '',
  fallback_model_id: '',
})

const routeItems = computed(() => [
  { key: 'text_model_id' as const, label: t('文本模型', 'Text model') },
  { key: 'vision_model_id' as const, label: t('图片/视觉模型', 'Vision model') },
  { key: 'audio_model_id' as const, label: t('音频模型', 'Audio model') },
  { key: 'fallback_model_id' as const, label: t('兜底模型', 'Fallback model') },
])

async function load() {
  const [modelList, routing] = await Promise.all([
    api.getModelConfigs(),
    api.getSmartRouting(),
  ])
  models.value = modelList.filter((model) => !model.id.startsWith('default_'))
  Object.assign(config, routing)
}

async function save() {
  saving.value = true
  message.value = ''
  try {
    const result = await api.saveSmartRouting({ ...config })
    if (result.data) Object.assign(config, result.data)
    message.value = t('已保存', 'Saved')
  } catch (error) {
    message.value = error instanceof Error ? error.message : t('保存失败', 'Save failed')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.routing-card {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 20px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--surface-color, rgba(255, 255, 255, 0.72));
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.switch-row span {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.switch-row small {
  color: var(--text-muted);
  font-size: 13px;
}

.switch-row input {
  width: 42px;
  height: 22px;
}

.routing-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.route-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.route-field select {
  width: 100%;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--input-bg, #fff);
  color: var(--text-primary);
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-save {
  min-height: 38px;
  padding: 0 16px;
  border: 0;
  border-radius: 8px;
  background: var(--primary-color);
  color: #fff;
  cursor: pointer;
}

.btn-save:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.save-message {
  color: var(--text-muted);
  font-size: 13px;
}

@media (max-width: 720px) {
  .routing-grid {
    grid-template-columns: 1fr;
  }
}
</style>
