<template>
  <section class="sandbox-workspace">
    <div class="sandbox-cli-bar">
      <button
        v-for="provider in cliProviders"
        :key="provider.provider"
        type="button"
        class="sandbox-cli-button"
        :class="{ available: provider.available, running: isProviderRunning(provider.provider) }"
        :title="providerTooltip(provider)"
        :disabled="!canStartProvider"
        @click="startProvider(provider.provider)"
      >
        <span class="sandbox-status-dot"></span>
        <span>{{ providerLabel(provider.provider) }}</span>
        <span v-if="isProviderRunning(provider.provider)" class="sandbox-equalizer" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </span>
      </button>
      <button class="sandbox-refresh" type="button" :disabled="statusLoading" @click="loadCliStatus">
        {{ statusLoading ? t('检测中...', 'Checking...') : t('刷新', 'Refresh') }}
      </button>
    </div>

    <div v-if="statusError" class="sandbox-state error">{{ statusError }}</div>
    <div v-else-if="cliStatus && !cliStatus.windows" class="sandbox-state error">
      {{ t('沙盒终端第一版仅支持 Windows。', 'Sandbox terminal v1 only supports Windows.') }}
    </div>
    <div v-else-if="cliStatus && !cliStatus.pty_available" class="sandbox-state error">
      {{ t('缺少 pywinpty，安装后可启用内嵌交互式终端。', 'pywinpty is missing. Install it to enable embedded interactive terminals.') }}
    </div>
    <div v-else-if="cliStatus && !cliStatus.agent_switch_available" class="sandbox-state warning">
      {{ t('未找到 agent-switch 命令。请使用工程内置 agent-switch-skill 安装后重试。', 'agent-switch was not found. Install it from the bundled agent-switch-skill and try again.') }}
    </div>

    <div v-if="tabs.length" class="sandbox-terminal-shell">
      <div class="sandbox-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.localId"
          type="button"
          class="sandbox-tab"
          :class="{ active: tab.localId === activeTabId, exited: tab.exited }"
          @click="activateTab(tab.localId)"
        >
          <span>{{ providerLabel(tab.provider) }}</span>
          <small>{{ tab.exited ? t('已退出', 'Exited') : tab.sessionId ? t('运行中', 'Running') : t('启动中', 'Starting') }}</small>
          <span class="sandbox-tab-close" @click.stop="closeTab(tab.localId)">x</span>
        </button>
      </div>

      <div class="sandbox-terminal-stack">
        <div
          v-for="tab in tabs"
          :key="tab.localId"
          :ref="el => setTerminalRef(tab.localId, el)"
          class="sandbox-terminal"
          :class="{ active: tab.localId === activeTabId }"
        ></div>
      </div>
    </div>

    <div v-else class="sandbox-empty">
      <div class="sandbox-empty-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 17 10 11 4 5"/>
          <path d="M12 19h8"/>
        </svg>
      </div>
      <strong>{{ t('选择一个 CLI 启动沙盒终端', 'Choose a CLI to start a sandbox terminal') }}</strong>
      <p>{{ t('终端会在全局工作目录中运行，并通过 agent-switch 捕获 CLI 会话。', 'The terminal runs in the global workspace and uses agent-switch to capture CLI sessions.') }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { sandboxApi, type SandboxCliStatus, type SandboxProviderStatus } from '@/api'
import { useSettingsStore } from '@/stores/settings'
import { useSandboxStore, type SandboxProvider, type SandboxTabState } from '@/stores/sandbox'

interface SandboxTerminalRuntime {
  terminal: Terminal | null
  fitAddon: FitAddon | null
  socket: WebSocket | null
  dataDisposable: { dispose: () => void } | null
  exitNoticeWritten: boolean
}

const settingsStore = useSettingsStore()
const sandboxStore = useSandboxStore()
const { tabs, activeTabId } = storeToRefs(sandboxStore)
const statusLoading = ref(false)
const statusError = ref('')
const cliStatus = ref<SandboxCliStatus | null>(null)
const terminalElements = new Map<string, HTMLElement>()
const terminalRuntimes = new Map<string, SandboxTerminalRuntime>()
let resizeObserver: ResizeObserver | null = null

const fallbackProviders: SandboxProviderStatus[] = [
  'claude',
  'codex',
  'codewhale',
  'deepseek',
  'kimi',
  'opencode',
].map(provider => ({
  provider,
  label: provider,
  available: false,
  status: 'unknown',
  command: `agent-switch ${provider}`,
  target_command: provider,
}))

const cliProviders = computed(() => {
  return cliStatus.value?.providers?.length ? cliStatus.value.providers : fallbackProviders
})

const canStartProvider = computed(() => {
  return Boolean(cliStatus.value?.windows && cliStatus.value?.pty_available && cliStatus.value?.agent_switch_available)
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    claude: 'Claude',
    codex: 'Codex',
    codewhale: 'CodeWhale',
    deepseek: 'DeepSeek',
    kimi: 'Kimi',
    opencode: 'OpenCode',
  }
  return labels[provider] || provider
}

function providerTooltip(provider: SandboxProviderStatus): string {
  const base = `${provider.command} | ${provider.status}`
  if (provider.available) return base
  if (!cliStatus.value?.agent_switch_available) {
    return `${base}\n${t('需要先安装 agent-switch。', 'Install agent-switch first.')}`
  }
  return `${base}\n${t('目标 CLI 可能未安装，仍可由 agent-switch 输出具体错误。', 'The target CLI may be missing; agent-switch will show the detailed error.')}`
}

function isProviderRunning(provider: string): boolean {
  return tabs.value.some(tab => tab.provider === provider && !tab.exited)
}

function setTerminalRef(localId: string, element: unknown) {
  if (element instanceof HTMLElement) {
    terminalElements.set(localId, element)
    resizeObserver?.observe(element)
  } else {
    const previous = terminalElements.get(localId)
    if (previous) resizeObserver?.unobserve(previous)
    terminalElements.delete(localId)
  }
}

async function loadCliStatus() {
  statusLoading.value = true
  statusError.value = ''
  try {
    cliStatus.value = await sandboxApi.getCliStatus()
  } catch (error) {
    statusError.value = error instanceof Error ? error.message : String(error)
  } finally {
    statusLoading.value = false
  }
}

async function startProvider(provider: string) {
  if (!canStartProvider.value) return
  const typedProvider = provider as SandboxProvider
  const tab = sandboxStore.addTab(typedProvider)
  await nextTick()
  await attachTerminal(tab)
  await startSession(tab)
}

async function attachTerminal(tab: SandboxTabState) {
  const element = terminalElements.get(tab.localId)
  if (!element) return
  if (terminalRuntimes.get(tab.localId)?.terminal) return

  const terminal = new Terminal({
    cursorBlink: true,
    convertEol: true,
    fontFamily: 'Cascadia Mono, Consolas, monospace',
    fontSize: 13,
    theme: {
      background: '#0b1020',
      foreground: '#d9e2f2',
      cursor: '#7aa2ff',
      selectionBackground: '#2f4f88',
    },
  })
  const fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.open(element)

  const runtime: SandboxTerminalRuntime = {
    terminal,
    fitAddon,
    socket: null,
    dataDisposable: null,
    exitNoticeWritten: false,
  }
  terminalRuntimes.set(tab.localId, runtime)
  runtime.dataDisposable = terminal.onData(data => {
    if (runtime.socket?.readyState === WebSocket.OPEN) {
      runtime.socket.send(JSON.stringify({ type: 'input', data }))
    }
  })
  fitTerminal(tab, fitAddon)

  if (tab.sessionId) {
    connectSession(tab)
  } else if (tab.initializing) {
    terminal.writeln(`OpenAgentSeal sandbox: agent-switch ${tab.provider}`)
    terminal.writeln('')
  }
}

async function startSession(tab: SandboxTabState) {
  const runtime = terminalRuntimes.get(tab.localId)
  const terminal = runtime?.terminal
  if (!terminal) {
    sandboxStore.updateTab(tab.localId, { exited: true, initializing: false })
    return
  }
  try {
    const session = await sandboxApi.createSession(tab.provider, terminal.cols || 100, terminal.rows || 30)
    sandboxStore.updateTab(tab.localId, { sessionId: session.session_id })
    if (terminalRuntimes.get(tab.localId)?.terminal === terminal) {
      terminal.writeln(`cwd: ${session.cwd}`)
      terminal.writeln(`command: ${session.command}`)
      terminal.writeln('')
      connectSession({ ...tab, sessionId: session.session_id })
    }
  } catch (error) {
    sandboxStore.updateTab(tab.localId, { exited: true })
    if (terminalRuntimes.get(tab.localId)?.terminal === terminal) {
      terminal.writeln(`\x1b[31m${error instanceof Error ? error.message : String(error)}\x1b[0m`)
    }
  } finally {
    sandboxStore.updateTab(tab.localId, { initializing: false })
  }
}

function connectSession(tab: SandboxTabState) {
  const runtime = terminalRuntimes.get(tab.localId)
  if (!tab.sessionId || !runtime?.terminal) return
  if (runtime.socket && runtime.socket.readyState !== WebSocket.CLOSED) return

  const socket = new WebSocket(sandboxApi.sessionWebSocketUrl(tab.sessionId))
  runtime.socket = socket

  socket.addEventListener('open', () => {
    sendResize(tab)
  })
  socket.addEventListener('message', event => {
    const terminal = runtime.terminal
    if (!terminal) return
    try {
      const message = JSON.parse(String(event.data))
      if (message.type === 'output') {
        terminal.write(String(message.data || ''))
      } else if (message.type === 'exit') {
        sandboxStore.updateTab(tab.localId, { exited: true, initializing: false })
        if (!runtime.exitNoticeWritten) {
          runtime.exitNoticeWritten = true
          terminal.writeln('')
          terminal.writeln('\x1b[90m[process exited]\x1b[0m')
        }
      } else if (message.type === 'error') {
        terminal.writeln(`\x1b[31m${message.message || 'Sandbox error'}\x1b[0m`)
      }
    } catch {
      terminal.write(String(event.data))
    }
  })
  socket.addEventListener('close', () => {
    if (runtime.socket === socket) {
      runtime.socket = null
    }
  })
  socket.addEventListener('error', () => {
    runtime.terminal?.writeln('\x1b[31m[websocket error]\x1b[0m')
  })
}

function fitTerminal(tab: SandboxTabState, addon = terminalRuntimes.get(tab.localId)?.fitAddon) {
  const runtime = terminalRuntimes.get(tab.localId)
  if (!addon || !runtime?.terminal) return
  try {
    addon.fit()
    sendResize(tab)
  } catch {
    // xterm can throw while hidden; it will refit when activated.
  }
}

function sendResize(tab: SandboxTabState) {
  const runtime = terminalRuntimes.get(tab.localId)
  if (!runtime?.terminal || !runtime.socket || runtime.socket.readyState !== WebSocket.OPEN) return
  runtime.socket.send(JSON.stringify({
    type: 'resize',
    rows: runtime.terminal.rows,
    cols: runtime.terminal.cols,
  }))
}

async function activateTab(localId: string) {
  sandboxStore.activateTab(localId)
  await nextTick()
  const tab = tabs.value.find(item => item.localId === localId)
  if (tab) fitTerminal(tab)
}

async function closeTab(localId: string) {
  const index = tabs.value.findIndex(tab => tab.localId === localId)
  if (index === -1) return
  const tab = tabs.value[index]
  const runtime = terminalRuntimes.get(tab.localId)
  try {
    runtime?.socket?.send(JSON.stringify({ type: 'terminate' }))
  } catch {
    // Ignore websocket close races.
  }
  runtime?.socket?.close()
  if (tab.sessionId) {
    await sandboxApi.deleteSession(tab.sessionId).catch(() => undefined)
  }
  runtime?.dataDisposable?.dispose()
  runtime?.terminal?.dispose()
  terminalRuntimes.delete(tab.localId)
  sandboxStore.removeTab(localId)
  terminalElements.delete(localId)
  await nextTick()
  const active = tabs.value.find(item => item.localId === activeTabId.value)
  if (active) fitTerminal(active)
}

function refitActiveTerminal() {
  const active = tabs.value.find(tab => tab.localId === activeTabId.value)
  if (active) fitTerminal(active)
}

onMounted(() => {
  void loadCliStatus()
  resizeObserver = new ResizeObserver(() => refitActiveTerminal())
  nextTick(() => {
    for (const element of terminalElements.values()) {
      resizeObserver?.observe(element)
    }
    for (const tab of tabs.value) {
      void attachTerminal(tab)
    }
  })
  window.addEventListener('resize', refitActiveTerminal)
})

onUnmounted(() => {
  window.removeEventListener('resize', refitActiveTerminal)
  resizeObserver?.disconnect()
  for (const [localId, runtime] of terminalRuntimes) {
    runtime.socket?.close()
    runtime.dataDisposable?.dispose()
    runtime.terminal?.dispose()
    terminalRuntimes.delete(localId)
  }
  terminalElements.clear()
})
</script>

<style scoped>
.sandbox-workspace {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
}

.sandbox-cli-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.sandbox-cli-button,
.sandbox-refresh {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--hover-bg);
  color: var(--text-primary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
}

.sandbox-cli-button:hover:not(:disabled),
.sandbox-refresh:hover:not(:disabled) {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.sandbox-cli-button:disabled,
.sandbox-refresh:disabled {
  opacity: 0.58;
  cursor: default;
}

.sandbox-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #a0a8b8;
}

.sandbox-cli-button.available .sandbox-status-dot {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.12);
}

.sandbox-cli-button.running {
  border-color: color-mix(in srgb, var(--primary-color) 62%, var(--border-color));
  background: color-mix(in srgb, var(--primary-color) 9%, var(--main-bg));
  color: var(--primary-color);
}

.sandbox-equalizer {
  display: inline-flex;
  align-items: end;
  gap: 2px;
  height: 11px;
}

.sandbox-equalizer span {
  width: 2px;
  height: 5px;
  border-radius: 2px;
  background: currentColor;
  animation: sandbox-eq 0.8s ease-in-out infinite;
}

.sandbox-equalizer span:nth-child(2) {
  animation-delay: 0.12s;
}

.sandbox-equalizer span:nth-child(3) {
  animation-delay: 0.24s;
}

.sandbox-state {
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--hover-bg);
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.sandbox-state.error {
  border-color: rgba(239, 68, 68, 0.3);
  color: #ef4444;
}

.sandbox-state.warning {
  border-color: rgba(245, 158, 11, 0.36);
  color: #b45309;
}

.sandbox-terminal-shell {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: #0b1020;
}

.sandbox-tabs {
  display: flex;
  gap: 6px;
  padding: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  overflow-x: auto;
}

.sandbox-tab {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 180px;
  padding: 7px 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.04);
  color: #d9e2f2;
  cursor: pointer;
  font-size: 12px;
}

.sandbox-tab.active {
  border-color: #7aa2ff;
  background: rgba(122, 162, 255, 0.16);
}

.sandbox-tab.exited {
  opacity: 0.7;
}

.sandbox-tab small {
  color: #91a0b8;
  font-size: 10px;
}

.sandbox-tab-close {
  color: #91a0b8;
}

.sandbox-terminal-stack {
  position: relative;
  min-height: 0;
  flex: 1;
}

.sandbox-terminal {
  position: absolute;
  inset: 0;
  display: none;
  padding: 10px;
}

.sandbox-terminal.active {
  display: block;
}

.sandbox-empty {
  display: flex;
  min-height: 260px;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  border: 1px dashed var(--border-color);
  border-radius: 14px;
  background: color-mix(in srgb, var(--main-bg) 92%, var(--primary-color) 8%);
  color: var(--text-muted);
  text-align: center;
}

.sandbox-empty-icon {
  display: flex;
  width: 46px;
  height: 46px;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: color-mix(in srgb, var(--primary-color) 14%, transparent);
  color: var(--primary-color);
}

.sandbox-empty-icon svg {
  width: 24px;
  height: 24px;
}

.sandbox-empty strong {
  color: var(--text-primary);
  font-size: 14px;
}

.sandbox-empty p {
  max-width: 360px;
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
}

@keyframes sandbox-eq {
  0%, 100% {
    height: 4px;
  }
  50% {
    height: 11px;
  }
}
</style>
