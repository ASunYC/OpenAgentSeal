import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import type { SystemSettings } from '@/types'

const defaultSettings: SystemSettings = {
  language: 'zh-CN',
  theme: 'dark',
  fontSize: 'medium',
  workspace: '',
  autoSave: true,
  streamResponse: true,
  useCoT: false  // 思考模式默认关闭
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<SystemSettings>({ ...defaultSettings })

  // 从localStorage加载设置
  function loadSettings() {
    try {
      const saved = localStorage.getItem('open-agent-settings')
      if (saved) {
        settings.value = { ...defaultSettings, ...JSON.parse(saved) }
      }
    } catch (e) {
      console.error('Failed to load settings:', e)
    }
  }

  // 保存设置到localStorage
  function saveSettings() {
    try {
      localStorage.setItem('open-agent-settings', JSON.stringify(settings.value))
    } catch (e) {
      console.error('Failed to save settings:', e)
    }
  }

  // 更新设置
  function updateSettings(newSettings: Partial<SystemSettings>) {
    settings.value = { ...settings.value, ...newSettings }
    saveSettings()
  }

  // 重置设置
  function resetSettings() {
    settings.value = { ...defaultSettings }
    saveSettings()
  }

  // 获取翻译文本
  function t(zhText: string, enText: string): string {
    return settings.value.language === 'zh-CN' ? zhText : enText
  }

  // 切换思考模式
  function toggleCoT() {
    settings.value.useCoT = !settings.value.useCoT
    saveSettings()
  }

  // 监听设置变化自动保存
  watch(settings, saveSettings, { deep: true })

  // 初始化加载
  loadSettings()

  return {
    settings,
    loadSettings,
    saveSettings,
    updateSettings,
    resetSettings,
    t,
    toggleCoT
  }
})