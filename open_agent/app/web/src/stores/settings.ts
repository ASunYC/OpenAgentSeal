import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { settingsApi } from '@/api'
import type { SystemSettings } from '@/types'

const SETTINGS_VERSION = 3
const DEFAULT_CONTEXT_WINDOW = 1_000_000

const defaultSettings: SystemSettings = {
  language: 'zh-CN',
  theme: 'light',
  settingsVersion: SETTINGS_VERSION,
  fontSize: 'medium',
  workspace: '',
  autoSave: true,
  streamResponse: true,
  enable_skills: true,
  useCoT: false,
  autoContextCompaction: true,
  contextCompactionTokenLimit: DEFAULT_CONTEXT_WINDOW,
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<SystemSettings>({ ...defaultSettings })
  const isHydrating = ref(true)

  async function loadSettings() {
    isHydrating.value = true
    try {
      const saved = localStorage.getItem('open-agent-settings')
      if (saved) {
        const savedSettings = JSON.parse(saved) as Partial<SystemSettings>
        if (savedSettings.contextCompactionTokenLimit === 60000) {
          savedSettings.contextCompactionTokenLimit = DEFAULT_CONTEXT_WINDOW
        }
        settings.value = { ...defaultSettings, ...savedSettings }
      }

      try {
        const backendSettings = await settingsApi.get()
        settings.value = {
          ...settings.value,
          ...backendSettings,
          settingsVersion: SETTINGS_VERSION,
        }
        localStorage.setItem('open-agent-settings', JSON.stringify(settings.value))
      } catch {
        settings.value.settingsVersion = SETTINGS_VERSION
        localStorage.setItem('open-agent-settings', JSON.stringify(settings.value))
      }
    } catch (error) {
      console.error('Failed to load settings:', error)
    } finally {
      isHydrating.value = false
    }
  }

  async function saveSettings() {
    if (isHydrating.value) return
    try {
      localStorage.setItem('open-agent-settings', JSON.stringify(settings.value))
      await settingsApi.save(settings.value)
    } catch (error) {
      console.error('Failed to save settings:', error)
    }
  }

  function updateSettings(newSettings: Partial<SystemSettings>) {
    settings.value = { ...settings.value, ...newSettings }
  }

  function resetSettings() {
    settings.value = { ...defaultSettings }
  }

  function t(zhText: string, enText: string): string {
    return settings.value.language === 'zh-CN' ? zhText : enText
  }

  function toggleCoT() {
    settings.value.useCoT = !settings.value.useCoT
  }

  watch(settings, () => {
    if (isHydrating.value) return
    void saveSettings()
  }, { deep: true })

  void loadSettings()

  return {
    settings,
    loadSettings,
    saveSettings,
    updateSettings,
    resetSettings,
    t,
    toggleCoT,
  }
})
