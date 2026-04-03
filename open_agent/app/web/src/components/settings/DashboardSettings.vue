<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('数据面板', 'Dashboard') }}</h3>
      <p>{{ t('查看系统统计数据', 'View system statistics') }}</p>
    </div>
    
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon">💬</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.messages }}</span>
          <span class="stat-label">{{ t('消息数', 'Messages') }}</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🤖</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.agents }}</span>
          <span class="stat-label">{{ t('智能体', 'Agents') }}</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">📁</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.sessions }}</span>
          <span class="stat-label">{{ t('会话数', 'Sessions') }}</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🔧</div>
        <div class="stat-info">
          <span class="stat-value">{{ stats.tools }}</span>
          <span class="stat-label">{{ t('工具数', 'Tools') }}</span>
        </div>
      </div>
    </div>
    
    <div class="chart-section">
      <h4>{{ t('使用趋势', 'Usage Trends') }}</h4>
      <div class="chart-placeholder">
        <p>{{ t('图表功能开发中...', 'Chart feature under development...') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()

const stats = ref({
  messages: 1284,
  agents: 3,
  sessions: 12,
  tools: 8
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}
</script>

<style scoped>
.tab-content { display: flex; flex-direction: column; gap: 20px; }
.content-header { margin-bottom: 8px; }
.content-header h3 { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.content-header p { font-size: 13px; color: var(--text-muted); margin: 0; }
.stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.stat-card { display: flex; align-items: center; gap: 12px; padding: 16px; background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 12px; }
.stat-icon { width: 48px; height: 48px; border-radius: 12px; background: var(--hover-bg); display: flex; align-items: center; justify-content: center; font-size: 24px; }
.stat-info { display: flex; flex-direction: column; }
.stat-value { font-size: 24px; font-weight: 700; color: var(--text-primary); }
.stat-label { font-size: 12px; color: var(--text-muted); }
.chart-section { background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 16px; }
.chart-section h4 { font-size: 14px; font-weight: 600; color: var(--text-primary); margin: 0 0 16px 0; }
.chart-placeholder { height: 200px; display: flex; align-items: center; justify-content: center; background: var(--hover-bg); border-radius: 8px; }
.chart-placeholder p { color: var(--text-muted); font-size: 13px; }
</style>