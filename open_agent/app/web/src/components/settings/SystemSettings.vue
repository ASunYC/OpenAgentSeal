<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('系统设置', 'System Settings') }}</h3>
      <p>{{ t('配置系统参数', 'Configure system parameters') }}</p>
    </div>
    
    <div class="settings-sections">
      <div class="section">
        <h4>{{ t('外观', 'Appearance') }}</h4>
        <div class="setting-item">
          <label>{{ t('主题', 'Theme') }}</label>
          <select v-model="settings.theme">
            <option value="dark">{{ t('深色', 'Dark') }}</option>
            <option value="light">{{ t('浅色', 'Light') }}</option>
            <option value="auto">{{ t('自动', 'Auto') }}</option>
          </select>
        </div>
        <div class="setting-item">
          <label>{{ t('语言', 'Language') }}</label>
          <select v-model="settings.language">
            <option value="zh-CN">中文</option>
            <option value="en-US">English</option>
          </select>
        </div>
      </div>
      
      <div class="section">
        <h4>{{ t('性能', 'Performance') }}</h4>
        <div class="setting-item">
          <label>{{ t('流式输出', 'Stream Output') }}</label>
          <input type="checkbox" v-model="settings.streamOutput" />
        </div>
        <div class="setting-item">
          <label>{{ t('自动保存', 'Auto Save') }}</label>
          <input type="checkbox" v-model="settings.autoSave" />
        </div>
      </div>
      
      <div class="section">
        <h4>{{ t('关于', 'About') }}</h4>
        <div class="about-info">
          <p><strong>Open Agent</strong></p>
          <p>{{ t('版本', 'Version') }}: 2026.03.15</p>
          <p>{{ t('构建', 'Build') }}: 2026.03.15-001</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()

const settings = reactive({
  theme: settingsStore.settings.theme,
  language: settingsStore.settings.language,
  streamOutput: true,
  autoSave: true
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

watch(settings, (newVal) => {
  settingsStore.updateSettings(newVal)
}, { deep: true })
</script>

<style scoped>
.tab-content { display: flex; flex-direction: column; gap: 20px; }
.content-header { margin-bottom: 8px; }
.content-header h3 { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.content-header p { font-size: 13px; color: var(--text-muted); margin: 0; }
.settings-sections { display: flex; flex-direction: column; gap: 24px; }
.section { background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 16px; }
.section h4 { font-size: 14px; font-weight: 600; color: var(--text-primary); margin: 0 0 16px 0; padding-bottom: 12px; border-bottom: 1px solid var(--border-color); }
.setting-item { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border-color); }
.setting-item:last-child { border-bottom: none; }
.setting-item label { font-size: 13px; color: var(--text-primary); }
.setting-item select { padding: 6px 12px; background: var(--input-bg); border: 1px solid var(--border-color); border-radius: 6px; color: var(--text-primary); font-size: 13px; }
.setting-item input[type="checkbox"] { width: 18px; height: 18px; accent-color: var(--primary-color); }
.about-info { padding: 8px 0; }
.about-info p { font-size: 13px; color: var(--text-secondary); margin: 4px 0; }
</style>