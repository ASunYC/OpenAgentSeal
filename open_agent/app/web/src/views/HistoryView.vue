<template>
  <div class="history-view">
    <header class="view-header">
      <h1>{{ t('历史会话', 'Chat History') }}</h1>
      <p class="subtitle">{{ t('查看历史对话记录', 'View historical chat records') }}</p>
    </header>
    
    <div class="history-container">
      <div class="agent-list">
        <h3>{{ t('智能体列表', 'Agent List') }}</h3>
        <div class="agents">
          <div 
            v-for="agent in agents" 
            :key="agent.id"
            :class="['agent-item', { active: selectedAgentId === agent.id }]"
            @click="selectAgent(agent.id)"
          >
            <div class="agent-avatar" :style="{ background: getAvatarColor(agent.name) }">
              {{ agent.name.charAt(0).toUpperCase() }}
            </div>
            <div class="agent-info">
              <span class="agent-name">{{ agent.name }}</span>
              <span class="session-count">{{ getSessionCount(agent.id) }} {{ t('个会话', 'sessions') }}</span>
            </div>
          </div>
        </div>
      </div>
      
      <div class="session-list" v-if="selectedAgentId">
        <h3>{{ t('会话列表', 'Session List') }}</h3>
        <div class="sessions">
          <div 
            v-for="session in sessions" 
            :key="session.id"
            :class="['session-item', { active: selectedSessionId === session.id }]"
            @click="selectSession(session)"
          >
            <div class="session-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </svg>
            </div>
            <div class="session-info">
              <span class="session-id">{{ session.id.slice(0, 8) }}</span>
              <span class="session-time">{{ formatTime(session.created_at) }}</span>
            </div>
          </div>
          
          <div v-if="sessions.length === 0" class="empty-sessions">
            {{ t('暂无会话记录', 'No chat sessions') }}
          </div>
        </div>
      </div>
      
      <div class="chat-content" v-if="selectedSessionId">
        <div class="content-header">
          <h3>{{ t('会话内容', 'Session Content') }}</h3>
          <span class="session-id-badge">{{ selectedSessionId }}</span>
        </div>
        
        <div class="messages" ref="messagesContainer">
          <div 
            v-for="(msg, index) in messages" 
            :key="index"
            :class="['message', msg.role]"
          >
            <div class="message-role">
              {{ msg.role === 'user' ? t('用户', 'User') : t('助手', 'Assistant') }}
            </div>
            <div class="message-content" v-html="renderMarkdown(msg.content)"></div>
            <div class="message-time" v-if="msg.timestamp">{{ formatTime(msg.timestamp) }}</div>
          </div>
        </div>
      </div>
      
      <div class="no-selection" v-else-if="!selectedAgentId">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12,6 12,12 16,14"/>
          </svg>
        </div>
        <p>{{ t('请选择一个智能体查看历史会话', 'Select an agent to view chat history') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAgentStore } from '@/stores/agent'
import { api } from '@/api'
import type { AgentConfig, Message, ChatSession } from '@/types'
import { marked } from 'marked'

const settingsStore = useSettingsStore()
const agentStore = useAgentStore()

const agents = ref<AgentConfig[]>([])
const selectedAgentId = ref('')
const sessions = ref<ChatSession[]>([])
const selectedSessionId = ref('')
const messages = ref<Message[]>([])

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function getAvatarColor(name: string): string {
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
  const index = name.charCodeAt(0) % colors.length
  return colors[index]
}

function getSessionCount(agentId: string): number {
  // 这里应该从实际数据获取
  return sessions.value.filter(s => s.agent_id === agentId).length || 0
}

function formatTime(timestamp: string): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleString(settingsStore.settings.language === 'zh-CN' ? 'zh-CN' : 'en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function renderMarkdown(content: string): string {
  try {
    return marked(content) as string
  } catch {
    return content
  }
}

async function selectAgent(agentId: string) {
  selectedAgentId.value = agentId
  selectedSessionId.value = ''
  messages.value = []
  
  try {
    sessions.value = await api.getSessions(agentId)
  } catch (error) {
    console.error('Failed to load sessions:', error)
    sessions.value = []
  }
}

async function selectSession(session: ChatSession) {
  selectedSessionId.value = session.id
  
  try {
    const history = await api.getSessionMessages(session.id)
    messages.value = history || []
  } catch (error) {
    console.error('Failed to load chat history:', error)
    messages.value = []
  }
}

onMounted(async () => {
  await agentStore.loadAgents()
  agents.value = [...agentStore.agents]
})
</script>

<style scoped>
.history-view {
  padding: 32px;
  height: 100%;
}

.view-header {
  margin-bottom: 24px;
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

.history-container {
  display: grid;
  grid-template-columns: 250px 280px 1fr;
  gap: 24px;
  height: calc(100% - 80px);
}

.agent-list, .session-list {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  overflow-y: auto;
}

.agent-list h3, .session-list h3, .content-header h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 16px 0;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.agents, .sessions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.agent-item, .session-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.agent-item:hover, .session-item:hover {
  background: var(--hover-bg);
}

.agent-item.active, .session-item.active {
  background: var(--primary-color);
  color: white;
}

.agent-item.active .session-count,
.session-item.active .session-time {
  color: rgba(255, 255, 255, 0.7);
}

.agent-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 16px;
  flex-shrink: 0;
}

.agent-info, .session-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.agent-name, .session-id {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-count, .session-time {
  font-size: 12px;
  color: var(--text-muted);
}

.session-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--hover-bg);
  border-radius: 8px;
  flex-shrink: 0;
}

.session-icon svg {
  width: 18px;
  height: 18px;
  stroke: var(--text-secondary);
}

.session-item.active .session-icon {
  background: rgba(255, 255, 255, 0.2);
}

.session-item.active .session-icon svg {
  stroke: white;
}

.empty-sessions {
  text-align: center;
  padding: 24px;
  color: var(--text-muted);
  font-size: 14px;
}

.chat-content {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.session-id-badge {
  padding: 4px 8px;
  background: var(--hover-bg);
  border-radius: 6px;
  font-size: 12px;
  font-family: monospace;
  color: var(--text-secondary);
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.message {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--hover-bg);
  border-radius: 12px;
}

.message.assistant {
  background: var(--input-bg);
  border-left: 3px solid var(--primary-color);
}

.message-role {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
}

.message-content {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
}

.message-content :deep(p) {
  margin: 0 0 8px 0;
}

.message-content :deep(p:last-child) {
  margin: 0;
}

.message-content :deep(code) {
  background: rgba(0, 0, 0, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.message-content :deep(pre) {
  background: rgba(0, 0, 0, 0.1);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.message-time {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 8px;
  text-align: right;
}

.no-selection {
  grid-column: 2 / 4;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}

.empty-icon {
  margin-bottom: 16px;
}

.empty-icon svg {
  width: 64px;
  height: 64px;
  stroke: var(--text-muted);
}

.no-selection p {
  font-size: 16px;
}
</style>