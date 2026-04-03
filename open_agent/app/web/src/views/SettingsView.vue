<template>
  <div class="settings-view">
    <header class="view-header">
      <h1>{{ t('基本设置', 'General Settings') }}</h1>
      <p class="subtitle">{{ t('自定义您的应用体验', 'Customize your app experience') }}</p>
    </header>
    
    <div class="settings-container">
      <!-- 外观设置 -->
      <section class="settings-section">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="5"/>
            <line x1="12" y1="1" x2="12" y2="3"/>
            <line x1="12" y1="21" x2="12" y2="23"/>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
            <line x1="1" y1="12" x2="3" y2="12"/>
            <line x1="21" y1="12" x2="23" y2="12"/>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
          </svg>
          {{ t('外观', 'Appearance') }}
        </h2>
        
        <div class="setting-item">
          <div class="setting-info">
            <label>{{ t('主题', 'Theme') }}</label>
            <p>{{ t('选择应用的主题模式', 'Choose the application theme mode') }}</p>
          </div>
          <div class="setting-control">
            <select v-model="settings.theme" @change="updateSettings">
              <option value="system">{{ t('跟随系统', 'System') }}</option>
              <option value="light">{{ t('浅色', 'Light') }}</option>
              <option value="dark">{{ t('深色', 'Dark') }}</option>
            </select>
          </div>
        </div>
        
        <div class="setting-item">
          <div class="setting-info">
            <label>{{ t('字体大小', 'Font Size') }}</label>
            <p>{{ t('调整界面字体大小', 'Adjust the interface font size') }}</p>
          </div>
          <div class="setting-control">
            <select v-model="settings.fontSize" @change="updateSettings">
              <option value="small">{{ t('小', 'Small') }}</option>
              <option value="medium">{{ t('中', 'Medium') }}</option>
              <option value="large">{{ t('大', 'Large') }}</option>
            </select>
          </div>
        </div>
      </section>
      
      <!-- 语言设置 -->
      <section class="settings-section">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
          </svg>
          {{ t('语言与地区', 'Language & Region') }}
        </h2>
        
        <div class="setting-item">
          <div class="setting-info">
            <label>{{ t('界面语言', 'Interface Language') }}</label>
            <p>{{ t('选择应用界面语言', 'Choose the application interface language') }}</p>
          </div>
          <div class="setting-control">
            <select v-model="settings.language" @change="updateSettings">
              <option value="zh-CN">简体中文</option>
              <option value="en-US">English</option>
            </select>
          </div>
        </div>
      </section>
      
      <!-- 功能设置 -->
      <section class="settings-section">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          {{ t('功能设置', 'Features') }}
        </h2>
        
        <div class="setting-item">
          <div class="setting-info">
            <label>{{ t('自动保存', 'Auto Save') }}</label>
            <p>{{ t('自动保存会话和配置', 'Automatically save sessions and configurations') }}</p>
          </div>
          <div class="setting-control">
            <label class="toggle">
              <input type="checkbox" v-model="settings.autoSave" @change="updateSettings">
              <span class="toggle-slider"></span>
            </label>
          </div>
        </div>
        
        <div class="setting-item">
          <div class="setting-info">
            <label>{{ t('流式响应', 'Stream Response') }}</label>
            <p>{{ t('启用AI回复的流式输出', 'Enable streaming output for AI responses') }}</p>
          </div>
          <div class="setting-control">
            <label class="toggle">
              <input type="checkbox" v-model="settings.streamResponse" @change="updateSettings">
              <span class="toggle-slider"></span>
            </label>
          </div>
        </div>
      </section>
      
      <!-- 关于 -->
      <section class="settings-section">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="16" x2="12" y2="12"/>
            <line x1="12" y1="8" x2="12.01" y2="8"/>
          </svg>
          {{ t('关于', 'About') }}
        </h2>
        
        <div class="about-content">
          <div class="app-logo">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </div>
          <div class="app-info">
            <h3>Open Agent</h3>
            <p class="version">{{ t('版本', 'Version') }}: {{ appVersion }}</p>
            <p class="description">{{ t('一个强大的AI智能体管理平台', 'A powerful AI agent management platform') }}</p>
          </div>
        </div>
      </section>
      
      <!-- 操作按钮 -->
      <div class="settings-actions">
        <button class="btn btn-secondary" @click="resetSettings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
          </svg>
          {{ t('重置设置', 'Reset Settings') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import type { SystemSettings } from '@/types'

const settingsStore = useSettingsStore()

const appVersion = ref('0.1.0')

const settings = reactive<SystemSettings>({
  language: 'zh-CN',
  theme: 'system',
  fontSize: 'medium',
  workspace: '',
  autoSave: true,
  streamResponse: true
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

async function updateSettings() {
  await settingsStore.updateSettings({ ...settings })
}

async function resetSettings() {
  const defaultSettings: SystemSettings = {
    language: 'zh-CN',
    theme: 'system',
    fontSize: 'medium',
    workspace: settings.workspace,
    autoSave: true,
    streamResponse: true
  }
  
  Object.assign(settings, defaultSettings)
  await settingsStore.updateSettings(defaultSettings)
}

onMounted(async () => {
  await settingsStore.loadSettings()
  Object.assign(settings, settingsStore.settings)
})
</script>

<style scoped>
.settings-view {
  padding: 32px;
  height: 100%;
  overflow-y: auto;
}

.view-header {
  margin-bottom: 32px;
}

.view-header h1 {
  font-size: 28px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 16px;
}

.settings-container {
  max-width: 800px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-section {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 20px 0;
}

.section-title svg {
  width: 20px;
  height: 20px;
  stroke: var(--primary-color);
}

.setting-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 0;
  border-bottom: 1px solid var(--border-color);
}

.setting-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.setting-item:first-child {
  padding-top: 0;
}

.setting-info {
  flex: 1;
}

.setting-info label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.setting-info p {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.setting-control {
  flex-shrink: 0;
  margin-left: 24px;
}

select {
  padding: 8px 32px 8px 12px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23666' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
}

select:focus {
  outline: none;
  border-color: var(--primary-color);
}

.toggle {
  position: relative;
  display: inline-block;
  width: 48px;
  height: 26px;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: var(--border-color);
  transition: 0.3s;
  border-radius: 26px;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 20px;
  width: 20px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
}

.toggle input:checked + .toggle-slider {
  background-color: var(--primary-color);
}

.toggle input:checked + .toggle-slider:before {
  transform: translateX(22px);
}

.about-content {
  display: flex;
  align-items: center;
  gap: 20px;
}

.app-logo {
  width: 64px;
  height: 64px;
  background: linear-gradient(135deg, var(--primary-color), #8b5cf6);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.app-logo svg {
  width: 36px;
  height: 36px;
  stroke: white;
}

.app-info h3 {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.app-info .version {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 8px 0;
}

.app-info .description {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

.settings-actions {
  display: flex;
  gap: 12px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  border: none;
}

.btn svg {
  width: 16px;
  height: 16px;
}

.btn-secondary {
  background: var(--hover-bg);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.btn-secondary:hover {
  background: var(--border-color);
}
</style>