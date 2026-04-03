<template>
  <div class="app-container" :class="settingsStore.settings.theme">
    <!-- 主聊天面板 -->
    <main class="main-chat" v-if="currentView === 'chat'">
      <!-- 顶部标题栏 -->
      <header class="chat-header">
        <div class="header-left">
          <div class="logo">
            <svg class="logo-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <circle cx="12" cy="10" r="3"/>
              <path d="M7 16c0-2 2-3 5-3s5 1 5 3"/>
            </svg>
            <span class="logo-text">OpenAgentSeal</span>
          </div>
        </div>
        
        <div class="header-center">
          <!-- 智能体选择器 -->
          <div class="selector agent-selector">
            <select v-model="selectedAgentId" @change="onAgentChange">
              <option v-for="agent in agentStore.agents" :key="agent.id" :value="agent.id">
                {{ agent.name }}
              </option>
            </select>
          </div>
          
          <!-- 模型选择器 -->
          <div class="selector model-selector">
            <select v-model="selectedModelId" @change="onModelChange">
              <option v-for="model in availableModels" :key="model.id" :value="model.id">
                {{ model.display_name || model.name }}
              </option>
            </select>
          </div>
        </div>
        
        <div class="header-right">
          <button class="btn-settings" @click="openSettings" :title="t('设置', 'Settings')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
            </svg>
          </button>
        </div>
      </header>
      
      <!-- 中间聊天区域 -->
      <div class="chat-body">
        <!-- 私人对话区 -->
        <div class="private-chat-panel">
          <div class="chat-messages" ref="messagesContainer">
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
                <!-- 思考过程显示 - 跟随每个 assistant 消息 -->
                <ThinkingProcess
                  v-if="msg.role === 'assistant' && settingsStore.settings.useCoT && msg.thinking && (msg.thinking.steps.length > 0 || msg.thinking.isThinking)"
                  :thinking="msg.thinking"
                  :is-visible="true"
                  :user-query="msg.userQuery || ''"
                  :current-step="msg.thinking.steps.length"
                />
                <!-- 正在输入指示器 - 当消息内容为空且正在加载时显示 -->
                <div v-if="msg.role === 'assistant' && !msg.content && msg.thinking?.isThinking" class="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
                <!-- 消息内容 -->
                <div v-if="msg.content" class="message-text" v-html="renderMarkdown(msg.content)"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 底部工具栏 -->
      <footer class="chat-footer">
        <div class="input-area">
          <!-- 迭代模式切换按钮 -->
          <button
            class="cot-toggle-btn"
            :class="{ active: settingsStore.settings.useCoT }"
            :title="t('迭代模式', 'Iteration Mode')"
            @click="settingsStore.toggleCoT"
          >
            <span class="cot-icon">🔄</span>
          </button>
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
            </button>
            <button class="btn-send" @click="sendMessage" :disabled="!inputMessage.trim() || loading" :title="t('发送', 'Send')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22,2 15,22 11,13 2,9"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="input-hints">
          <span>{{ t('Enter 发送 · Shift+Enter 换行', 'Enter to send · Shift+Enter for new line') }}</span>
          <span
            :class="{ 'cot-active': settingsStore.settings.useCoT }"
            class="cot-status"
          >
            {{ settingsStore.settings.useCoT ? t('🔄 迭代模式已开启', '🔄 Iteration mode enabled') : t('🔄 迭代模式已关闭', '🔄 Iteration mode disabled') }}
          </span>
        </div>
      </footer>
    </main>
    
    <!-- 设置面板 -->
    <aside 
      class="settings-sidebar" 
      :class="{ open: showSettings }"
      :style="{ width: settingsWidth + 'px', right: showSettings ? '0' : '-' + settingsWidth + 'px' }"
    >
      <SettingsPanel
        :current-tab="settingsTab"
        :width="settingsWidth"
        @close="closeSettings"
        @switch-tab="switchSettingsTab"
        @update:width="onSettingsWidthChange"
      />
    </aside>
    
    <!-- 设置面板遮罩 -->
    <div class="settings-overlay" v-if="showSettings" @click="closeSettings"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, reactive } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useSettingsStore } from '@/stores/settings'
import { useSessionStore } from '@/stores/session'
import { api } from '@/api'
import SettingsPanel from '@/components/SettingsPanel.vue'
import ThinkingProcess from '@/components/ThinkingProcess.vue'
import { marked } from 'marked'
import type { Message, ModelConfig, ThinkingStep } from '@/types'

const agentStore = useAgentStore()
const settingsStore = useSettingsStore()
const sessionStore = useSessionStore()

// 当前视图
const currentView = ref('chat')

// 设置面板状态
const showSettings = ref(false)
const settingsTab = ref('dashboard') // 默认选中数据面板
const settingsWidth = ref(900) // 默认宽度 900px

// 处理设置面板宽度变化
const onSettingsWidthChange = (width: number) => {
  settingsWidth.value = width
}

// 聊天状态
const selectedAgentId = ref('')
const selectedModelId = ref('')
const sessionId = ref('')  // 独立的 session ID
const messages = ref<Message[]>([])
const inputMessage = ref('')
const loading = ref(false)
const messagesContainer = ref<HTMLElement | null>(null)

// 翻译函数
function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

// 可用模型
const availableModels = computed(() => {
  return agentStore.modelConfigs
})

// 获取智能体颜色
function getAgentColor(): string {
  const agent = agentStore.agents.find(a => a.id === selectedAgentId.value)
  if (!agent) return '#3b82f6'
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
  const index = agent.name.charCodeAt(0) % colors.length
  return colors[index]
}

// 获取智能体名称
function getAgentName(): string {
  const agent = agentStore.agents.find(a => a.id === selectedAgentId.value)
  return agent?.name || 'Agent'
}

// 格式化时间
function formatTime(timestamp?: string): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString(settingsStore.settings.language === 'zh-CN' ? 'zh-CN' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit'
  })
}

// 渲染 Markdown
function renderMarkdown(content: string): string {
  try {
    return marked(content) as string
  } catch {
    return content
  }
}

// 智能体切换
async function onAgentChange() {
  // 保存当前选中的 agent ID
  localStorage.setItem('selected_agent_id', selectedAgentId.value)
  
  messages.value = []
  const agent = agentStore.agents.find(a => a.id === selectedAgentId.value)
  if (agent) {
    selectedModelId.value = agent.model_id || ''
    // 创建或恢复 session
    await createOrGetSession()
  }
  loadChatHistory()
}

// 创建或获取 session
async function createOrGetSession() {
  if (!selectedAgentId.value) return
  
  try {
    // 尝试从 localStorage 恢复 session ID
    const savedSessionId = localStorage.getItem(`session_${selectedAgentId.value}`)
    
    if (savedSessionId) {
      // 检查 localStorage 中是否有对应的消息历史
      const savedMessages = localStorage.getItem(`messages_${savedSessionId}`)
      if (savedMessages) {
        // 有历史消息，直接使用保存的 session ID
        sessionId.value = savedSessionId
        console.log('Restored session from localStorage:', sessionId.value)
        return
      }
    }
    
    // 创建新的 session ID
    sessionId.value = `session_agent_${selectedAgentId.value}_${Date.now()}`
    localStorage.setItem(`session_${selectedAgentId.value}`, sessionId.value)
    console.log('Created new session:', sessionId.value)
  } catch (error) {
    console.error('Failed to create session:', error)
  }
}

// 模型切换
function onModelChange() {
  // 更新当前智能体的模型
  if (selectedAgentId.value && selectedModelId.value) {
    const agent = agentStore.agents.find(a => a.id === selectedAgentId.value)
    if (agent) {
      agent.model_id = selectedModelId.value
      agentStore.saveAgent(agent)
    }
  }
}

// 加载聊天历史
async function loadChatHistory() {
  if (!sessionId.value) return
  
  try {
    // 首先尝试从 localStorage 加载
    const savedMessages = localStorage.getItem(`messages_${sessionId.value}`)
    if (savedMessages) {
      messages.value = JSON.parse(savedMessages)
      scrollToBottom()
      return
    }
    
    // 如果 localStorage 没有，尝试从后端加载
    const history = await api.getSessionMessages(sessionId.value) as any
    if (history && Array.isArray(history)) {
      messages.value = history
    } else if (history && history.messages && Array.isArray(history.messages)) {
      messages.value = history.messages
    } else {
      messages.value = []
    }
    scrollToBottom()
  } catch (error) {
    console.error('Failed to load chat history:', error)
    // 尝试从 localStorage 加载作为备份
    const savedMessages = localStorage.getItem(`messages_${sessionId.value}`)
    if (savedMessages) {
      messages.value = JSON.parse(savedMessages)
    } else {
      messages.value = []
    }
  }
}

// 保存消息到 localStorage
function saveMessages() {
  if (sessionId.value && messages.value.length > 0) {
    localStorage.setItem(`messages_${sessionId.value}`, JSON.stringify(messages.value))
  }
}

// 生成唯一ID
function generateId(): string {
  return `step_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

// 发送消息
async function sendMessage() {
  if (!inputMessage.value.trim() || loading.value || !selectedAgentId.value) return
  
  // 如果没有 session，创建一个
  if (!sessionId.value) {
    await createOrGetSession()
  }
  
  const userMessage = inputMessage.value.trim()
  inputMessage.value = ''
  
  messages.value.push({
    role: 'user',
    content: userMessage,
    timestamp: new Date().toISOString()
  })
  
  scrollToBottom()
  loading.value = true
  
  // 创建一个 assistant 消息占位符，用于存储思考过程和最终回复
  // 使用 reactive 确保深层响应式
  const assistantMessage: Message = reactive({
    role: 'assistant' as const,
    content: '',
    userQuery: userMessage,  // 保存用户查询
    timestamp: new Date().toISOString(),
    thinking: settingsStore.settings.useCoT ? {
      isThinking: true,
      steps: [] as ThinkingStep[]
    } : undefined
  })
  messages.value.push(assistantMessage)
  
  try {
    let assistantContent = ''
    
    // 使用 sessionId 而不是 agentId
    // 监听后端发送的事件：thinking, tool_call, tool_result, complete, error
    await api.chat(sessionId.value, userMessage, (event) => {
      console.log('[Iteration Debug] Received event:', event)
      
      // 仅在开启迭代模式时处理步骤
      if (settingsStore.settings.useCoT && assistantMessage.thinking) {
        // 监听 step_start 事件
        if (event.event === 'step_start') {
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'thinking',
            content: `开始步骤 ${event.step}/${event.max_steps}`,
            timestamp: new Date().toISOString()
          })
        }
        
        // 监听 thinking 事件（LLM 思考内容）
        if (event.event === 'thinking' && event.content) {
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'thinking',
            content: event.content,
            timestamp: new Date().toISOString()
          })
          scrollToBottom()
        }
        
        // 监听工具调用
        if (event.event === 'tool_call') {
          const toolName = event.tool_name || 'unknown'
          const args = event.arguments ? JSON.stringify(event.arguments, null, 2) : ''
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'tool_call',
            content: `调用工具: ${toolName}`,
            toolName: toolName,
            toolOutput: args,
            timestamp: new Date().toISOString()
          })
          scrollToBottom()
        }
        
        // 监听工具结果
        if (event.event === 'tool_result') {
          const resultContent = event.result || event.error || ''
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'tool_result',
            content: event.success ? '工具执行成功' : '工具执行失败',
            toolOutput: typeof resultContent === 'string' ? resultContent : JSON.stringify(resultContent, null, 2),
            timestamp: new Date().toISOString()
          })
          scrollToBottom()
        }
        
        // 监听 step_end 事件
        if (event.event === 'step_end') {
          const stepInfo = `步骤 ${event.step} 完成，耗时 ${event.elapsed?.toFixed(2) || 0}s`
          // 更新最后一个步骤或添加新步骤
          const lastStep = assistantMessage.thinking.steps[assistantMessage.thinking.steps.length - 1]
          if (lastStep && lastStep.type === 'thinking') {
            lastStep.content += `\n${stepInfo}`
          }
        }
      }
      
      // 监听完成事件 - 这是获取最终回复的关键
      if (event.event === 'complete' && event.content) {
        assistantContent = event.content
        // 完成时停止迭代状态
        if (settingsStore.settings.useCoT && assistantMessage.thinking) {
          assistantMessage.thinking.isThinking = false
        }
      }
      
      // 监听错误事件
      if (event.event === 'error' && event.error) {
        console.error('Agent error:', event.error)
        if (settingsStore.settings.useCoT && assistantMessage.thinking) {
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'observation',
            content: `错误: ${event.error}`,
            timestamp: new Date().toISOString()
          })
          assistantMessage.thinking.isThinking = false
        }
      }
    })
    
    // 更新 assistant 消息内容
    assistantMessage.content = assistantContent || t('抱歉，没有收到回复。', 'Sorry, no response received.')
    
    scrollToBottom()
  } catch (error) {
    console.error('Failed to send message:', error)
    if (settingsStore.settings.useCoT && assistantMessage.thinking) {
      assistantMessage.thinking.isThinking = false
    }
    assistantMessage.content = t('抱歉，发生了错误。请重试。', 'Sorry, an error occurred. Please try again.')
  } finally {
    loading.value = false
    // 保存消息到 localStorage
    saveMessages()
  }
}

// 清空聊天
function clearChat() {
  if (confirm(t('确定要清空对话记录吗？', 'Are you sure you want to clear the chat?'))) {
    messages.value = []
    // 清空 localStorage 中的消息
    if (sessionId.value) {
      localStorage.removeItem(`messages_${sessionId.value}`)
    }
  }
}

// 滚动到底部
function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

// 打开设置
function openSettings() {
  showSettings.value = true
}

// 关闭设置
function closeSettings() {
  showSettings.value = false
}

// 切换设置标签
function switchSettingsTab(tab: string) {
  settingsTab.value = tab
}

// 初始化
onMounted(async () => {
  await agentStore.loadAgents()
  await agentStore.loadModelConfigs()
  await sessionStore.loadChats()
  
  // 尝试恢复之前选中的智能体
  const savedAgentId = localStorage.getItem('selected_agent_id')
  let agentToSelect = null
  
  if (savedAgentId) {
    // 验证保存的 agent ID 是否仍然有效
    agentToSelect = agentStore.agents.find(a => a.id === savedAgentId)
  }
  
  // 如果没有保存的 agent 或保存的 agent 不存在，选择第一个
  if (!agentToSelect && agentStore.agents.length > 0) {
    agentToSelect = agentStore.agents[0]
  }
  
  if (agentToSelect) {
    selectedAgentId.value = agentToSelect.id
    if (agentToSelect.model_id) {
      selectedModelId.value = agentToSelect.model_id
    }
    // 保存选中的 agent ID
    localStorage.setItem('selected_agent_id', agentToSelect.id)
    // 创建或恢复 session
    await createOrGetSession()
    await loadChatHistory()
    
    // 不再自动发送问候消息（避免与 CLI 重复）
    // 用户可以主动输入消息开始对话
  }
})
</script>

<style scoped>
.app-container {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  position: relative;
}

/* 主聊天区域 */
.main-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--main-bg);
}

/* 顶部标题栏 */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: var(--card-bg);
  border-bottom: 1px solid var(--border-color);
  height: 60px;
}

.header-left {
  display: flex;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-icon {
  width: 32px;
  height: 32px;
  color: var(--primary-color);
}

.logo-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.header-center {
  display: flex;
  align-items: center;
  gap: 16px;
}

.selector select {
  padding: 8px 32px 8px 12px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23666' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  min-width: 150px;
}

.selector select:focus {
  outline: none;
  border-color: var(--primary-color);
}

.header-right {
  display: flex;
  align-items: center;
}

.btn-settings {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.btn-settings:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.btn-settings svg {
  width: 20px;
  height: 20px;
}

/* 聊天消息区域 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.message {
  display: flex;
  gap: 12px;
  max-width: 80%;
}

.message.user {
  align-self: flex-end;
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
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.message.user .message-header {
  flex-direction: row-reverse;
}

.sender {
  font-weight: 500;
  color: var(--text-primary);
}

.time {
  color: var(--text-muted);
}

.message-text {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  background: var(--card-bg);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
}

.message.user .message-text {
  background: var(--primary-color);
  color: white;
  border-color: var(--primary-color);
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
  background: var(--card-bg);
  border: 1px solid var(--border-color);
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

/* 底部输入区域 */
.chat-footer {
  padding: 16px 24px;
  background: var(--card-bg);
  border-top: 1px solid var(--border-color);
}

.input-area {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.input-area textarea {
  flex: 1;
  padding: 12px 16px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  color: var(--text-primary);
  font-size: 14px;
  resize: none;
  min-height: 60px;
}

.input-area textarea:focus {
  outline: none;
  border-color: var(--primary-color);
}

/* CoT 切换按钮样式 */
.cot-toggle-btn {
  width: 44px;
  height: 44px;
  padding: 0;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.cot-toggle-btn:hover {
  background: var(--hover-bg);
}

.cot-toggle-btn.active {
  background: var(--primary-color);
  border-color: var(--primary-color);
  animation: pulse 2s infinite;
}

.cot-toggle-btn.active .cot-icon {
  filter: brightness(0) invert(1);
}

@keyframes pulse {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(59, 130, 246, 0);
  }
}

.cot-icon {
  font-size: 18px;
}

/* 输入提示 */
.input-hints {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-secondary);
}

.cot-status {
  transition: color 0.2s ease;
}

.cot-status.cot-active {
  color: var(--primary-color);
  font-weight: 500;
}

.input-actions {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: 8px;
}

.btn-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.btn-clear:hover {
  background: var(--hover-bg);
}

.btn-clear svg {
  width: 18px;
  height: 18px;
}

.btn-send {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 44px;
  height: 44px;
  padding: 0;
  background: var(--primary-color);
  border: none;
  border-radius: 12px;
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
  width: 18px;
  height: 18px;
}

/* 设置侧边栏 */
.settings-sidebar {
  position: fixed;
  top: 0;
  right: -900px;
  width: 900px;
  height: 100vh;
  background: var(--card-bg);
  border-left: 1px solid var(--border-color);
  z-index: 1000;
  transition: right 0.3s ease;
  overflow: hidden;
}

.settings-sidebar.open {
  right: 0;
}

/* 设置遮罩 */
.settings-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 999;
}

/* 双面板布局 */
.chat-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-body.dual-panel {
  flex-direction: row;
}

.private-chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
</style>