<template>
  <div class="chat-view">
    <header class="view-header">
      <h1>{{ t('会话', 'Chat') }}</h1>
      <p class="subtitle">{{ t('与智能体对话', 'Chat with agents') }}</p>
    </header>
    
    <div class="chat-container">
      <div class="agent-selector">
        <label>{{ t('选择智能体', 'Select Agent') }}</label>
        <select v-model="selectedAgentId" @change="onAgentChange">
          <option value="">{{ t('请选择智能体', 'Please select an agent') }}</option>
          <option v-for="agent in agents" :key="agent.id" :value="agent.id">
            {{ agent.name }}
          </option>
        </select>
      </div>
      
      <div class="chat-panel" v-if="selectedAgentId">
        <div class="messages" ref="messagesContainer">
          <div 
            v-for="(msg, index) in messages" 
            :key="index"
            :class="['message', msg.role]"
          >
            <div class="message-avatar">
              <div v-if="msg.role === 'user'" class="avatar user-avatar">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg>
              </div>
              <div v-else class="avatar agent-avatar" :style="{ background: getAgentColor() }">
                {{ getAgentName().charAt(0).toUpperCase() }}
              </div>
            </div>
            <div class="message-content">
              <div class="message-header">
                <span class="sender">{{ msg.role === 'user' ? t('你', 'You') : getAgentName() }}</span>
                <span class="time">{{ formatTime(msg.timestamp) }}</span>
              </div>
              <div class="message-text" v-html="renderMarkdown(msg.content || '')"></div>
            </div>
          </div>
          
          <div v-if="loading" class="message assistant">
            <div class="message-avatar">
              <div class="avatar agent-avatar" :style="{ background: getAgentColor() }">
                {{ getAgentName().charAt(0).toUpperCase() }}
              </div>
            </div>
            <div class="message-content">
              <div class="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
        </div>
        
        <div class="input-area">
          <textarea 
            v-model="inputMessage"
            :placeholder="t('输入消息...', 'Type a message...')"
            @keydown.enter.exact.prevent="sendMessage"
            rows="3"
          ></textarea>
          <div class="input-actions">
            <button class="btn-clear" @click="clearChat">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3,6 5,6 21,6"/>
                <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
              </svg>
              {{ t('清空', 'Clear') }}
            </button>
            <button class="btn-send" @click="sendMessage" :disabled="!inputMessage.trim() || loading">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22,2 15,22 11,13 2,9"/>
              </svg>
              {{ t('发送', 'Send') }}
            </button>
          </div>
        </div>
      </div>
      
      <div class="no-agent-selected" v-else>
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <p>{{ t('请先选择一个智能体开始对话', 'Please select an agent to start chatting') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAgentStore } from '@/stores/agent'
import { api } from '@/api'
import type { AgentConfig, Message } from '@/types'
import { marked } from 'marked'

const settingsStore = useSettingsStore()
const agentStore = useAgentStore()

const agents = ref<AgentConfig[]>([])
const selectedAgentId = ref('')
const messages = ref<Message[]>([])
const inputMessage = ref('')
const loading = ref(false)
const messagesContainer = ref<HTMLElement | null>(null)

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function getAgentColor(): string {
  const agent = agents.value.find(a => a.id === selectedAgentId.value)
  if (!agent) return '#3b82f6'
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
  const index = agent.name.charCodeAt(0) % colors.length
  return colors[index]
}

function getAgentName(): string {
  const agent = agents.value.find(a => a.id === selectedAgentId.value)
  return agent?.name || 'Agent'
}

function formatTime(timestamp?: string): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString(settingsStore.settings.language === 'zh-CN' ? 'zh-CN' : 'en-US', {
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

async function onAgentChange() {
  messages.value = []
  if (selectedAgentId.value) {
    await loadChatHistory()
  }
}

async function loadChatHistory() {
  if (!selectedAgentId.value) return
  
  try {
    const history = await api.getChatHistory(selectedAgentId.value)
    messages.value = history?.messages || []
    scrollToBottom()
  } catch (error) {
    console.error('Failed to load chat history:', error)
  }
}

async function sendMessage() {
  if (!inputMessage.value.trim() || loading.value || !selectedAgentId.value) return
  
  const userMessage = inputMessage.value.trim()
  inputMessage.value = ''
  
  messages.value.push({
    role: 'user',
    content: userMessage,
    timestamp: new Date().toISOString()
  })
  
  scrollToBottom()
  loading.value = true
  
  try {
    let assistantContent = ''
    
    await api.chat(selectedAgentId.value, userMessage, (event) => {
      // Handle streaming events
      if (event.event === 'message' && event.content) {
        assistantContent = event.content
      }
    })
    
    messages.value.push({
      role: 'assistant',
      content: assistantContent || t('抱歉，没有收到回复。', 'Sorry, no response received.'),
      timestamp: new Date().toISOString()
    })
    
    scrollToBottom()
  } catch (error) {
    console.error('Failed to send message:', error)
    messages.value.push({
      role: 'assistant',
      content: t('抱歉，发生了错误。请重试。', 'Sorry, an error occurred. Please try again.'),
      timestamp: new Date().toISOString()
    })
  } finally {
    loading.value = false
  }
}

function clearChat() {
  if (confirm(t('确定要清空对话记录吗？', 'Are you sure you want to clear the chat?'))) {
    messages.value = []
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

onMounted(async () => {
  await agentStore.loadAgents()
  agents.value = [...agentStore.agents]
})
</script>

<style scoped>
.chat-view {
  padding: 32px;
  height: 100%;
  display: flex;
  flex-direction: column;
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

.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.agent-selector {
  margin-bottom: 20px;
}

.agent-selector label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.agent-selector select {
  width: 100%;
  max-width: 300px;
  padding: 12px 16px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
}

.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.message.user {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-avatar {
  background: var(--primary-color);
  color: white;
}

.user-avatar svg {
  width: 20px;
  height: 20px;
}

.agent-avatar {
  color: white;
  font-weight: 700;
  font-size: 16px;
}

.message-content {
  max-width: 70%;
}

.message.user .message-content {
  align-items: flex-end;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.message.user .message-header {
  flex-direction: row-reverse;
}

.sender {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.time {
  font-size: 12px;
  color: var(--text-muted);
}

.message-text {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  background: var(--hover-bg);
  color: var(--text-primary);
}

.message.user .message-text {
  background: var(--primary-color);
  color: white;
}

.message-text :deep(p) {
  margin: 0 0 8px 0;
}

.message-text :deep(p:last-child) {
  margin: 0;
}

.message-text :deep(code) {
  background: rgba(0, 0, 0, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.message-text :deep(pre) {
  background: rgba(0, 0, 0, 0.1);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: var(--hover-bg);
  border-radius: 12px;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: var(--text-muted);
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
  }
  30% {
    transform: translateY(-4px);
  }
}

.input-area {
  padding: 16px;
  border-top: 1px solid var(--border-color);
}

.input-area textarea {
  width: 100%;
  padding: 12px 16px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  resize: none;
}

.input-area textarea:focus {
  outline: none;
  border-color: var(--primary-color);
}

.input-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 12px;
}

.btn-clear {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-clear:hover {
  background: var(--hover-bg);
}

.btn-clear svg {
  width: 16px;
  height: 16px;
}

.btn-send {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  background: var(--primary-color);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-send:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-send:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-send svg {
  width: 16px;
  height: 16px;
}

.no-agent-selected {
  flex: 1;
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

.no-agent-selected p {
  font-size: 16px;
}
</style>