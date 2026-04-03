<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('工作目录', 'Workspace') }}</h3>
      <p>{{ t('管理工作目录和文件', 'Manage workspace and files') }}</p>
    </div>
    
    <div class="workspace-info">
      <div class="info-card">
        <h4>{{ t('当前工作目录', 'Current Workspace') }}</h4>
        <div class="path-display">
          <code>{{ workspacePath }}</code>
          <button class="btn-icon" @click="copyPath">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
          </button>
        </div>
      </div>
      
      <div class="actions-card">
        <h4>{{ t('快捷操作', 'Quick Actions') }}</h4>
        <div class="action-buttons">
          <button class="btn-action" @click="openFolder">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
            {{ t('打开文件夹', 'Open Folder') }}
          </button>
          <button class="btn-action" @click="changeWorkspace">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            {{ t('更改目录', 'Change Directory') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()

const workspacePath = ref('/home/user/open-agent-workspace')

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function copyPath() {
  navigator.clipboard.writeText(workspacePath.value)
  alert(t('已复制到剪贴板', 'Copied to clipboard'))
}

function openFolder() {
  alert(t('打开文件夹功能开发中', 'Open folder feature under development'))
}

function changeWorkspace() {
  const newPath = prompt(t('输入新的工作目录路径', 'Enter new workspace path'), workspacePath.value)
  if (newPath) {
    workspacePath.value = newPath
  }
}
</script>

<style scoped>
.tab-content { display: flex; flex-direction: column; gap: 20px; }
.content-header { margin-bottom: 8px; }
.content-header h3 { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.content-header p { font-size: 13px; color: var(--text-muted); margin: 0; }
.workspace-info { display: flex; flex-direction: column; gap: 16px; }
.info-card, .actions-card { background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 16px; }
.info-card h4, .actions-card h4 { font-size: 14px; font-weight: 600; color: var(--text-primary); margin: 0 0 12px 0; }
.path-display { display: flex; align-items: center; gap: 8px; padding: 12px; background: var(--hover-bg); border-radius: 8px; }
.path-display code { flex: 1; font-family: monospace; font-size: 13px; color: var(--text-primary); word-break: break-all; }
.btn-icon { width: 32px; height: 32px; border-radius: 6px; border: none; background: transparent; color: var(--text-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; }
.btn-icon:hover { background: var(--border-color); color: var(--text-primary); }
.btn-icon svg { width: 16px; height: 16px; }
.action-buttons { display: flex; gap: 12px; }
.btn-action { display: flex; align-items: center; gap: 8px; padding: 10px 16px; background: var(--hover-bg); border: 1px solid var(--border-color); border-radius: 8px; color: var(--text-primary); font-size: 13px; cursor: pointer; transition: all 0.2s; }
.btn-action:hover { border-color: var(--primary-color); }
.btn-action svg { width: 16px; height: 16px; }
</style>