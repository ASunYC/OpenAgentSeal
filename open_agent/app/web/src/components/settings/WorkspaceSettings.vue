<template>
  <div class="tab-content settings-shell">
    <div class="content-header settings-header">
      <h3>{{ t('工作目录', 'Workspace') }}</h3>
      <p>{{ t('管理当前工作目录和文件位置', 'Manage the current workspace and files') }}</p>
    </div>

    <div class="workspace-info">
      <div class="info-card settings-surface">
        <h4>{{ t('当前目录', 'Current Workspace') }}</h4>
        <div class="path-display settings-surface-soft">
          <code>{{ workspacePath || t('未设置工作目录', 'No workspace path set') }}</code>
          <button class="btn-icon settings-button" :title="t('复制路径', 'Copy path')" @click="copyPath">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
          </button>
        </div>
      </div>

      <div class="actions-card settings-surface">
        <h4>{{ t('快捷操作', 'Quick Actions') }}</h4>
        <div class="action-buttons">
          <button class="btn-action settings-button" @click="openFolder">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            {{ t('打开目录', 'Open Folder') }}
          </button>
          <button class="btn-action settings-button" @click="promptWorkspace">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
            </svg>
            {{ t('修改目录', 'Change Directory') }}
          </button>
          <button class="btn-action btn-primary settings-button settings-button-primary" :disabled="saving" @click="saveWorkspace">
            {{ saving ? t('保存中...', 'Saving...') : t('保存设置', 'Save Settings') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const workspacePath = ref(settingsStore.settings.workspace || '')
const saving = ref(false)

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function copyPath() {
  if (!workspacePath.value.trim()) return
  navigator.clipboard.writeText(workspacePath.value)
  alert(t('已复制到剪贴板。', 'Copied to clipboard.'))
}

async function openFolder() {
  const path = workspacePath.value.trim()
  if (!path) {
    alert(t('请先设置工作目录。', 'Please set a workspace path first.'))
    return
  }

  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_path', { target: path })
  } catch (error) {
    console.warn('Failed to open workspace folder:', error)
    alert(t('当前环境无法打开目录。', 'This environment cannot open folders.'))
  }
}

function promptWorkspace() {
  const nextPath = prompt(t('请输入新的工作目录路径', 'Enter a new workspace path'), workspacePath.value)
  if (nextPath) {
    workspacePath.value = nextPath.trim()
  }
}

async function refreshWorkspace() {
  try {
    const result = await api.getWorkDirectory()
    if (result.path) {
      workspacePath.value = result.path
      settingsStore.updateSettings({ workspace: result.path })
    }
  } catch (error) {
    console.warn('Failed to load workspace path:', error)
  }
}

async function saveWorkspace() {
  const nextPath = workspacePath.value.trim()
  if (!nextPath) {
    alert(t('请输入工作目录。', 'Please enter a workspace path.'))
    return
  }

  saving.value = true
  try {
    const result = await api.setWorkDirectory(nextPath)
    if (!result.success) {
      alert(result.error || t('保存失败。', 'Save failed.'))
      return
    }

    settingsStore.updateSettings({ workspace: nextPath })
    alert(t('工作目录已更新。', 'Workspace updated.'))
  } catch (error) {
    console.error('Failed to save workspace:', error)
    alert(t('保存失败。', 'Save failed.'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void refreshWorkspace()
})
</script>

<style scoped>
.workspace-info {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.info-card,
.actions-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-card h4,
.actions-card h4 {
  margin: 0;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.path-display {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  box-shadow: none !important;
}

.path-display code {
  flex: 1;
  min-width: 0;
  color: var(--text-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
}

.btn-icon {
  width: 40px;
  min-width: 40px;
  padding: 0;
}

.btn-icon svg,
.btn-action svg {
  width: 16px;
  height: 16px;
}

.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.btn-action:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}
</style>
