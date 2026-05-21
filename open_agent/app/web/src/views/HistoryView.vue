<template>
  <div class="history-view">
    <header class="view-header">
      <h1>{{ t('历史对话', 'Chat History') }}</h1>
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
              <span class="chat-count">{{ getChatCount(agent.id) }} {{ t('个对话', 'chats') }}</span>
            </div>
          </div>
        </div>
      </div>
      
      <div class="chat-list" v-if="selectedAgentId">
        <h3>{{ t('对话列表', 'Chat List') }}</h3>
        <div class="chats">
          <div 
            v-for="chat in chats" 
            :key="chat.id"
            :class="['chat-item', { active: selectedChatId === chat.id }]"
            @click="selectChat(chat)"
          >
            <div class="chat-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </svg>
            </div>
            <div class="chat-info">
              <span class="chat-id">{{ chat.id.slice(0, 8) }}</span>
              <span class="chat-time">{{ formatTime(chat.created_at) }}</span>
            </div>
          </div>
          
          <div v-if="chats.length === 0" class="empty-chats">
            {{ t('暂无对话记录', 'No chat records') }}
          </div>
        </div>
      </div>
      
      <div class="chat-content" v-if="selectedChatId">
        <div class="content-header">
          <h3>{{ t('对话内容', 'Chat Content') }}</h3>
          <div class="content-header-actions">
            <span class="chat-id-badge">{{ selectedChatId }}</span>
            <button class="fork-chat-btn" @click="forkSelectedChat" :disabled="isForking">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="10" height="10" rx="2"/>
                <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
              </svg>
              <span>{{ isForking ? t('复制中...', 'Forking...') : t('复制成新任务', 'Fork Task') }}</span>
            </button>
          </div>
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
        <p>{{ t('请选择一个智能体查看历史对话', 'Select an agent to view chat history') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAgentStore } from '@/stores/agent'
import { api } from '@/api'
import type { AgentConfig, Chat, Message } from '@/types'
import { marked } from 'marked'

const settingsStore = useSettingsStore()
const agentStore = useAgentStore()

const agents = ref<AgentConfig[]>([])
const selectedAgentId = ref('')
const allChats = ref<Chat[]>([])
const chats = ref<Chat[]>([])
const selectedChatId = ref('')
const messages = ref<Message[]>([])
const isForking = ref(false)

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function getAvatarColor(name: string): string {
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
  const index = name.charCodeAt(0) % colors.length
  return colors[index]
}

function getChatCount(agentId: string): number {
  return allChats.value.filter(chat => getChatAgentId(chat) === agentId).length
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
  selectedChatId.value = ''
  messages.value = []
  
  try {
    allChats.value = await api.getChats()
    chats.value = allChats.value.filter(chat => getChatAgentId(chat) === agentId)
  } catch (error) {
    console.error('Failed to load chats:', error)
    chats.value = []
  }
}

async function selectChat(chat: Chat) {
  selectedChatId.value = chat.id
  
  try {
    const history = await api.getChatHistory(chat.id)
    messages.value = history.messages || []
  } catch (error) {
    console.error('Failed to load chat history:', error)
    messages.value = []
  }
}

async function forkSelectedChat() {
  if (!selectedChatId.value || isForking.value) return

  isForking.value = true
  try {
    const selectedChat = chats.value.find(chat => chat.id === selectedChatId.value)
    if (!selectedChat) return

    const forked = await api.forkChat(selectedChat.session_id, t('新任务', 'New Task'))
    allChats.value.unshift(forked.chat)
    chats.value.unshift(forked.chat)
    await selectChat(forked.chat)
  } catch (error) {
    console.error('Failed to fork chat:', error)
  } finally {
    isForking.value = false
  }
}

onMounted(async () => {
  await agentStore.loadAgents()
  agents.value = [...agentStore.agents]
  allChats.value = await api.getChats()
})

function getChatAgentId(chat: Chat): string {
  const fromMeta = chat.meta?.agent_id
  if (typeof fromMeta === 'string' && fromMeta) return fromMeta

  if (chat.session_id.startsWith('session_agent_')) {
    const agentPart = chat.session_id.slice('session_agent_'.length)
    if (agentPart.includes('_')) {
      return agentPart.split('_').slice(0, -1).join('_')
    }
  }

  return chat.user_id || 'default'
}
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

.agent-list, .chat-list {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 16px;
  overflow-y: auto;
}

.agent-list h3, .chat-list h3, .content-header h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 16px 0;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.agents, .chats {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.agent-item, .chat-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.agent-item:hover, .chat-item:hover {
  background: var(--hover-bg);
}

.agent-item.active, .chat-item.active {
  background: var(--primary-color);
  color: white;
}

.agent-item.active .chat-count,
.chat-item.active .chat-time {
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

.agent-info, .chat-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.agent-name, .chat-id {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-count, .chat-time {
  font-size: 12px;
  color: var(--text-muted);
}

.chat-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--hover-bg);
  border-radius: 8px;
  flex-shrink: 0;
}

.chat-icon svg {
  width: 18px;
  height: 18px;
  stroke: var(--text-secondary);
}

.chat-item.active .chat-icon {
  background: rgba(255, 255, 255, 0.2);
}

.chat-item.active .chat-icon svg {
  stroke: white;
}

.empty-chats {
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

.content-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chat-id-badge {
  padding: 4px 8px;
  background: var(--hover-bg);
  border-radius: 6px;
  font-size: 12px;
  font-family: monospace;
  color: var(--text-secondary);
}

.fork-chat-btn {
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: var(--glass-bg-strong, var(--card-bg));
  color: var(--text-primary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  transition: all 0.2s;
}

.fork-chat-btn:hover:not(:disabled) {
  border-color: var(--primary-color);
  color: var(--primary-color);
  transform: translateY(-1px);
}

.fork-chat-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.fork-chat-btn svg {
  width: 15px;
  height: 15px;
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
