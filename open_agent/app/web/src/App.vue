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
          <button class="btn-settings" @click="forkCurrentTask" :disabled="loading || isForking" :title="t('复制为新任务', 'Fork into new task')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="10" height="10" rx="2"/>
              <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
            </svg>
          </button>
          <button class="btn-settings" @click="openBrowserHome" title="Browser">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <path d="M2 12h20"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
          </button>
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
          <div class="chat-messages" ref="messagesContainer" @click="handleChatClick">
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
            <svg class="cot-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 12a9 9 0 0 1-15.31 6.36"/>
              <path d="M3 12A9 9 0 0 1 18.31 5.64"/>
              <path d="M6 18H3v3"/>
              <path d="M18 6h3V3"/>
            </svg>
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
            {{ settingsStore.settings.useCoT ? t('迭代模式已开启', 'Iteration mode enabled') : t('迭代模式已关闭', 'Iteration mode disabled') }}
          </span>
        </div>
      </footer>
    </main>

    <main class="main-browser" v-else-if="currentView === 'browser'">
      <header class="chat-header browser-app-header">
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
        <div class="header-right">
          <button class="btn-settings" @click="currentView = 'chat'" title="Back to chat">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M19 12H5"/>
              <path d="M12 19l-7-7 7-7"/>
            </svg>
          </button>
          <button class="btn-settings" @click="openSettings" :title="t('设置', 'Settings')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
            </svg>
          </button>
        </div>
      </header>

      <section class="browser-workspace">
        <div class="browser-tabs">
          <button
            v-for="tab in browserTabs"
            :key="tab.id"
            class="browser-tab"
            :class="{ active: tab.id === activeBrowserTabId }"
            @click="switchBrowserTab(tab.id)"
            :title="tab.url"
          >
            <span class="browser-tab-title">{{ tab.title }}</span>
            <span v-if="tab.loadState === 'loading'" class="browser-tab-state"></span>
            <span class="browser-tab-close" @click.stop="closeBrowserTab(tab.id)">x</span>
          </button>
          <button class="browser-new-tab" @click="createBrowserTab()" title="New tab">+</button>
        </div>

        <div class="browser-toolbar">
          <button class="browser-icon-btn" @click="browserBack" :disabled="!canBrowserBack" title="Back">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M19 12H5"/>
              <path d="M12 19l-7-7 7-7"/>
            </svg>
          </button>
          <button class="browser-icon-btn" @click="browserForward" :disabled="!canBrowserForward" title="Forward">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M5 12h14"/>
              <path d="M12 5l7 7-7 7"/>
            </svg>
          </button>
          <button class="browser-icon-btn" @click="reloadBrowserTab" :disabled="!activeBrowserTab" title="Reload">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
              <path d="M21 3v6h-6"/>
            </svg>
          </button>
          <input
            class="browser-address"
            v-model="browserAddress"
            @keydown.enter.prevent="goBrowserAddress"
            placeholder="https://example.com"
          />
          <button class="browser-go" @click="goBrowserAddress">Go</button>
        </div>

        <div class="browser-frame-area" v-if="activeBrowserTab">
          <iframe
            class="browser-frame"
            :key="`${activeBrowserTab.id}-${activeBrowserTab.renderKey}`"
            :src="activeBrowserTab.url"
            @load="onBrowserFrameLoad"
            referrerpolicy="no-referrer"
          ></iframe>
        </div>
        <div class="browser-empty" v-else>
          <button class="browser-go" @click="createBrowserTab()">Open browser tab</button>
        </div>
      </section>
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
import { useChatStore } from '@/stores/chat'
import { api } from '@/api'
import SettingsPanel from '@/components/SettingsPanel.vue'
import ThinkingProcess from '@/components/ThinkingProcess.vue'
import { marked } from 'marked'
import type { Message, ThinkingStep } from '@/types'
import { typewriterReveal } from '@/utils/typewriter'

const agentStore = useAgentStore()
const settingsStore = useSettingsStore()
const chatStore = useChatStore()

// 当前视图
const currentView = ref('chat')

type BrowserLoadState = 'idle' | 'loading' | 'loaded'

interface BrowserTab {
  id: string
  url: string
  title: string
  history: string[]
  historyIndex: number
  renderKey: number
  loadState: BrowserLoadState
}

const BROWSER_HOME = 'about:blank'
const browserTabs = ref<BrowserTab[]>([])
const activeBrowserTabId = ref('')
const browserAddress = ref('')

const activeBrowserTab = computed(() => {
  return browserTabs.value.find(tab => tab.id === activeBrowserTabId.value) || null
})

const canBrowserBack = computed(() => {
  return !!activeBrowserTab.value && activeBrowserTab.value.historyIndex > 0
})

const canBrowserForward = computed(() => {
  return !!activeBrowserTab.value && activeBrowserTab.value.historyIndex < activeBrowserTab.value.history.length - 1
})

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
const runnerSessionId = ref('')
const messages = ref<Message[]>([])
const inputMessage = ref('')
const loading = ref(false)
const isForking = ref(false)
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
  const colors = ['#2f6ef4', '#3f7f68', '#8a6f2c', '#9b4f45', '#596579', '#4f7f9f', '#6f6a9a']
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
    const html = marked(content) as string
    return normalizeRenderedLinks(html)
  } catch {
    return content
  }
}

function normalizeRenderedLinks(html: string): string {
  if (typeof DOMParser === 'undefined') return html

  const parser = new DOMParser()
  const doc = parser.parseFromString(`<div>${html}</div>`, 'text/html')

  doc.querySelectorAll('a[href]').forEach((anchor) => {
    const rawText = anchor.textContent || anchor.getAttribute('href') || ''
    const parts = splitUrlDecoration(rawText)
    const cleanedHref = sanitizeBrowserUrlCandidate(parts.core || rawText)
    const link = anchor.cloneNode(true) as HTMLAnchorElement

    link.setAttribute('href', cleanedHref)
    link.setAttribute('target', '_blank')
    link.setAttribute('rel', 'noopener noreferrer')
    link.textContent = cleanedHref

    if (parts.leading || parts.trailing) {
      const wrapper = doc.createElement('span')
      if (parts.leading) wrapper.appendChild(doc.createTextNode(parts.leading))
      wrapper.appendChild(link)
      if (parts.trailing) wrapper.appendChild(doc.createTextNode(parts.trailing))
      anchor.replaceWith(wrapper)
    } else {
      anchor.replaceWith(link)
    }
  })

  return doc.body.firstElementChild?.innerHTML || html
}

function splitUrlDecoration(value: string): { leading: string; core: string; trailing: string } {
  let text = value.trim()
  const leadingMatch = text.match(/^[<([{'"“‘]+/)
  const leading = leadingMatch?.[0] || ''
  if (leading) text = text.slice(leading.length)

  const trailingMatch = text.match(/[>\])}"'”’。、，。！？!?.,;:]+$/)
  const trailing = trailingMatch?.[0] || ''
  if (trailing) text = text.slice(0, -trailing.length)

  return {
    leading,
    core: text,
    trailing,
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
    // 创建或恢复 runner 对话通道
    await createOrGetSession()
  }
  loadChatHistory()
}

// 创建或获取 runner 对话通道
async function createOrGetSession() {
  if (!selectedAgentId.value) return
  
  try {
    // 尝试从 localStorage 恢复 runner 通道 ID
    const savedRunnerSessionId = localStorage.getItem(`session_${selectedAgentId.value}`)
    
    if (savedRunnerSessionId) {
      // 检查 localStorage 中是否有对应的消息历史
      const savedMessages = localStorage.getItem(`messages_${savedRunnerSessionId}`)
      if (savedMessages) {
        // 有历史消息，直接使用保存的 runner 通道 ID
        runnerSessionId.value = savedRunnerSessionId
        console.log('Restored runner chat channel from localStorage:', runnerSessionId.value)
        return
      }
    }
    
    // 创建新的 runner 通道 ID
    runnerSessionId.value = `session_agent_${selectedAgentId.value}_${Date.now()}`
    localStorage.setItem(`session_${selectedAgentId.value}`, runnerSessionId.value)
    console.log('Created runner chat channel:', runnerSessionId.value)
  } catch (error) {
    console.error('Failed to create runner chat channel:', error)
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
  if (!runnerSessionId.value) return
  
  try {
    // 首先尝试从 localStorage 加载
    const savedMessages = localStorage.getItem(`messages_${runnerSessionId.value}`)
    if (savedMessages) {
      messages.value = JSON.parse(savedMessages)
      scrollToBottom()
      return
    }
    
    // 如果 localStorage 没有，尝试从 runner chat 历史加载
    const chat = await api.getChatByRunnerSession(runnerSessionId.value)
    const history = await api.getChatHistory(chat.id)
    messages.value = history.messages || []
    scrollToBottom()
  } catch (error) {
    console.error('Failed to load chat history:', error)
    // 尝试从 localStorage 加载作为备份
    const savedMessages = localStorage.getItem(`messages_${runnerSessionId.value}`)
    if (savedMessages) {
      messages.value = JSON.parse(savedMessages)
    } else {
      messages.value = []
    }
  }
}

// 保存消息到 localStorage
function saveMessages() {
  if (runnerSessionId.value && messages.value.length > 0) {
    localStorage.setItem(`messages_${runnerSessionId.value}`, JSON.stringify(messages.value))
  }
}

async function forkCurrentTask() {
  if (!runnerSessionId.value || isForking.value || !selectedAgentId.value) return

  isForking.value = true
  try {
    const currentMessages = JSON.parse(JSON.stringify(messages.value))
    const forked = await api.forkChat(runnerSessionId.value, `${getAgentName()} Task`)
    const nextRunnerSessionId = forked.chat.session_id

    runnerSessionId.value = nextRunnerSessionId
    localStorage.setItem(`session_${selectedAgentId.value}`, nextRunnerSessionId)
    localStorage.setItem(`messages_${nextRunnerSessionId}`, JSON.stringify(currentMessages))
    saveMessages()

    console.log('[Task Fork] Created new task runner channel:', nextRunnerSessionId, 'copied messages:', forked.copied_message_count)
  } catch (error) {
    console.error('Failed to fork current task:', error)
  } finally {
    isForking.value = false
  }
}

// 生成唯一ID
function generateId(): string {
  return `step_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

// 发送消息
async function sendMessage() {
  if (!inputMessage.value.trim() || loading.value || !selectedAgentId.value) return
  
  // 如果没有 runner 通道，创建一个
  if (!runnerSessionId.value) {
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
    
    // 使用 runner 通道 ID，而不是 agentId
    // 监听后端发送的事件：thinking, tool_call, tool_result, complete, error
    await api.chat(runnerSessionId.value, userMessage, (event) => {
      console.log('[Iteration Debug] Received event:', event)

      if (event.event === 'message' && event.content) {
        assistantContent = event.content
        assistantMessage.content = event.content
        scrollToBottom()
      }
      
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
    
    // 更新 assistant 消息内容，加入一个本地打字机动画
    await typewriterReveal(
      assistantMessage,
      assistantContent || t('抱歉，没有收到回复。', 'Sorry, no response received.'),
      {
        onUpdate: scrollToBottom
      }
    )

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
    if (runnerSessionId.value) {
      localStorage.removeItem(`messages_${runnerSessionId.value}`)
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

function normalizeBrowserUrl(rawUrl: string): string {
  const trimmed = sanitizeBrowserUrlCandidate(rawUrl)
  if (!trimmed) return BROWSER_HOME
  if (trimmed === 'about:blank') return BROWSER_HOME

  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)
    ? trimmed
    : `https://${trimmed}`

  try {
    const parsed = new URL(withScheme)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return BROWSER_HOME
    }
    return parsed.toString()
  } catch {
    return BROWSER_HOME
  }
}

function sanitizeBrowserUrlCandidate(rawUrl: string): string {
  let value = rawUrl.trim()
  value = value.replace(/^[<([{'"“‘]+/, '')
  value = value.replace(/[>\])}"'”’。、，。！？!?.,;:]+$/g, '')

  try {
    const parsed = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? value : `https://${value}`)
    parsed.hash = ''
    return parsed.toString()
  } catch {
    return value
  }
}

function titleFromUrl(url: string): string {
  if (!url || url === 'about:blank') {
    return 'New Tab'
  }

  try {
    return new URL(url).host || url
  } catch {
    return url
  }
}

function createBrowserTab(rawUrl: string = BROWSER_HOME) {
  const url = normalizeBrowserUrl(rawUrl)
  const tab: BrowserTab = {
    id: `browser_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    url,
    title: titleFromUrl(url),
    history: [url],
    historyIndex: 0,
    renderKey: 0,
    loadState: 'loading'
  }

  browserTabs.value.push(tab)
  activeBrowserTabId.value = tab.id
  browserAddress.value = url
  currentView.value = 'browser'
}

function openBrowserHome() {
  if (!activeBrowserTab.value) {
    createBrowserTab()
    return
  }

  browserAddress.value = activeBrowserTab.value.url
  currentView.value = 'browser'
}

function openBrowserTab(rawUrl: string) {
  createBrowserTab(rawUrl)
}

function navigateActiveBrowserTab(rawUrl: string, replace = false) {
  const tab = activeBrowserTab.value
  if (!tab) {
    createBrowserTab(rawUrl)
    return
  }

  const url = normalizeBrowserUrl(rawUrl)
  tab.url = url
  tab.title = titleFromUrl(url)
  tab.loadState = 'loading'
  tab.renderKey += 1

  if (replace) {
    tab.history[tab.historyIndex] = url
  } else {
    tab.history = tab.history.slice(0, tab.historyIndex + 1)
    tab.history.push(url)
    tab.historyIndex = tab.history.length - 1
  }

  browserAddress.value = url
  currentView.value = 'browser'
}

function goBrowserAddress() {
  navigateActiveBrowserTab(browserAddress.value)
}

function switchBrowserTab(tabId: string) {
  const tab = browserTabs.value.find(item => item.id === tabId)
  if (!tab) return

  activeBrowserTabId.value = tab.id
  browserAddress.value = tab.url
  currentView.value = 'browser'
}

function closeBrowserTab(tabId: string) {
  const index = browserTabs.value.findIndex(tab => tab.id === tabId)
  if (index === -1) return

  browserTabs.value.splice(index, 1)

  if (activeBrowserTabId.value === tabId) {
    const nextTab = browserTabs.value[index] || browserTabs.value[index - 1] || null
    activeBrowserTabId.value = nextTab?.id || ''
    browserAddress.value = nextTab?.url || ''
    if (!nextTab) currentView.value = 'chat'
  }
}

function browserBack() {
  const tab = activeBrowserTab.value
  if (!tab || tab.historyIndex <= 0) return

  tab.historyIndex -= 1
  tab.url = tab.history[tab.historyIndex]
  tab.title = titleFromUrl(tab.url)
  tab.loadState = 'loading'
  tab.renderKey += 1
  browserAddress.value = tab.url
}

function browserForward() {
  const tab = activeBrowserTab.value
  if (!tab || tab.historyIndex >= tab.history.length - 1) return

  tab.historyIndex += 1
  tab.url = tab.history[tab.historyIndex]
  tab.title = titleFromUrl(tab.url)
  tab.loadState = 'loading'
  tab.renderKey += 1
  browserAddress.value = tab.url
}

function reloadBrowserTab() {
  const tab = activeBrowserTab.value
  if (!tab) return

  tab.loadState = 'loading'
  tab.renderKey += 1
}

function onBrowserFrameLoad() {
  const tab = activeBrowserTab.value
  if (tab) tab.loadState = 'loaded'
}

function handleChatClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const anchor = target?.closest?.('a[href]') as HTMLAnchorElement | null
  if (!anchor) return

  const href = anchor.getAttribute('href') || ''
  if (!/^https?:\/\//i.test(href)) return

  event.preventDefault()
  openBrowserTab(href)
}

async function listenForDesktopNavigation() {
  try {
    const tauriEvent = await import('@tauri-apps/api/event')
    await tauriEvent.listen<string>('external-navigation-requested', event => {
      if (event.payload) openBrowserTab(sanitizeBrowserUrlCandidate(event.payload))
    })
  } catch (error) {
    console.debug('Tauri navigation bridge is not available in web mode:', error)
  }
}

// 初始化
onMounted(async () => {
  await listenForDesktopNavigation()

  await agentStore.loadAgents()
  await agentStore.loadModelConfigs()
  await chatStore.loadChats()
  
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
    // 创建或恢复 runner 对话通道
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
  isolation: isolate;
  background:
    radial-gradient(circle at 18% 12%, var(--mesh-one), transparent 34%),
    radial-gradient(circle at 82% 18%, var(--mesh-two), transparent 30%),
    radial-gradient(circle at 50% 90%, rgba(47, 110, 244, 0.08), transparent 34%),
    linear-gradient(135deg, var(--mesh-three), var(--bg-secondary));
}

.app-container::before {
  content: '';
  position: absolute;
  inset: -18%;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 22% 24%, rgba(47, 110, 244, 0.16), transparent 24%),
    radial-gradient(circle at 76% 18%, rgba(181, 213, 255, 0.32), transparent 24%),
    radial-gradient(circle at 62% 78%, rgba(255, 255, 255, 0.55), transparent 28%);
  filter: blur(26px);
  opacity: 0.72;
  animation: mesh-drift 18s ease-in-out infinite alternate;
  transform: translate3d(0, 0, 0);
}

.app-container::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image: radial-gradient(circle at center, var(--dot-color) 1px, transparent 1px);
  background-size: 18px 18px;
  mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.9), rgba(0, 0, 0, 0.78));
  opacity: 0.38;
}

.app-container.dark::before {
  background:
    radial-gradient(circle at 22% 24%, rgba(47, 110, 244, 0.12), transparent 24%),
    radial-gradient(circle at 76% 18%, rgba(70, 95, 130, 0.22), transparent 24%),
    radial-gradient(circle at 62% 78%, rgba(24, 25, 27, 0.5), transparent 28%);
  opacity: 0.62;
}

@keyframes mesh-drift {
  from {
    transform: translate3d(-1.5%, -1%, 0) scale(1);
  }
  to {
    transform: translate3d(1.5%, 1%, 0) scale(1.04);
  }
}

/* 主聊天区域 */
.main-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: transparent;
  position: relative;
  z-index: 1;
}

.main-browser {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: transparent;
  min-width: 0;
  position: relative;
  z-index: 1;
}

.browser-workspace {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.browser-app-header {
  flex-shrink: 0;
}

.browser-header-center {
  justify-content: center;
  flex: 1;
}

.browser-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px 0;
  background: var(--glass-bg);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  border-bottom: 1px solid var(--border-color);
  overflow-x: auto;
  flex-shrink: 0;
}

.browser-tab,
.browser-new-tab,
.browser-command,
.browser-icon-btn,
.browser-go {
  border: 1px solid var(--border-color);
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
  transition: transform 0.18s ease, background 0.2s, border-color 0.2s, opacity 0.2s;
}

.browser-tab {
  height: 34px;
  max-width: 220px;
  min-width: 120px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px 0 12px;
  border-radius: 10px 10px 0 0;
  border-bottom-color: transparent;
}

.browser-tab.active {
  background: var(--glass-bg-strong);
  border-color: var(--primary-color);
  border-bottom-color: transparent;
  box-shadow: 0 10px 24px rgba(47, 110, 244, 0.08);
}

.browser-tab-title {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.browser-tab-close {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.browser-tab-close:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.browser-tab-state {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 2px solid var(--primary-color);
  border-top-color: transparent;
  animation: browser-spin 0.8s linear infinite;
  flex-shrink: 0;
}

.browser-new-tab {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  font-size: 20px;
  line-height: 1;
  flex-shrink: 0;
}

.browser-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px 12px;
  background: var(--glass-bg);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.browser-icon-btn,
.browser-command {
  height: 36px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.browser-icon-btn {
  width: 36px;
  padding: 0;
}

.browser-command {
  gap: 6px;
  padding: 0 12px;
}

.browser-icon-btn svg,
.browser-command svg {
  width: 16px;
  height: 16px;
}

.browser-icon-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.browser-tab:hover,
.browser-new-tab:hover,
.browser-command:hover,
.browser-icon-btn:hover:not(:disabled),
.browser-go:hover {
  background: var(--hover-bg);
  transform: translateY(-1px);
}

.browser-address {
  flex: 1;
  min-width: 160px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  font-size: 14px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
}

.browser-address:focus {
  outline: none;
  border-color: var(--primary-color);
}

.browser-go {
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  font-weight: 600;
}

.browser-frame-area {
  flex: 1;
  min-height: 0;
  margin: 16px 18px 18px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  background: var(--glass-bg-strong);
  box-shadow: var(--soft-shadow);
}

.browser-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: white;
  display: block;
}

.browser-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

@keyframes browser-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 顶部标题栏 */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: var(--glass-bg);
  backdrop-filter: blur(20px) saturate(170%);
  -webkit-backdrop-filter: blur(20px) saturate(170%);
  border-bottom: 1px solid var(--border-color);
  box-shadow: inset 0 1px 0 var(--glass-border);
  height: 64px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 14px;
}

.logo-icon {
  width: 30px;
  height: 30px;
  color: var(--primary-color);
  filter: drop-shadow(0 8px 16px rgba(47, 110, 244, 0.18));
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.header-center {
  display: flex;
  align-items: center;
  gap: 16px;
}

.selector select {
  height: 36px;
  padding: 8px 34px 8px 13px;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 560;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23737373' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  min-width: 150px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65), 0 8px 20px rgba(17, 24, 39, 0.04);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.18s ease;
}

.selector select:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(47, 110, 244, 0.12);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.btn-settings {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.18s ease, background 0.2s, border-color 0.2s, color 0.2s;
}

.btn-settings:hover {
  background: var(--glass-bg-strong);
  border-color: var(--border-color);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.btn-settings svg {
  width: 20px;
  height: 20px;
}

/* 聊天消息区域 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 30px 32px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.message {
  display: flex;
  gap: 12px;
  max-width: min(78%, 860px);
  animation: message-rise 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.message.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

@keyframes message-rise {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-avatar {
  flex-shrink: 0;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35), 0 10px 22px rgba(17, 24, 39, 0.08);
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
  font-size: 14px;
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
  font-size: 11px;
  letter-spacing: 0.01em;
}

.message.user .message-header {
  flex-direction: row-reverse;
}

.sender {
  font-weight: 650;
  color: var(--text-primary);
}

.time {
  color: var(--text-muted);
}

.message-text {
  padding: 12px 15px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.6;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  box-shadow: 0 12px 28px rgba(17, 24, 39, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.68);
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
}

.message.user .message-text {
  background: var(--primary-color);
  color: white;
  border-color: var(--primary-color);
  box-shadow: 0 14px 30px rgba(47, 110, 244, 0.18);
}

.message-text :deep(p) {
  margin: 0 0 8px 0;
}

.message-text :deep(p:last-child) {
  margin: 0;
}

.message-text :deep(code) {
  background: rgba(23, 23, 23, 0.08);
  padding: 2px 6px;
  border-radius: 6px;
  font-family: monospace;
}

.message-text :deep(pre) {
  background: rgba(23, 23, 23, 0.07);
  padding: 12px;
  border-radius: 12px;
  overflow-x: auto;
  margin: 8px 0;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: var(--soft-shadow);
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
  padding: 16px 24px 14px;
  background: var(--footer-bg);
  border-top: 1px solid var(--border-color);
  backdrop-filter: blur(22px) saturate(170%);
  -webkit-backdrop-filter: blur(22px) saturate(170%);
  box-shadow: inset 0 1px 0 var(--glass-border);
}

.input-area {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) 44px;
  gap: 12px;
  align-items: center;
}

.input-area textarea {
  flex: 1;
  width: 100%;
  height: 96px;
  min-height: 96px;
  padding: 14px 16px;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 18px;
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  box-sizing: border-box;
  box-shadow: var(--glass-shadow);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.input-area textarea:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: var(--glass-shadow), 0 0 0 3px rgba(47, 110, 244, 0.12);
}

.input-area textarea::placeholder {
  color: var(--text-muted);
}

/* CoT 切换按钮样式 */
.cot-toggle-btn {
  width: 44px;
  height: 44px;
  padding: 0;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  box-shadow: var(--soft-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.62);
  transition: transform 0.18s ease, background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
  flex-shrink: 0;
}

.cot-toggle-btn:hover {
  background: var(--hover-bg);
  transform: translateY(-1px);
  color: var(--text-primary);
}

.cot-toggle-btn.active {
  background: var(--primary-color);
  border-color: var(--primary-color);
  box-shadow: 0 14px 30px rgba(47, 110, 244, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.cot-toggle-btn.active .cot-icon {
  color: white;
}

.cot-icon {
  width: 18px;
  height: 18px;
}

/* 输入提示 */
.input-hints {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  padding: 0 4px;
  font-size: 11px;
  color: var(--text-secondary);
  flex-wrap: wrap;
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
  justify-content: space-between;
  align-self: center;
  height: 96px;
  gap: 0;
}

.btn-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  color: var(--text-secondary);
  cursor: pointer;
  box-shadow: var(--soft-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.62);
  transition: transform 0.18s ease, background 0.2s ease, color 0.2s ease;
}

.btn-clear:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
  transform: translateY(-1px);
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
  border-radius: 16px;
  color: white;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 14px 30px rgba(47, 110, 244, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.22);
  transition: transform 0.18s ease, opacity 0.2s;
}

.btn-send:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
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
  background: var(--glass-bg-strong);
  backdrop-filter: blur(24px) saturate(175%);
  -webkit-backdrop-filter: blur(24px) saturate(175%);
  border-left: 1px solid var(--border-color);
  box-shadow: -24px 0 60px rgba(17, 24, 39, 0.16), inset 1px 0 0 rgba(255, 255, 255, 0.45);
  z-index: 1000;
  transition: right 0.32s cubic-bezier(0.22, 1, 0.36, 1);
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
  background: rgba(23, 23, 23, 0.22);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  z-index: 999;
}

/* 双面板布局 */
.chat-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
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
  position: relative;
}
</style>
