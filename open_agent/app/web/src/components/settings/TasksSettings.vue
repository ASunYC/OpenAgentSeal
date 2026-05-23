<template>
  <div class="tab-content settings-shell">
    <div class="content-header settings-header">
      <h3>{{ t('任务', 'Tasks') }}</h3>
      <p>{{ t('查看任务队列与执行状态', 'View task queue and execution status') }}</p>
    </div>

    <div class="toolbar settings-toolbar">
      <div class="status-card settings-surface">
        <strong>{{ dispatcher.status || 'idle' }}</strong>
        <span>{{ dispatcher.status_message || t('没有任务运行中', 'No running tasks') }}</span>
      </div>
      <div class="toolbar-actions">
        <button class="btn-secondary settings-button" @click="loadTasks">{{ t('刷新', 'Refresh') }}</button>
      </div>
    </div>

    <div class="stats-grid">
      <div class="stat-card settings-surface">
        <span class="value">{{ tasks.length }}</span>
        <span class="label">{{ t('全部', 'All') }}</span>
      </div>
      <div class="stat-card settings-surface">
        <span class="value">{{ running.length }}</span>
        <span class="label">{{ t('运行中', 'Running') }}</span>
      </div>
      <div class="stat-card settings-surface">
        <span class="value">{{ pending.length }}</span>
        <span class="label">{{ t('等待中', 'Pending') }}</span>
      </div>
      <div class="stat-card settings-surface">
        <span class="value">{{ completed.length }}</span>
        <span class="label">{{ t('已完成', 'Completed') }}</span>
      </div>
    </div>

    <div v-if="loading" class="state-card settings-state settings-surface">{{ t('加载中...', 'Loading...') }}</div>
    <div v-else-if="error" class="state-card error settings-state settings-surface">{{ error }}</div>
    <div v-else-if="tasks.length === 0" class="state-card settings-state settings-surface">
      {{ t('当前没有任务。', 'No tasks currently.') }}
    </div>

    <div v-else class="task-list">
      <article v-for="task in tasks" :key="task.task_id" class="task-card settings-surface">
        <header class="task-header">
          <div>
            <h4>{{ task.task_id }}</h4>
            <p>{{ task.status }} | {{ task.priority }}</p>
          </div>
          <span class="task-status" :class="String(task.status)">{{ task.status_message || task.status }}</span>
        </header>
        <p class="task-input">{{ task.user_input }}</p>
        <div class="task-meta">
          <span>{{ t('创建', 'Created') }}: {{ formatDate(String(task.created_at || '')) }}</span>
          <span>{{ t('进度', 'Progress') }}: {{ formatProgress(task) }}</span>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { tasksApi } from '@/api'
import { useSettingsStore } from '@/stores/settings'

interface TaskRecord {
  task_id: string
  user_input: string
  status: string
  status_message?: string
  priority?: number
  created_at?: string
  progress?: {
    percentage?: number
    current_step?: number
    total_steps?: number
  }
}

const settingsStore = useSettingsStore()
const loading = ref(false)
const error = ref<string | null>(null)
const dispatcher = ref<Record<string, any>>({})
const tasks = ref<TaskRecord[]>([])
const running = ref<TaskRecord[]>([])
const pending = ref<TaskRecord[]>([])
const completed = ref<TaskRecord[]>([])

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatProgress(task: TaskRecord): string {
  const percentage = task.progress?.percentage
  if (typeof percentage === 'number') {
    return `${Math.round(percentage)}%`
  }
  const current = task.progress?.current_step ?? 0
  const total = task.progress?.total_steps ?? 0
  if (total > 0) {
    return `${current}/${total}`
  }
  return '--'
}

async function loadTasks() {
  loading.value = true
  error.value = null
  try {
    const data = await tasksApi.list()
    if (!data.success) {
      throw new Error(data.error || 'Failed to load tasks')
    }
    dispatcher.value = data.status as Record<string, any>
    tasks.value = data.tasks as unknown as TaskRecord[]
    running.value = data.running as unknown as TaskRecord[]
    pending.value = data.pending as unknown as TaskRecord[]
    completed.value = data.completed as unknown as TaskRecord[]
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadTasks()
})
</script>

<style scoped>
.status-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: min(100%, 280px);
  padding: 14px 16px;
}

.status-card strong {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.2;
  text-transform: capitalize;
}

.status-card span {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.4;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 84px;
  justify-content: center;
}

.value {
  color: var(--text-primary);
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
}

.label {
  color: var(--text-muted);
  font-size: 12px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.task-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.task-header h4 {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
  word-break: break-word;
}

.task-header p {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.task-status {
  flex: 0 0 auto;
  max-width: 220px;
  padding: 5px 9px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.task-status.running {
  background: #dbeafe;
  color: #1d4ed8;
}

.task-status.completed {
  background: #dcfce7;
  color: #15803d;
}

.task-status.failed,
.task-status.cancelled {
  background: #fee2e2;
  color: #b91c1c;
}

.task-input {
  margin: 0;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.6;
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  color: var(--text-muted);
  font-size: 12px;
}

@media (max-width: 900px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .toolbar-actions,
  .toolbar-actions .settings-button {
    width: 100%;
  }

  .task-header {
    flex-direction: column;
  }
}
</style>
