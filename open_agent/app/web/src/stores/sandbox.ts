import { defineStore } from 'pinia'
import { ref } from 'vue'

export type SandboxProvider = 'claude' | 'codex' | 'codewhale' | 'deepseek' | 'kimi' | 'opencode'
export type SandboxLayoutMode = 'tabs' | 'grid'

export interface SandboxTabState {
  localId: string
  provider: SandboxProvider
  sessionId: string
  exited: boolean
  initializing: boolean
}

export const useSandboxStore = defineStore('sandbox', () => {
  const tabs = ref<SandboxTabState[]>([])
  const activeTabId = ref('')
  const layoutMode = ref<SandboxLayoutMode>('tabs')

  function addTab(provider: SandboxProvider): SandboxTabState {
    const tab: SandboxTabState = {
      localId: `sandbox_tab_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      provider,
      sessionId: '',
      exited: false,
      initializing: true,
    }
    tabs.value.push(tab)
    activeTabId.value = tab.localId
    return tab
  }

  function updateTab(localId: string, patch: Partial<SandboxTabState>): SandboxTabState | null {
    const tab = tabs.value.find(item => item.localId === localId)
    if (!tab) return null
    Object.assign(tab, patch)
    return tab
  }

  function removeTab(localId: string): void {
    const index = tabs.value.findIndex(tab => tab.localId === localId)
    if (index === -1) return
    tabs.value.splice(index, 1)
    if (activeTabId.value === localId) {
      activeTabId.value = tabs.value[Math.min(index, tabs.value.length - 1)]?.localId || ''
    }
  }

  function activateTab(localId: string): void {
    if (tabs.value.some(tab => tab.localId === localId)) {
      activeTabId.value = localId
    }
  }

  function setLayoutMode(mode: SandboxLayoutMode): void {
    layoutMode.value = mode
  }

  return {
    tabs,
    activeTabId,
    layoutMode,
    addTab,
    updateTab,
    removeTab,
    activateTab,
    setLayoutMode,
  }
})
