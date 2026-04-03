<template>
  <div class="dashboard-view">
    <header class="view-header">
      <h1>{{ t('数据面板', 'Dashboard') }}</h1>
      <p class="subtitle">{{ t('系统概览与统计', 'System Overview & Statistics') }}</p>
    </header>
    
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon agents">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
        </div>
        <div class="stat-content">
          <span class="stat-value">{{ stats.totalAgents }}</span>
          <span class="stat-label">{{ t('智能体', 'Agents') }}</span>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon sessions">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <div class="stat-content">
          <span class="stat-value">{{ stats.totalSessions }}</span>
          <span class="stat-label">{{ t('会话', 'Sessions') }}</span>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon messages">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M8 12h8M12 8v8"/>
          </svg>
        </div>
        <div class="stat-content">
          <span class="stat-value">{{ stats.totalMessages }}</span>
          <span class="stat-label">{{ t('消息', 'Messages') }}</span>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon models">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42"/>
          </svg>
        </div>
        <div class="stat-content">
          <span class="stat-value">{{ stats.activeModels }}</span>
          <span class="stat-label">{{ t('模型', 'Models') }}</span>
        </div>
      </div>
    </div>
    
    <div class="dashboard-content">
      <section class="recent-section">
        <h2>{{ t('最近会话', 'Recent Sessions') }}</h2>
        <div class="recent-list" v-if="recentSessions.length > 0">
          <div 
            class="recent-item" 
            v-for="session in recentSessions" 
            :key="session.session_id"
            @click="openSession(session)"
          >
            <div class="recent-item-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </svg>
            </div>
            <div class="recent-item-content">
              <span class="recent-item-title">{{ session.agent_name }}</span>
              <span class="recent-item-preview">{{ session.preview || t('无预览', 'No preview') }}</span>
            </div>
            <span class="recent-item-time">{{ formatTime(session.updated_at) }}</span>
          </div>
        </div>
        <div class="empty-list" v-else>
          <p>{{ t('暂无最近会话', 'No recent sessions') }}</p>
        </div>
      </section>
      
      <section class="quick-actions">
        <h2>{{ t('快捷操作', 'Quick Actions') }}</h2>
        <div class="actions-grid">
          <button class="action-btn" @click="$emit('navigate', 'agent-config')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
              <circle cx="12" cy="7" r="4"/>
            </svg>
            <span>{{ t('新建智能体', 'New Agent') }}</span>
          </button>
          <button class="action-btn" @click="$emit('navigate', 'chat')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <span>{{ t('开始对话', 'Start Chat') }}</span>
          </button>
          <button class="action-btn" @click="$emit('navigate', 'models')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
            </svg>
            <span>{{ t('配置模型', 'Configure Models') }}</span>
          </button>
          <button class="action-btn" @click="$emit('navigate', 'settings')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 1v2M12 21v2"/>
            </svg>
            <span>{{ t('系统设置', 'System Settings') }}</span>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useSettingsStore } from '@/stores/settings'
import { useSessionStore } from '@/stores/session'
import type { SessionHistory } from '@/types'

const emit = defineEmits(['navigate'])

const agentStore = useAgentStore()
const settingsStore = useSettingsStore()
const sessionStore = useSessionStore()

const stats = computed(() => ({
  totalAgents: agentStore.agents.length,
  totalSessions: sessionStore.chats.length,
  totalMessages: sessionStore.chats.reduce((sum: number, c: any) => sum + (c.message_count || 0), 0),
  activeModels: agentStore.modelConfigs.length
}))

const recentSessions = ref<SessionHistory[]>([])

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString(settingsStore.settings.language === 'zh-CN' ? 'zh-CN' : 'en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function openSession(session: SessionHistory) {
  emit('navigate', 'history', session.session_id, session.agent_id)
}

onMounted(async () => {
  await sessionStore.loadChats()
  // 获取最近会话
  const sessions = sessionStore.chats.slice(0, 5)
  recentSessions.value = sessions.map((s: any) => ({
    session_id: s.session_id,
    agent_id: s.id,
    agent_name: s.name,
    created_at: s.created_at,
    updated_at: s.updated_at,
    message_count: 0,
    preview: ''
  }))
})
</script>

<style scoped>
.dashboard-view {
  padding: 32px;
  max-width: 1200px;
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

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 20px;
  margin-bottom: 40px;
}

.stat-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-icon svg {
  width: 24px;
  height: 24px;
}

.stat-icon.agents { background: rgba(59, 130, 246, 0.1); color: #3b82f6; }
.stat-icon.sessions { background: rgba(16, 185, 129, 0.1); color: #10b981; }
.stat-icon.messages { background: rgba(245, 158, 11, 0.1); color: #f59e0b; }
.stat-icon.models { background: rgba(139, 92, 246, 0.1); color: #8b5cf6; }

.stat-content {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-label {
  font-size: 14px;
  color: var(--text-secondary);
}

.dashboard-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 32px;
}

@media (max-width: 900px) {
  .dashboard-content {
    grid-template-columns: 1fr;
  }
}

.recent-section, .quick-actions {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
}

.recent-section h2, .quick-actions h2 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.recent-item:hover {
  background: var(--hover-bg);
}

.recent-item-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: var(--primary-color);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
}

.recent-item-icon svg {
  width: 18px;
  height: 18px;
}

.recent-item-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.recent-item-title {
  font-weight: 500;
  color: var(--text-primary);
}

.recent-item-preview {
  font-size: 13px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-item-time {
  font-size: 12px;
  color: var(--text-muted);
}

.empty-list {
  text-align: center;
  padding: 24px;
  color: var(--text-muted);
}

.actions-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.action-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px;
  background: var(--hover-bg);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
}

.action-btn:hover {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: white;
}

.action-btn svg {
  width: 24px;
  height: 24px;
}

.action-btn span {
  font-size: 14px;
  font-weight: 500;
}
</style>