<template>
  <div class="tab-content settings-shell">
    <div class="content-header settings-header">
      <h3>{{ t('数据面板', 'Dashboard') }}</h3>
      <p>{{ t('查看系统统计数据', 'View system statistics') }}</p>
    </div>

    <div v-if="loading" class="loading-state settings-state settings-surface">
      <span>{{ t('加载中...', 'Loading...') }}</span>
    </div>

    <div v-else-if="error" class="error-state settings-state settings-surface">
      <span>{{ t('加载失败：', 'Failed to load: ') }}{{ error }}</span>
    </div>

    <template v-else>
      <div class="stats-grid">
        <div class="stat-card settings-surface">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
            </svg>
          </div>
          <div class="stat-info">
            <span class="stat-value">{{ stats.messages }}</span>
            <span class="stat-label">{{ t('消息数', 'Messages') }}</span>
          </div>
        </div>

        <div class="stat-card settings-surface">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <rect x="5" y="7" width="14" height="10" rx="3" />
              <path d="M9 3v4M15 3v4M9 13h.01M15 13h.01M12 17v3" />
            </svg>
          </div>
          <div class="stat-info">
            <span class="stat-value">{{ stats.agents }}</span>
            <span class="stat-label">{{ t('智能体', 'Agents') }}</span>
          </div>
        </div>

        <div class="stat-card settings-surface">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M7 8h10M7 12h6" />
              <path d="M5 4h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-5 3V6a2 2 0 0 1 2-2z" />
            </svg>
          </div>
          <div class="stat-info">
            <span class="stat-value">{{ stats.chats }}</span>
            <span class="stat-label">{{ t('对话数', 'Chats') }}</span>
          </div>
        </div>

        <div class="stat-card settings-surface">
          <div class="stat-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M3 12h4l2-6 4 12 2-6h6" />
            </svg>
          </div>
          <div class="stat-info">
            <span class="stat-value">{{ stats.activityTotal }}</span>
            <span class="stat-label">{{ t('近期活动', 'Activity') }}</span>
          </div>
        </div>
      </div>

      <div class="chart-section settings-surface">
        <div class="chart-heading settings-toolbar">
          <h4>{{ t('使用趋势', 'Usage Trends') }}</h4>
          <button class="refresh-button settings-button" @click="loadStats">{{ t('刷新', 'Refresh') }}</button>
        </div>

        <div v-if="activity.length" class="bar-chart settings-surface-soft">
          <div v-for="item in activity" :key="item.date" class="bar-item">
            <div class="bar-track">
              <div class="bar-fill" :style="{ height: `${barHeight(item.count)}%` }"></div>
            </div>
            <span class="bar-count">{{ item.count }}</span>
            <span class="bar-label">{{ formatDate(item.date) }}</span>
          </div>
        </div>

        <div v-else class="empty-chart settings-state settings-surface-soft">
          {{ t('暂无可显示的近期活动。', 'No recent activity to display.') }}
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { dashboardApi } from '@/api'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()

const loading = ref(false)
const error = ref<string | null>(null)
const activity = ref<{ date: string; count: number }[]>([])
const stats = ref({
  messages: 0,
  agents: 0,
  chats: 0,
  activityTotal: 0,
})

const maxActivity = computed(() => Math.max(...activity.value.map((item) => item.count), 1))

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function barHeight(count: number): number {
  return Math.max(8, Math.round((count / maxActivity.value) * 100))
}

function formatDate(date: string): string {
  if (!date) return '--'
  const parsed = new Date(date)
  if (Number.isNaN(parsed.getTime())) return date
  return `${parsed.getMonth() + 1}/${parsed.getDate()}`
}

async function loadStats() {
  loading.value = true
  error.value = null
  try {
    const data = await dashboardApi.getStats()
    activity.value = data.recentActivity
    stats.value = {
      messages: data.totalMessages,
      agents: data.activeAgents,
      chats: data.totalChats,
      activityTotal: data.recentActivity.reduce((sum, item) => sum + item.count, 0),
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    console.error('Failed to load dashboard stats:', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadStats()
})
</script>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  min-height: 92px;
}

.stat-icon {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border: 1px solid rgba(47, 110, 244, 0.14);
  border-radius: 14px;
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
  color: var(--primary-color);
}

.stat-icon svg {
  width: 20px;
  height: 20px;
}

.stat-info {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.stat-value {
  color: var(--text-primary);
  font-size: 24px;
  font-weight: 700;
  line-height: 1.15;
}

.stat-label {
  color: var(--text-muted);
  font-size: 12px;
}

.chart-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chart-heading h4 {
  margin: 0;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.bar-chart {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(40px, 1fr));
  align-items: end;
  gap: 10px;
  min-height: 190px;
  padding: 12px;
  box-shadow: none !important;
}

.bar-item {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-direction: column;
  min-width: 0;
}

.bar-track {
  display: flex;
  align-items: end;
  width: 100%;
  height: 120px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--hover-bg);
}

.bar-fill {
  width: 100%;
  min-height: 8px;
  border-radius: 999px 999px 0 0;
  background: linear-gradient(180deg, var(--primary-color), color-mix(in srgb, var(--primary-color) 72%, #ffffff));
}

.bar-count {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}

.bar-label {
  color: var(--text-muted);
  font-size: 11px;
}

@media (max-width: 720px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
