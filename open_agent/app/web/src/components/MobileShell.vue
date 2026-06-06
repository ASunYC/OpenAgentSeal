<template>
  <main class="mobile-shell">
    <section v-if="!token" class="pairing-view">
      <div class="pairing-brand">
        <img :src="appIconUrl" alt="" />
        <div>
          <h1>OpenAgentSeal</h1>
          <p>移动工作台</p>
        </div>
      </div>

      <div class="pairing-panel">
        <div class="panel-title">
          <span class="step-number">1</span>
          <div>
            <h2>连接你的电脑</h2>
            <p>电脑端 OpenAgentSeal 必须保持运行</p>
          </div>
        </div>

        <label v-if="isNativeMobileRuntime" class="field-label" for="server-url">电脑地址</label>
        <div v-if="isNativeMobileRuntime" class="server-row">
          <input
            id="server-url"
            v-model="serverUrl"
            inputmode="url"
            placeholder="例如 192.168.1.20:9998"
            autocomplete="url"
            @blur="saveServer"
          />
          <button type="button" class="secondary-button" :disabled="connectionState === 'checking'" @click="checkServer">
            {{ connectionState === 'checking' ? '检测中' : '检测' }}
          </button>
        </div>
        <p v-if="isNativeMobileRuntime" class="field-hint">
          与电脑连接同一个局域网，地址可在电脑端“设置 → 移动端”中查看。
        </p>

        <div class="panel-title pairing-step">
          <span class="step-number">2</span>
          <div>
            <h2>输入配对码</h2>
            <p>配对码由电脑端生成，有效期 3 分钟</p>
          </div>
        </div>

        <label class="field-label" for="pairing-code">6 位配对码</label>
        <input
          id="pairing-code"
          v-model="pairingCode"
          class="code-input"
          inputmode="numeric"
          maxlength="6"
          placeholder="000000"
          autocomplete="one-time-code"
          @keyup.enter="pair"
        />

        <button
          type="button"
          class="primary-button connect-button"
          :disabled="pairingBusy || pairingCode.length !== 6 || (isNativeMobileRuntime && !serverUrl.trim())"
          @click="pair"
        >
          {{ pairingBusy ? '正在连接…' : '连接电脑' }}
        </button>

        <p v-if="pairingError" class="error-text">{{ pairingError }}</p>
        <div class="security-note">
          <span class="security-icon">✓</span>
          <span>设备令牌只保存在当前设备，电脑端可以随时撤销访问。</span>
        </div>
      </div>
    </section>

    <section v-else class="mobile-console">
      <header class="mobile-header">
        <div class="header-brand">
          <img :src="appIconUrl" alt="" />
          <div>
            <strong>OpenAgentSeal</strong>
            <span :class="['connection-label', connectionState]">
              <i></i>
              {{ connectionLabel }}
            </span>
          </div>
        </div>
        <button type="button" class="icon-button" title="刷新" :disabled="loading" @click="refresh">
          ↻
        </button>
      </header>

      <div v-if="connectionState === 'offline'" class="offline-banner">
        <span>与电脑的连接已断开，当前内容仍保留在手机上。</span>
        <button type="button" @click="refresh">重试</button>
      </div>

      <nav class="agent-rail" aria-label="智能体">
        <button
          v-for="agent in summary?.agents || []"
          :key="agent.id"
          type="button"
          class="agent-chip"
          :class="{ active: agent.id === selectedAgentId }"
          @click="selectAgent(agent.id)"
        >
          <span class="agent-avatar">{{ agent.name.slice(0, 1) }}</span>
          <span>{{ agent.name }}</span>
          <i v-if="isRunning && agent.id === selectedAgentId" class="working-dot"></i>
        </button>
      </nav>

      <section v-if="activeView === 'chats'" class="content-view chat-index">
        <div class="view-heading">
          <div>
            <h1>{{ selectedAgent?.name || '默认助手' }}</h1>
            <p>{{ summary?.chats.length || 0 }} 个会话</p>
          </div>
          <button type="button" class="primary-button compact" :disabled="loading" @click="createChat">
            新建会话
          </button>
        </div>

        <div v-if="loading && !summary" class="center-state">正在连接电脑…</div>
        <div v-else-if="!summary?.chats.length" class="center-state">
          <strong>还没有会话</strong>
          <span>为 {{ selectedAgent?.name || '当前智能体' }} 创建第一个移动会话。</span>
          <button type="button" class="primary-button" @click="createChat">开始新会话</button>
        </div>
        <div v-else class="chat-list">
          <button
            v-for="chat in summary.chats"
            :key="chat.id"
            type="button"
            class="chat-row"
            @click="selectChat(chat)"
          >
            <span class="chat-icon">▢</span>
            <span class="chat-copy">
              <strong>{{ chat.name }}</strong>
              <small>{{ formatDate(chat.updated_at) }}</small>
            </span>
            <span class="row-arrow">›</span>
          </button>
        </div>
      </section>

      <section v-else-if="activeView === 'conversation'" class="content-view conversation-view">
        <div class="conversation-heading">
          <button type="button" class="back-button" @click="activeView = 'chats'">‹</button>
          <div>
            <strong>{{ selectedChat?.name || '会话' }}</strong>
            <span>{{ selectedAgent?.name || '默认助手' }}</span>
          </div>
          <button v-if="isRunning" type="button" class="stop-button" @click="stopRun">停止</button>
        </div>

        <div ref="messagesElement" class="messages">
          <article
            v-for="(message, index) in messages"
            :key="`${message.role}-${index}-${message.timestamp || ''}`"
            class="message"
            :class="message.role"
          >
            <span>{{ message.role === 'user' ? '你' : selectedAgent?.name || 'OpenAgentSeal' }}</span>
            <p>{{ messageText(message) }}</p>
          </article>
          <div v-if="!messages.length" class="center-state compact-state">发送一条消息开始协作。</div>
          <div v-if="isRunning" class="running-indicator">
            <i></i><i></i><i></i>
            <span>{{ selectedAgent?.name || '智能体' }} 正在工作</span>
          </div>
        </div>

        <form class="composer" @submit.prevent="sendMessage">
          <textarea
            v-model="draft"
            rows="2"
            :disabled="!selectedChat || isRunning"
            placeholder="输入消息…"
            @keydown.enter.exact.prevent="sendMessage"
          ></textarea>
          <button
            v-if="isRunning"
            type="button"
            class="send-button stop"
            title="停止"
            @click="stopRun"
          >
            ■
          </button>
          <button
            v-else
            type="submit"
            class="send-button"
            title="发送"
            :disabled="!selectedChat || !draft.trim()"
          >
            ↑
          </button>
        </form>
      </section>

      <section v-else-if="activeView === 'tasks'" class="content-view task-view">
        <div class="view-heading">
          <div>
            <h1>运行任务</h1>
            <p>{{ summary?.running_tasks.length || 0 }} 个正在运行</p>
          </div>
        </div>
        <div v-if="summary?.running_tasks.length" class="task-list">
          <div
            v-for="task in summary.running_tasks"
            :key="String(task.id || task.task_id || task.session_id)"
            class="task-row"
          >
            <span class="task-pulse"></span>
            <div>
              <strong>{{ String(task.title || task.name || task.task_id || '运行中') }}</strong>
              <small>{{ String(task.status || 'running') }}</small>
            </div>
          </div>
        </div>
        <div v-else class="center-state">
          <strong>当前没有运行任务</strong>
          <span>智能体开始工作后，状态会显示在这里。</span>
        </div>
      </section>

      <section v-else class="content-view device-view">
        <div class="view-heading">
          <div>
            <h1>当前设备</h1>
            <p>{{ summary?.device.name || 'Mobile Device' }}</p>
          </div>
        </div>
        <dl class="device-details">
          <div>
            <dt>连接地址</dt>
            <dd>{{ currentServerLabel }}</dd>
          </div>
          <div>
            <dt>最近同步</dt>
            <dd>{{ formatDate(summary?.server_time) || '-' }}</dd>
          </div>
          <div>
            <dt>设备状态</dt>
            <dd>{{ connectionLabel }}</dd>
          </div>
        </dl>
        <button type="button" class="disconnect-button" @click="disconnect(false)">断开当前设备</button>
        <button
          v-if="isNativeMobileRuntime"
          type="button"
          class="change-server-button"
          @click="disconnect(true)"
        >
          更换电脑
        </button>
      </section>

      <p v-if="error" class="floating-error">{{ error }}</p>

      <footer v-if="activeView !== 'conversation'" class="mobile-nav">
        <button type="button" :class="{ active: activeView === 'chats' }" @click="activeView = 'chats'">
          <span>▤</span>
          会话
        </button>
        <button type="button" :class="{ active: activeView === 'tasks' }" @click="activeView = 'tasks'">
          <span>◫</span>
          任务
        </button>
        <button type="button" :class="{ active: activeView === 'device' }" @click="activeView = 'device'">
          <span>◎</span>
          设备
        </button>
      </footer>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
  getMobileServerUrl,
  isNativeMobileRuntime,
  mobileApi,
  setMobileServerUrl,
} from '@/api'
import type { AgentConfig, Chat, Message } from '@/types'
import appIconUrl from '@/assets/icon.png'

type MobileView = 'chats' | 'conversation' | 'tasks' | 'device'
type ConnectionState = 'connected' | 'checking' | 'offline'

const TOKEN_STORAGE_KEY = 'open-agent-mobile-token'
const AGENT_STORAGE_KEY = 'open-agent-mobile-agent'
const token = ref(localStorage.getItem(TOKEN_STORAGE_KEY) || '')
const serverUrl = ref(getMobileServerUrl())
const summary = ref<Awaited<ReturnType<typeof mobileApi.getSummary>> | null>(null)
const selectedAgentId = ref(localStorage.getItem(AGENT_STORAGE_KEY) || 'main')
const selectedChat = ref<Chat | null>(null)
const messages = ref<Message[]>([])
const messagesElement = ref<HTMLElement | null>(null)
const draft = ref('')
const activeView = ref<MobileView>('chats')
const loading = ref(false)
const isRunning = ref(false)
const error = ref('')
const pairingCode = ref(new URLSearchParams(window.location.search).get('code') || '')
const pairingBusy = ref(false)
const pairingError = ref('')
const connectionState = ref<ConnectionState>(navigator.onLine ? 'checking' : 'offline')
let refreshTimer: number | undefined

const selectedAgent = computed<AgentConfig | null>(() => {
  return summary.value?.agents.find(agent => agent.id === selectedAgentId.value) || null
})

const connectionLabel = computed(() => {
  if (connectionState.value === 'connected') return '已连接电脑'
  if (connectionState.value === 'checking') return '正在连接'
  return '连接已断开'
})

const currentServerLabel = computed(() => {
  return isNativeMobileRuntime ? getMobileServerUrl() || '-' : window.location.origin
})

function deviceName(): string {
  const platform = navigator.userAgent.includes('Android')
    ? 'Android'
    : navigator.userAgent.includes('iPhone') || navigator.userAgent.includes('iPad')
      ? 'iOS'
      : 'Mobile'
  return `${platform} Device`
}

function messageText(message: Message): string {
  if (typeof message.content === 'string') return message.content
  return String(message.content || '')
}

function formatDate(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function readableError(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err)
  if (message.includes('401')) return '配对已失效，请在电脑端重新生成配对码。'
  if (message.includes('Failed to fetch') || message.includes('NetworkError')) {
    return '无法连接电脑，请检查电脑地址、局域网和防火墙。'
  }
  return message
}

function saveServer(): void {
  if (!isNativeMobileRuntime) return
  serverUrl.value = setMobileServerUrl(serverUrl.value)
}

async function checkServer(): Promise<boolean> {
  if (isNativeMobileRuntime) saveServer()
  if (isNativeMobileRuntime && !serverUrl.value) {
    pairingError.value = '请先输入电脑地址。'
    return false
  }
  connectionState.value = 'checking'
  pairingError.value = ''
  try {
    await mobileApi.health(serverUrl.value)
    connectionState.value = 'connected'
    return true
  } catch (err) {
    connectionState.value = 'offline'
    pairingError.value = readableError(err)
    return false
  }
}

async function pair(): Promise<void> {
  const code = pairingCode.value.trim()
  if (!/^\d{6}$/.test(code)) return
  pairingBusy.value = true
  pairingError.value = ''
  try {
    if (!(await checkServer())) return
    const result = await mobileApi.pair(code, deviceName())
    token.value = result.token
    localStorage.setItem(TOKEN_STORAGE_KEY, result.token)
    window.history.replaceState({}, '', isNativeMobileRuntime ? '/' : '/mobile')
    await refresh()
  } catch (err) {
    pairingError.value = readableError(err)
  } finally {
    pairingBusy.value = false
  }
}

async function refresh(): Promise<void> {
  if (!token.value || loading.value) return
  loading.value = true
  error.value = ''
  connectionState.value = 'checking'
  try {
    const nextSummary = await mobileApi.getSummary(token.value, selectedAgentId.value)
    summary.value = nextSummary
    connectionState.value = 'connected'
    if (!nextSummary.agents.some(agent => agent.id === selectedAgentId.value)) {
      selectedAgentId.value = nextSummary.agents[0]?.id || 'main'
      localStorage.setItem(AGENT_STORAGE_KEY, selectedAgentId.value)
      summary.value = await mobileApi.getSummary(token.value, selectedAgentId.value)
    }
    if (selectedChat.value) {
      selectedChat.value = summary.value.chats.find(chat => chat.id === selectedChat.value?.id) || null
      if (!selectedChat.value && activeView.value === 'conversation') activeView.value = 'chats'
    }
  } catch (err) {
    connectionState.value = 'offline'
    error.value = readableError(err)
    if ((err instanceof Error ? err.message : String(err)).includes('401')) {
      disconnect(false)
      pairingError.value = '当前设备访问已被撤销，请重新配对。'
    }
  } finally {
    loading.value = false
  }
}

async function selectAgent(agentId: string): Promise<void> {
  if (agentId === selectedAgentId.value) return
  selectedAgentId.value = agentId
  localStorage.setItem(AGENT_STORAGE_KEY, agentId)
  selectedChat.value = null
  messages.value = []
  activeView.value = 'chats'
  await refresh()
}

async function selectChat(chat: Chat): Promise<void> {
  selectedChat.value = chat
  messages.value = []
  error.value = ''
  activeView.value = 'conversation'
  try {
    const history = await mobileApi.getChatHistory(token.value, chat.id, selectedAgentId.value)
    messages.value = history.messages
    await scrollMessages()
  } catch (err) {
    error.value = readableError(err)
  }
}

async function createChat(): Promise<void> {
  error.value = ''
  try {
    const chat = await mobileApi.createChat(
      token.value,
      `${selectedAgent.value?.name || 'OpenAgentSeal'} 移动会话`,
      selectedAgentId.value,
    )
    await refresh()
    await selectChat(chat)
  } catch (err) {
    error.value = readableError(err)
  }
}

async function sendMessage(): Promise<void> {
  const chat = selectedChat.value
  const content = draft.value.trim()
  if (!chat || !content || isRunning.value) return

  draft.value = ''
  isRunning.value = true
  error.value = ''
  messages.value.push({ role: 'user', content, timestamp: new Date().toISOString() })
  const assistantMessage: Message = {
    role: 'assistant',
    content: '',
    timestamp: new Date().toISOString(),
  }
  messages.value.push(assistantMessage)
  await scrollMessages()

  try {
    for await (const event of mobileApi.runAgentStream(
      token.value,
      chat.session_id,
      content,
      selectedAgentId.value,
    )) {
      if (event.event === 'message' && event.content) {
        assistantMessage.content = `${assistantMessage.content || ''}${event.content}`
        await scrollMessages()
      } else if (event.event === 'complete' && event.content) {
        assistantMessage.content = event.content
      } else if (event.event === 'error') {
        throw new Error(event.error || '智能体运行失败')
      }
    }
    connectionState.value = 'connected'
    await selectChat(chat)
    await refresh()
  } catch (err) {
    connectionState.value = navigator.onLine ? connectionState.value : 'offline'
    error.value = readableError(err)
  } finally {
    isRunning.value = false
  }
}

async function stopRun(): Promise<void> {
  if (!selectedChat.value) return
  await mobileApi.cancel(token.value, selectedChat.value.session_id).catch(() => undefined)
  isRunning.value = false
  await refresh()
}

async function scrollMessages(): Promise<void> {
  await nextTick()
  if (messagesElement.value) {
    messagesElement.value.scrollTop = messagesElement.value.scrollHeight
  }
}

function disconnect(clearServer: boolean): void {
  token.value = ''
  summary.value = null
  selectedChat.value = null
  messages.value = []
  activeView.value = 'chats'
  localStorage.removeItem(TOKEN_STORAGE_KEY)
  if (clearServer && isNativeMobileRuntime) {
    setMobileServerUrl('')
    serverUrl.value = ''
  }
}

function handleOnline(): void {
  connectionState.value = 'checking'
  void refresh()
}

function handleOffline(): void {
  connectionState.value = 'offline'
}

function handleVisibility(): void {
  if (document.visibilityState === 'visible') void refresh()
}

onMounted(() => {
  if (isNativeMobileRuntime && token.value && !serverUrl.value) {
    disconnect(false)
  }
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)
  document.addEventListener('visibilitychange', handleVisibility)
  refreshTimer = window.setInterval(() => {
    if (!isRunning.value && document.visibilityState === 'visible') void refresh()
  }, 15_000)

  if (token.value) {
    void refresh()
  } else if (pairingCode.value && (!isNativeMobileRuntime || serverUrl.value)) {
    void pair()
  }
})

onUnmounted(() => {
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
  document.removeEventListener('visibilitychange', handleVisibility)
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
})
</script>

<style scoped>
.mobile-shell {
  --mobile-bg: #f4f6f9;
  --mobile-surface: #ffffff;
  --mobile-surface-muted: #eef2f7;
  --mobile-border: #dce2ea;
  --mobile-text: #111827;
  --mobile-secondary: #64748b;
  --mobile-primary: #2563eb;
  --mobile-primary-soft: #e8f0ff;
  --mobile-danger: #dc2626;
  min-height: 100dvh;
  background: var(--mobile-bg);
  color: var(--mobile-text);
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

button,
input,
textarea {
  font: inherit;
}

button {
  cursor: pointer;
}

button:disabled {
  cursor: default;
  opacity: 0.5;
}

.pairing-view {
  width: min(100%, 480px);
  margin: 0 auto;
  padding: calc(36px + env(safe-area-inset-top)) 20px calc(24px + env(safe-area-inset-bottom));
}

.pairing-brand {
  display: flex;
  margin-bottom: 28px;
  align-items: center;
  gap: 12px;
}

.pairing-brand img,
.header-brand img {
  width: 46px;
  height: 46px;
  border-radius: 8px;
  object-fit: cover;
}

.pairing-brand h1,
.pairing-brand p,
.panel-title h2,
.panel-title p,
.view-heading h1,
.view-heading p {
  margin: 0;
}

.pairing-brand h1 {
  font-size: 22px;
}

.pairing-brand p,
.panel-title p,
.view-heading p {
  margin-top: 3px;
  color: var(--mobile-secondary);
  font-size: 13px;
}

.pairing-panel {
  padding: 20px;
  border: 1px solid var(--mobile-border);
  border-radius: 8px;
  background: var(--mobile-surface);
  box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
}

.panel-title {
  display: flex;
  margin-bottom: 20px;
  align-items: center;
  gap: 12px;
}

.pairing-step {
  margin-top: 26px;
}

.step-number {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 50%;
  background: var(--mobile-primary-soft);
  color: var(--mobile-primary);
  font-size: 13px;
  font-weight: 800;
}

.panel-title h2 {
  font-size: 16px;
}

.field-label {
  display: block;
  margin-bottom: 7px;
  font-size: 13px;
  font-weight: 700;
}

.field-hint {
  margin: 7px 0 0;
  color: var(--mobile-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.server-row {
  display: flex;
  gap: 8px;
}

input,
textarea {
  width: 100%;
  border: 1px solid var(--mobile-border);
  border-radius: 8px;
  outline: none;
  background: var(--mobile-surface);
  color: var(--mobile-text);
}

input:focus,
textarea:focus {
  border-color: var(--mobile-primary);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

input {
  height: 46px;
  padding: 0 13px;
}

.code-input {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.32em;
  text-align: center;
}

.primary-button,
.secondary-button {
  min-height: 42px;
  padding: 0 15px;
  border: 1px solid var(--mobile-primary);
  border-radius: 8px;
  background: var(--mobile-primary);
  color: #ffffff;
  font-weight: 750;
}

.secondary-button {
  background: var(--mobile-surface);
  color: var(--mobile-primary);
}

.connect-button {
  width: 100%;
  margin-top: 16px;
}

.security-note {
  display: flex;
  margin-top: 18px;
  align-items: flex-start;
  gap: 8px;
  color: var(--mobile-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.security-icon {
  color: #16a34a;
  font-weight: 800;
}

.error-text,
.floating-error {
  color: var(--mobile-danger);
  font-size: 13px;
}

.mobile-console {
  display: flex;
  min-height: 100dvh;
  flex-direction: column;
}

.mobile-header {
  position: sticky;
  z-index: 20;
  top: 0;
  display: flex;
  min-height: calc(62px + env(safe-area-inset-top));
  padding: calc(10px + env(safe-area-inset-top)) 16px 10px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--mobile-border);
  background: color-mix(in srgb, var(--mobile-surface) 94%, transparent);
  backdrop-filter: blur(16px);
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-brand img {
  width: 38px;
  height: 38px;
}

.header-brand strong,
.header-brand span {
  display: block;
}

.header-brand strong {
  font-size: 15px;
}

.connection-label {
  margin-top: 2px;
  color: var(--mobile-secondary);
  font-size: 11px;
}

.connection-label i {
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 5px;
  border-radius: 50%;
  background: #94a3b8;
}

.connection-label.connected i {
  background: #22c55e;
}

.connection-label.checking i {
  background: #f59e0b;
}

.connection-label.offline i {
  background: #ef4444;
}

.icon-button,
.back-button {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border: 1px solid var(--mobile-border);
  border-radius: 8px;
  background: var(--mobile-surface);
  color: var(--mobile-text);
  font-size: 22px;
}

.offline-banner {
  display: flex;
  padding: 9px 14px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #fff7ed;
  color: #9a3412;
  font-size: 12px;
}

.offline-banner button {
  border: 0;
  background: transparent;
  color: inherit;
  font-weight: 800;
}

.agent-rail {
  display: flex;
  padding: 10px 12px;
  gap: 8px;
  overflow-x: auto;
  border-bottom: 1px solid var(--mobile-border);
  background: var(--mobile-surface);
  scrollbar-width: none;
}

.agent-rail::-webkit-scrollbar {
  display: none;
}

.agent-chip {
  position: relative;
  display: flex;
  min-height: 40px;
  padding: 5px 12px 5px 6px;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--mobile-border);
  border-radius: 8px;
  background: var(--mobile-surface);
  color: var(--mobile-text);
}

.agent-chip.active {
  border-color: var(--mobile-primary);
  background: var(--mobile-primary-soft);
  color: var(--mobile-primary);
}

.agent-avatar {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 7px;
  background: var(--mobile-surface-muted);
  font-size: 12px;
  font-weight: 800;
}

.working-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
  animation: pulse 1s ease-in-out infinite;
}

.content-view {
  width: min(100%, 720px);
  margin: 0 auto;
  padding: 18px 16px calc(86px + env(safe-area-inset-bottom));
  flex: 1;
}

.view-heading {
  display: flex;
  margin-bottom: 18px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.view-heading h1 {
  font-size: 20px;
}

.primary-button.compact {
  min-height: 38px;
  font-size: 13px;
}

.chat-list,
.task-list {
  overflow: hidden;
  border: 1px solid var(--mobile-border);
  border-radius: 8px;
  background: var(--mobile-surface);
}

.chat-row {
  display: flex;
  width: 100%;
  min-height: 64px;
  padding: 10px 12px;
  align-items: center;
  gap: 11px;
  border: 0;
  border-bottom: 1px solid var(--mobile-border);
  background: transparent;
  color: var(--mobile-text);
  text-align: left;
}

.chat-row:last-child {
  border-bottom: 0;
}

.chat-row:active {
  background: var(--mobile-surface-muted);
}

.chat-icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 8px;
  background: var(--mobile-primary-soft);
  color: var(--mobile-primary);
}

.chat-copy {
  min-width: 0;
  flex: 1;
}

.chat-copy strong,
.chat-copy small {
  display: block;
}

.chat-copy strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-copy small,
.task-row small {
  margin-top: 4px;
  color: var(--mobile-secondary);
  font-size: 11px;
}

.row-arrow {
  color: var(--mobile-secondary);
  font-size: 24px;
}

.center-state {
  display: flex;
  min-height: 48vh;
  padding: 32px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 10px;
  color: var(--mobile-secondary);
  text-align: center;
}

.center-state strong {
  color: var(--mobile-text);
}

.compact-state {
  min-height: 220px;
}

.conversation-view {
  display: flex;
  height: calc(100dvh - 120px - env(safe-area-inset-top));
  padding: 0;
  flex-direction: column;
}

.conversation-heading {
  display: grid;
  min-height: 58px;
  padding: 8px 12px;
  grid-template-columns: 38px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--mobile-border);
  background: var(--mobile-surface);
}

.conversation-heading > div strong,
.conversation-heading > div span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-heading > div strong {
  font-size: 14px;
}

.conversation-heading > div span {
  margin-top: 2px;
  color: var(--mobile-secondary);
  font-size: 11px;
}

.stop-button {
  padding: 7px 10px;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: #fff1f2;
  color: var(--mobile-danger);
  font-size: 12px;
  font-weight: 750;
}

.messages {
  display: flex;
  padding: 16px;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.message {
  max-width: 88%;
  align-self: flex-start;
}

.message.user {
  align-self: flex-end;
}

.message > span {
  display: block;
  margin: 0 4px 5px;
  color: var(--mobile-secondary);
  font-size: 10px;
}

.message.user > span {
  text-align: right;
}

.message p {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--mobile-border);
  border-radius: 8px;
  background: var(--mobile-surface);
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.message.user p {
  border-color: var(--mobile-primary);
  background: var(--mobile-primary);
  color: #ffffff;
}

.running-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--mobile-secondary);
  font-size: 11px;
}

.running-indicator i {
  width: 3px;
  height: 12px;
  background: var(--mobile-primary);
  animation: equalizer 0.8s ease-in-out infinite alternate;
}

.running-indicator i:nth-child(2) {
  animation-delay: 0.15s;
}

.running-indicator i:nth-child(3) {
  animation-delay: 0.3s;
}

.running-indicator span {
  margin-left: 5px;
}

.composer {
  display: grid;
  padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  grid-template-columns: minmax(0, 1fr) 44px;
  align-items: end;
  gap: 8px;
  border-top: 1px solid var(--mobile-border);
  background: var(--mobile-surface);
}

.composer textarea {
  min-height: 44px;
  max-height: 120px;
  padding: 11px 12px;
  resize: none;
}

.send-button {
  width: 44px;
  height: 44px;
  border: 1px solid var(--mobile-primary);
  border-radius: 8px;
  background: var(--mobile-primary);
  color: #ffffff;
  font-size: 20px;
  font-weight: 800;
}

.send-button.stop {
  border-color: var(--mobile-danger);
  background: var(--mobile-danger);
  font-size: 13px;
}

.task-row {
  display: flex;
  min-height: 64px;
  padding: 12px;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid var(--mobile-border);
}

.task-row:last-child {
  border-bottom: 0;
}

.task-row strong,
.task-row small {
  display: block;
}

.task-pulse {
  width: 10px;
  height: 10px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: #22c55e;
  animation: pulse 1s ease-in-out infinite;
}

.device-details {
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--mobile-border);
  border-radius: 8px;
  background: var(--mobile-surface);
}

.device-details > div {
  display: grid;
  min-height: 52px;
  padding: 10px 12px;
  grid-template-columns: 92px minmax(0, 1fr);
  align-items: center;
  border-bottom: 1px solid var(--mobile-border);
}

.device-details > div:last-child {
  border-bottom: 0;
}

.device-details dt {
  color: var(--mobile-secondary);
  font-size: 12px;
}

.device-details dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: 13px;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.disconnect-button,
.change-server-button {
  width: 100%;
  min-height: 44px;
  margin-top: 14px;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: var(--mobile-surface);
  color: var(--mobile-danger);
  font-weight: 750;
}

.change-server-button {
  margin-top: 8px;
  border-color: var(--mobile-border);
  color: var(--mobile-text);
}

.floating-error {
  position: fixed;
  z-index: 30;
  right: 12px;
  bottom: calc(76px + env(safe-area-inset-bottom));
  left: 12px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: #fff1f2;
  box-shadow: 0 8px 24px rgba(127, 29, 29, 0.12);
}

.mobile-nav {
  position: fixed;
  z-index: 20;
  right: 0;
  bottom: 0;
  left: 0;
  display: grid;
  min-height: calc(62px + env(safe-area-inset-bottom));
  padding-bottom: env(safe-area-inset-bottom);
  grid-template-columns: repeat(3, 1fr);
  border-top: 1px solid var(--mobile-border);
  background: color-mix(in srgb, var(--mobile-surface) 95%, transparent);
  backdrop-filter: blur(16px);
}

.mobile-nav button {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 2px;
  border: 0;
  background: transparent;
  color: var(--mobile-secondary);
  font-size: 10px;
}

.mobile-nav button span {
  font-size: 19px;
}

.mobile-nav button.active {
  color: var(--mobile-primary);
  font-weight: 750;
}

@keyframes pulse {
  50% {
    opacity: 0.35;
    transform: scale(0.78);
  }
}

@keyframes equalizer {
  from {
    height: 5px;
  }
  to {
    height: 14px;
  }
}

@media (prefers-color-scheme: dark) {
  .mobile-shell {
    --mobile-bg: #101318;
    --mobile-surface: #171b22;
    --mobile-surface-muted: #202630;
    --mobile-border: #303744;
    --mobile-text: #f3f4f6;
    --mobile-secondary: #9ca3af;
    --mobile-primary: #5d8cff;
    --mobile-primary-soft: #202e4d;
  }

  .offline-banner {
    background: #3b2417;
    color: #fdba74;
  }

  .stop-button,
  .floating-error {
    border-color: #7f1d1d;
    background: #32181b;
  }
}

@media (min-width: 760px) {
  .mobile-console {
    width: 720px;
    min-height: 100dvh;
    margin: 0 auto;
    border-right: 1px solid var(--mobile-border);
    border-left: 1px solid var(--mobile-border);
    background: var(--mobile-bg);
  }

  .mobile-nav {
    right: 50%;
    left: 50%;
    width: 718px;
    transform: translateX(-50%);
  }
}
</style>
