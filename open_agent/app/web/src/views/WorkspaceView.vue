<template>
  <div class="workspace-view">
    <header class="view-header">
      <h1>{{ t('工作目录设置', 'Workspace Settings') }}</h1>
      <p class="subtitle">{{ t('配置智能体的工作目录', 'Configure agent workspace directory') }}</p>
    </header>
    
    <div class="workspace-card">
      <div class="current-path">
        <label>{{ t('当前工作目录', 'Current Workspace') }}</label>
        <div class="path-display">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          <span>{{ workspace }}</span>
        </div>
      </div>
      
      <div class="path-input-section">
        <label>{{ t('修改工作目录', 'Change Workspace') }}</label>
        <div class="input-group">
          <input 
            type="text" 
            v-model="newWorkspace" 
            :placeholder="t('输入新的工作目录路径', 'Enter new workspace path')"
          />
          <button class="btn-browse" @click="browseDirectory">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
            {{ t('浏览', 'Browse') }}
          </button>
        </div>
        <p class="hint">{{ t('工作目录用于存储智能体的文件、日志和配置', 'Workspace is used to store agent files, logs and configurations') }}</p>
      </div>
      
      <div class="actions">
        <button class="btn-primary" @click="saveWorkspace" :disabled="saving">
          <svg v-if="saving" class="spinner" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="31.4 31.4" />
          </svg>
          {{ saving ? t('保存中...', 'Saving...') : t('保存设置', 'Save Settings') }}
        </button>
      </div>
    </div>
    
    <div class="info-card">
      <h3>{{ t('工作目录说明', 'Workspace Information') }}</h3>
      <ul>
        <li>{{ t('智能体将在此目录下创建和管理文件', 'Agents will create and manage files in this directory') }}</li>
        <li>{{ t('会话日志将保存在工作目录的logs子目录中', 'Session logs will be saved in the logs subdirectory') }}</li>
        <li>{{ t('MCP配置文件存放在工作目录的config子目录中', 'MCP config files are stored in the config subdirectory') }}</li>
        <li>{{ t('修改工作目录后需要重启应用才能生效', 'Restart the application after changing workspace') }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { api } from '@/api'

const settingsStore = useSettingsStore()

const workspace = ref(settingsStore.settings.workspace)
const newWorkspace = ref('')
const saving = ref(false)

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

async function browseDirectory() {
  // 由于浏览器限制，无法直接打开文件选择器
  // 用户需要手动输入路径
  alert(t('请手动输入目录路径', 'Please enter the directory path manually'))
}

async function saveWorkspace() {
  if (!newWorkspace.value.trim()) {
    alert(t('请输入工作目录路径', 'Please enter workspace path'))
    return
  }
  
  saving.value = true
  try {
    const result = await api.setWorkDirectory(newWorkspace.value.trim())
    if (result.success) {
      workspace.value = newWorkspace.value.trim()
      settingsStore.updateSettings({ workspace: newWorkspace.value.trim() })
      newWorkspace.value = ''
      alert(t('工作目录已更新，重启后生效', 'Workspace updated, restart required'))
    } else {
      alert(result.error || t('保存失败', 'Save failed'))
    }
  } catch (error) {
    console.error('Failed to save workspace:', error)
    alert(t('保存失败', 'Save failed'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  newWorkspace.value = workspace.value
})
</script>

<style scoped>
.workspace-view {
  padding: 32px;
  max-width: 800px;
  margin: 0 auto;
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

.workspace-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
}

.current-path {
  margin-bottom: 24px;
}

.current-path label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.path-display {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--hover-bg);
  border-radius: 8px;
  color: var(--text-primary);
  font-family: monospace;
}

.path-display svg {
  width: 20px;
  height: 20px;
  color: var(--primary-color);
}

.path-input-section {
  margin-bottom: 24px;
}

.path-input-section label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.input-group {
  display: flex;
  gap: 12px;
}

.input-group input {
  flex: 1;
  padding: 12px 16px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
}

.input-group input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.btn-browse {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  background: var(--hover-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.btn-browse:hover {
  background: var(--border-color);
}

.btn-browse svg {
  width: 18px;
  height: 18px;
}

.hint {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-muted);
}

.actions {
  display: flex;
  justify-content: flex-end;
}

.btn-primary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: var(--primary-color);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.spinner {
  width: 18px;
  height: 18px;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.info-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
}

.info-card h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.info-card ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.info-card li {
  position: relative;
  padding-left: 20px;
  margin-bottom: 8px;
  color: var(--text-secondary);
  font-size: 14px;
}

.info-card li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: var(--primary-color);
}
</style>