<template>
  <div class="tab-content settings-shell">
    <div class="content-header settings-header logs-header">
      <h3>{{ t('日志', 'Logs') }}</h3>
      <p>{{ t('查看最近的运行日志', 'View recent run logs') }}</p>
      <div class="log-header-actions">
        <span class="retention-pill">{{ t('仅展示近10天的日志', 'Showing logs from the last 10 days') }}</span>
        <button class="btn-secondary settings-button" :disabled="files.length === 0" @click="clearVisibleLogs">
          {{ t('清理', 'Clear') }}
        </button>
      </div>
    </div>

    <div class="toolbar settings-toolbar">
      <div class="path-pill settings-pill">
        <span>{{ t('日志目录', 'Log directory') }}</span>
        <code>{{ logPath || '...' }}</code>
      </div>
      <div class="toolbar-actions">
        <button class="btn-secondary settings-button" @click="openFolder">{{ t('打开目录', 'Open Folder') }}</button>
        <button class="btn-secondary settings-button" @click="loadLogs">{{ t('刷新', 'Refresh') }}</button>
      </div>
    </div>

    <div v-if="loading" class="state-card settings-state settings-surface">{{ t('加载中...', 'Loading...') }}</div>
    <div v-else-if="error" class="state-card error settings-state settings-surface">{{ error }}</div>
    <div v-else-if="files.length === 0" class="state-card settings-state settings-surface">
      {{ t('暂无日志文件。', 'No log files found.') }}
    </div>

    <div v-else class="log-list">
      <article v-for="file in files" :key="file.path" class="log-card settings-surface">
        <header class="log-header">
          <div>
            <h4>{{ file.name }}</h4>
            <p>{{ formatSize(file.size) }} | {{ formatDate(file.updated_at) }}</p>
          </div>
        </header>
        <pre class="log-tail settings-surface-soft">{{ file.tail.join('\n') || t('空日志文件', 'Empty log file') }}</pre>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { logsApi } from '@/api'
import { useSettingsStore } from '@/stores/settings'

interface LogFile {
  name: string
  path: string
  size: number
  updated_at: string
  tail: string[]
}

const settingsStore = useSettingsStore()
const logPath = ref('')
const files = ref<LogFile[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function openFolder() {
  if (!logPath.value) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_path', { target: logPath.value })
  } catch (err) {
    console.warn('Failed to open logs folder:', err)
    alert(t('当前环境无法打开目录。', 'This environment cannot open folders.'))
  }
}

async function loadLogs() {
  loading.value = true
  error.value = null
  try {
    const data = await logsApi.list()
    if (!data.success) {
      throw new Error(data.error || 'Failed to load logs')
    }
    logPath.value = data.path
    files.value = data.files
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function clearVisibleLogs() {
  files.value = []
  error.value = null
  loading.value = false
}

onMounted(() => {
  void loadLogs()
})
</script>

<style scoped>
.logs-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 16px;
  align-items: start;
}

.logs-header p {
  grid-column: 1;
}

.log-header-actions {
  grid-column: 2;
  grid-row: 1 / span 2;
  display: flex;
  align-items: center;
  gap: 8px;
}

.retention-pill {
  padding: 5px 10px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
}

.path-pill {
  max-width: min(100%, 560px);
  border-radius: 14px;
}

.path-pill code {
  min-width: 0;
  color: var(--text-primary);
  word-break: break-all;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.log-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.log-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.log-header h4 {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.log-header p {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.log-tail {
  max-height: 220px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  color: var(--text-primary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  box-shadow: none !important;
}

@media (max-width: 720px) {
  .logs-header {
    grid-template-columns: 1fr;
  }

  .log-header-actions {
    grid-column: 1;
    grid-row: auto;
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar-actions,
  .toolbar-actions .settings-button {
    width: 100%;
  }
}
</style>
