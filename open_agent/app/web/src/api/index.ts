/**
 * API layer following CoPaw's pattern
 * Provides REST API calls and SSE streaming
 */

import type { Chat, ChatHistory, ContextBlockDetail, ContextBlockSummary, ContextCompactionStatus, RuntimeCapabilities, Message, AgentEvent, AgentConfig, ModelConfig, CommandInfo, AppSettings, ApiResponse, ProviderInfo, ProviderModelsResponse, ProviderDiagnosticResponse, UploadedFile, ForkChatResponse, RuntimeThread, RuntimeTurn, RuntimeEvent, SmartRoutingConfig, ChatAttachment, WorkspaceSource, WorkspaceSourceState, Workspace, FileEntry, WorkspaceSearchResult } from '@/types'
import { Capacitor } from '@capacitor/core'

const DESKTOP_BACKEND = 'http://127.0.0.1:9998'
const DEFAULT_CONTEXT_WINDOW = 1_000_000
const isTauriRuntime = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
export const isNativeMobileRuntime = Capacitor.isNativePlatform()
export const MOBILE_SERVER_STORAGE_KEY = 'open-agent-mobile-server'
export const API_BASE = isTauriRuntime ? `${DESKTOP_BACKEND}/api` : '/api'
const WS_BASE = isTauriRuntime
  ? 'ws://127.0.0.1:9998/api'
  : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api`

// Helper for API calls
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`)
  }
  return response.json()
}

export function normalizeMobileServerUrl(value: string): string {
  let normalized = value.trim()
  if (!normalized) return ''
  if (!/^https?:\/\//i.test(normalized)) normalized = `http://${normalized}`
  normalized = normalized.replace(/\/+$/, '')
  normalized = normalized.replace(/\/mobile(?:\?.*)?$/i, '')
  normalized = normalized.replace(/\/api$/i, '')
  return normalized
}

export function getMobileServerUrl(): string {
  if (!isNativeMobileRuntime) return window.location.origin
  return normalizeMobileServerUrl(localStorage.getItem(MOBILE_SERVER_STORAGE_KEY) || '')
}

export function setMobileServerUrl(value: string): string {
  const normalized = normalizeMobileServerUrl(value)
  if (normalized) {
    localStorage.setItem(MOBILE_SERVER_STORAGE_KEY, normalized)
  } else {
    localStorage.removeItem(MOBILE_SERVER_STORAGE_KEY)
  }
  return normalized
}

function mobileApiBase(): string {
  const server = getMobileServerUrl()
  return server ? `${server}/api` : API_BASE
}

async function mobileRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${mobileApiBase()}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`)
  }
  return response.json()
}

async function requestWithToken<T>(path: string, token: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${mobileApiBase()}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(options?.headers || {}),
    },
  })
  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`)
  }
  return response.json()
}

function profileQuery(profileId?: string): string {
  return profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ''
}

// Chat API
export const chatApi = {
  async list(userId?: string): Promise<Chat[]> {
    const query = userId ? `?user_id=${userId}` : ''
    return request<Chat[]>(`/chats${query}`)
  },

  async create(name = 'New Chat', userId = 'default'): Promise<Chat> {
    return request<Chat>('/chats', {
      method: 'POST',
      body: JSON.stringify({ name, user_id: userId }),
    })
  },

  async get(chatId: string, profileId?: string): Promise<Chat> {
    return request<Chat>(`/chats/${chatId}${profileQuery(profileId)}`)
  },

  async getByRunnerSession(runnerSessionId: string, profileId?: string): Promise<Chat> {
    return request<Chat>(`/chats/runner-channel/${encodeURIComponent(runnerSessionId)}${profileQuery(profileId)}`)
  },

  async delete(chatId: string, profileId?: string): Promise<void> {
    await request(`/chats/${chatId}${profileQuery(profileId)}`, { method: 'DELETE' })
  },

  async deleteMany(chatIds: string[], profileId?: string): Promise<{ success: boolean; deleted_count: number }> {
    return request<{ success: boolean; deleted_count: number }>(`/chats/delete${profileQuery(profileId)}`, {
      method: 'POST',
      body: JSON.stringify({ chat_ids: chatIds }),
    })
  },

  async getHistory(chatId: string, profileId?: string): Promise<ChatHistory> {
    return request<ChatHistory>(`/chats/${chatId}/history${profileQuery(profileId)}`)
  },

  async getContextStatus(runnerSessionId: string, profileId?: string): Promise<ContextCompactionStatus> {
    return request<ContextCompactionStatus>(
      `/chats/session/${encodeURIComponent(runnerSessionId)}/context-status${profileQuery(profileId)}`,
    )
  },

  async listContextBlocks(runnerSessionId: string, profileId?: string): Promise<ContextBlockSummary[]> {
    const query = new URLSearchParams()
    if (profileId) query.set('profile_id', profileId)
    query.set('limit', '200')
    const response = await request<{ blocks: ContextBlockSummary[] }>(
      `/chats/session/${encodeURIComponent(runnerSessionId)}/context-blocks?${query.toString()}`,
    )
    return response.blocks || []
  },

  async getContextBlock(runnerSessionId: string, refId: string, profileId?: string): Promise<ContextBlockDetail> {
    const query = new URLSearchParams()
    query.set('ref_id', refId)
    query.set('max_chars', '120000')
    if (profileId) query.set('profile_id', profileId)
    return request<ContextBlockDetail>(
      `/chats/session/${encodeURIComponent(runnerSessionId)}/context-block?${query.toString()}`,
    )
  },

  async clearMessages(runnerSessionId: string, profileId?: string): Promise<void> {
    await request(`/chats/session/${encodeURIComponent(runnerSessionId)}/messages${profileQuery(profileId)}`, { method: 'DELETE' })
  },

  async persistMessages(runnerSessionId: string, messages: Message[], profileId?: string): Promise<void> {
    await request(`/chats/session/${encodeURIComponent(runnerSessionId)}/messages${profileQuery(profileId)}`, {
      method: 'POST',
      body: JSON.stringify({ messages }),
    })
  },

  async fork(runnerSessionId: string, name?: string, profileId?: string): Promise<ForkChatResponse> {
    return request<ForkChatResponse>('/chats/fork', {
      method: 'POST',
      body: JSON.stringify({
        session_id: runnerSessionId,
        name,
        profile_id: profileId,
      }),
    })
  },
}

// SSE Streaming following CoPaw's pattern
export async function* runAgentStream(
  runnerSessionId: string,
  messages: Message[],
  userId = 'default',
  workspaceSources: WorkspaceSource[] = [],
  selectedWorkspacePaths: string[] = [],
  toolAccessMode: 'default' | 'full' = 'default',
  profileId = 'main',
): AsyncGenerator<AgentEvent> {
  const response = await fetch(`${API_BASE}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: runnerSessionId,
      user_id: userId,
      messages,
      stream: true,
      workspace_sources: workspaceSources,
      selected_workspace_paths: selectedWorkspacePaths,
      tool_access_mode: toolAccessMode,
      profile_id: profileId,
    }),
  })

  if (!response.ok) {
    throw new Error(`Run failed: ${response.status}`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          console.log('[API Debug] SSE event:', data)
          yield data
        } catch (e) {
          // Skip invalid JSON
          console.warn('[API Debug] Failed to parse SSE:', line, e)
        }
      }
    }
  }
}

// Cancel a running chat in the runner.
export async function cancelRunnerChat(runnerSessionId: string): Promise<boolean> {
  const result = await request<{ success: boolean }>(`/cancel?session_id=${runnerSessionId}`, {
    method: 'POST',
  })
  return result.success
}

export const runtimeApi = {
  async listThreads(userId?: string): Promise<RuntimeThread[]> {
    const query = userId ? `?user_id=${encodeURIComponent(userId)}` : ''
    const result = await request<{ threads: RuntimeThread[] }>(`/runtime/threads${query}`)
    return result.threads
  },

  async getThreadBySession(runnerSessionId: string): Promise<RuntimeThread> {
    return request<RuntimeThread>(`/runtime/threads/session/${encodeURIComponent(runnerSessionId)}`)
  },

  async getThread(threadId: string): Promise<RuntimeThread> {
    return request<RuntimeThread>(`/runtime/threads/${encodeURIComponent(threadId)}`)
  },

  async listTurns(threadId: string): Promise<RuntimeTurn[]> {
    const result = await request<{ turns: RuntimeTurn[] }>(`/runtime/threads/${encodeURIComponent(threadId)}/turns`)
    return result.turns
  },

  async listEvents(threadId: string, sinceSeq = 0, limit = 1000): Promise<RuntimeEvent[]> {
    const params = new URLSearchParams({
      since_seq: String(sinceSeq),
      limit: String(limit),
    })
    const result = await request<{ events: RuntimeEvent[] }>(
      `/runtime/threads/${encodeURIComponent(threadId)}/events?${params.toString()}`,
    )
    return result.events
  },
}

export interface SandboxProviderStatus {
  provider: string
  label: string
  available: boolean
  status: string
  command: string
  target_command: string
}

export interface SandboxCliStatus {
  windows: boolean
  pty_available: boolean
  agent_switch_available: boolean
  workspace: string
  providers: SandboxProviderStatus[]
}

export interface SandboxSession {
  session_id: string
  provider: string
  cwd: string
  command: string
}

export const sandboxApi = {
  async getCliStatus(): Promise<SandboxCliStatus> {
    return request<SandboxCliStatus>('/sandbox/cli-status')
  },

  async createSession(provider: string, cols: number, rows: number): Promise<SandboxSession> {
    return request<SandboxSession>('/sandbox/sessions', {
      method: 'POST',
      body: JSON.stringify({ provider, cols, rows }),
    })
  },

  async deleteSession(sessionId: string): Promise<{ success: boolean }> {
    return request<{ success: boolean }>(`/sandbox/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    })
  },

  sessionWebSocketUrl(sessionId: string): string {
    return `${WS_BASE}/sandbox/sessions/${encodeURIComponent(sessionId)}/ws`
  },
}

export interface MobileAccessInfo {
  success: boolean
  mobile_path: string
  bind_host: string
  remote_enabled: boolean
  local_urls: string[]
  lan_urls: string[]
  pairing_ttl_seconds: number
  paired_devices: Array<{
    id: string
    name: string
    created_at?: string
    last_seen_at?: string
    enabled: boolean
  }>
}

export interface MobilePairingCode {
  success: boolean
  code: string
  expires_at: string
  mobile_url: string
  mobile_urls: string[]
}

export interface MobileSummary {
  success: boolean
  device: {
    id: string
    name: string
    created_at?: string
    last_seen_at?: string
    enabled: boolean
  }
  agents: AgentConfig[]
  chats: Chat[]
  running_tasks: Record<string, unknown>[]
  server_time: string
}

export const mobileApi = {
  async health(serverUrl?: string): Promise<{ status: string; ready: boolean }> {
    if (serverUrl !== undefined) setMobileServerUrl(serverUrl)
    return mobileRequest<{ status: string; ready: boolean }>('/health')
  },

  async getAccessInfo(): Promise<MobileAccessInfo> {
    return request<MobileAccessInfo>('/mobile/access-info')
  },

  async createPairingCode(): Promise<MobilePairingCode> {
    return request<MobilePairingCode>('/mobile/pairing-code', { method: 'POST' })
  },

  async pair(code: string, deviceName: string): Promise<{ success: boolean; token: string; device: MobileSummary['device'] }> {
    return mobileRequest<{ success: boolean; token: string; device: MobileSummary['device'] }>('/mobile/pair', {
      method: 'POST',
      body: JSON.stringify({ code, device_name: deviceName }),
    })
  },

  async getSummary(token: string, profileId = 'main'): Promise<MobileSummary> {
    return requestWithToken<MobileSummary>(`/mobile/summary?profile_id=${encodeURIComponent(profileId)}`, token)
  },

  async getChatHistory(token: string, chatId: string, profileId = 'main'): Promise<ChatHistory> {
    const result = await requestWithToken<{ success: boolean; chat_id: string; total: number; messages: Message[] }>(
      `/mobile/chats/${encodeURIComponent(chatId)}/history?profile_id=${encodeURIComponent(profileId)}`,
      token,
    )
    return { chat_id: result.chat_id, total: result.total, messages: result.messages }
  },

  async createChat(token: string, name = 'Mobile Chat', profileId = 'main'): Promise<Chat> {
    return requestWithToken<Chat>('/mobile/chats', token, {
      method: 'POST',
      body: JSON.stringify({ name, profile_id: profileId }),
    })
  },

  async revokeDevice(deviceId: string): Promise<{ success: boolean; device_id: string }> {
    return request<{ success: boolean; device_id: string }>(`/mobile/devices/${encodeURIComponent(deviceId)}`, {
      method: 'DELETE',
    })
  },

  async cancel(token: string, sessionId: string): Promise<{ success: boolean; session_id: string }> {
    return requestWithToken<{ success: boolean; session_id: string }>(`/cancel?session_id=${encodeURIComponent(sessionId)}`, token, {
      method: 'POST',
    })
  },

  async *runAgentStream(token: string, runnerSessionId: string, content: string, profileId = 'main'): AsyncGenerator<AgentEvent> {
    const response = await fetch(`${mobileApiBase()}/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        session_id: runnerSessionId,
        user_id: 'mobile',
        messages: [{ role: 'user', content }],
        stream: true,
        profile_id: profileId,
      }),
    })
    if (!response.ok) {
      throw new Error(`Run failed: ${response.status}`)
    }
    const reader = response.body?.getReader()
    if (!reader) throw new Error('No response body')
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          yield JSON.parse(line.slice(6)) as AgentEvent
        } catch {
          // Ignore malformed SSE frames.
        }
      }
    }
  },
}

// Agent API
export const agentApi = {
  async list(): Promise<AgentConfig[]> {
    const main = await request<AgentConfig>('/main-agent')
    const profiles = await request<AgentConfig[]>('/agent-profiles')
    return [main, ...profiles]
  },

  async get(agentId: string): Promise<AgentConfig> {
    if (agentId === 'main') {
      return request<AgentConfig>('/main-agent')
    }
    return request<AgentConfig>(`/agent-profiles/${encodeURIComponent(agentId)}`)
  },

  async save(agent: AgentConfig): Promise<ApiResponse<AgentConfig>> {
    const isMain = agent.id === 'main'
    const existing = isMain ? true : await request<AgentConfig[]>(`/agent-profiles`)
      .then(items => items.some(item => item.id === agent.id))
      .catch(() => false)
    const url = isMain
      ? '/main-agent'
      : existing
        ? `/agent-profiles/${encodeURIComponent(agent.id)}`
        : '/agent-profiles'
    return request<ApiResponse<AgentConfig>>(url, {
      method: isMain || existing ? 'PATCH' : 'POST',
      body: JSON.stringify(agent),
    })
  },

  async delete(agentId: string): Promise<ApiResponse<void>> {
    if (agentId === 'main') {
      return { success: false, error: 'Main agent cannot be deleted' } as ApiResponse<void>
    }
    return request<ApiResponse<void>>(`/agent-profiles/${encodeURIComponent(agentId)}`, { method: 'DELETE' })
  },

  async listProfileSkills(agentId: string): Promise<{ profile_id: string; skills_dir: string; skills: Array<{ name: string; description: string; path: string; content: string }> }> {
    return request(`/agent-profiles/${encodeURIComponent(agentId)}/skills`)
  },

  async saveProfileSkill(agentId: string, skill: { name: string; description: string; content: string }): Promise<ApiResponse<{ name: string; path: string }>> {
    return request<ApiResponse<{ name: string; path: string }>>(`/agent-profiles/${encodeURIComponent(agentId)}/skills`, {
      method: 'POST',
      body: JSON.stringify(skill),
    })
  },

  async deleteProfileSkill(agentId: string, skillName: string): Promise<ApiResponse<void>> {
    return request<ApiResponse<void>>(`/agent-profiles/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillName)}`, {
      method: 'DELETE',
    })
  },

  async getProfileMcp(agentId: string): Promise<{ profile_id: string; path: string; config: Record<string, unknown> }> {
    return request(`/agent-profiles/${encodeURIComponent(agentId)}/mcp`)
  },

  async saveProfileMcp(agentId: string, config: Record<string, unknown>): Promise<ApiResponse<{ path: string; config: Record<string, unknown> }>> {
    return request<ApiResponse<{ path: string; config: Record<string, unknown> }>>(`/agent-profiles/${encodeURIComponent(agentId)}/mcp`, {
      method: 'PUT',
      body: JSON.stringify({ config }),
    })
  },
}

// Model Config API - 后端直接返回数组
export const modelConfigApi = {
  async list(): Promise<ModelConfig[]> {
    // 后端直接返回 ModelConfig[] 数组
    return request<ModelConfig[]>('/model-configs')
  },

  async save(config: ModelConfig): Promise<ApiResponse<ModelConfig>> {
    return request<ApiResponse<ModelConfig>>('/model-configs', {
      method: 'POST',
      body: JSON.stringify(config),
    })
  },

  async delete(configId: string): Promise<ApiResponse<void>> {
    return request<ApiResponse<void>>(`/model-configs/${configId}`, { method: 'DELETE' })
  },

  async setDefault(configId: string): Promise<ApiResponse<void>> {
    return request<ApiResponse<void>>(`/model-configs/${configId}/default`, { method: 'POST' })
  },

  async diagnose(configId: string): Promise<ProviderDiagnosticResponse> {
    return request<ProviderDiagnosticResponse>(`/model-configs/${configId}/diagnostics`)
  },

  async resolveContextWindow(modelName: string, provider = ''): Promise<{
    model_name: string
    provider: string
    context_window: number
    source: string
  }> {
    const query = new URLSearchParams({ model_name: modelName, provider })
    return request(`/models/context-window?${query.toString()}`)
  },
}

// Provider API - 提供商相关接口
export const providerApi = {
  /**
   * 获取所有提供商列表
   */
  async list(): Promise<ProviderInfo[]> {
    return request<ProviderInfo[]>('/providers')
  },

  /**
   * 获取指定提供商的可用模型列表
   * @param provider - 提供商名称（如 openai, anthropic）
   */
  async getModels(provider: string): Promise<ProviderModelsResponse> {
    return request<ProviderModelsResponse>(`/providers/${provider}/models`)
  },

  async diagnose(provider: string, config: Partial<ModelConfig>): Promise<ProviderDiagnosticResponse> {
    return request<ProviderDiagnosticResponse>(`/providers/${provider}/diagnostics`, {
      method: 'POST',
      body: JSON.stringify(config),
    })
  },
}

// Command API
export const commandApi = {
  async list(): Promise<CommandInfo[]> {
    return request<CommandInfo[]>('/commands')
  },
}

// Settings API
interface BackendAppSettings {
  language?: string
  theme?: string
  font_size?: string
  workspace?: string
  auto_save?: boolean
  stream_response?: boolean
  enable_skills?: boolean
  use_cot?: boolean
  auto_context_compaction?: boolean
  context_compaction_token_limit?: number
}

export const settingsApi = {
  async get(): Promise<AppSettings> {
    const data = await request<BackendAppSettings>('/settings')
    return {
      language: (data.language as AppSettings['language']) || 'zh-CN',
      theme: (data.theme as AppSettings['theme']) || 'light',
      fontSize: (data.font_size as AppSettings['fontSize']) || 'medium',
      workspace: data.workspace || '',
      autoSave: data.auto_save ?? true,
      streamResponse: data.stream_response ?? true,
      enable_skills: data.enable_skills ?? true,
      useCoT: data.use_cot ?? false,
      autoContextCompaction: data.auto_context_compaction ?? true,
      contextCompactionTokenLimit: data.context_compaction_token_limit ?? DEFAULT_CONTEXT_WINDOW,
    }
  },

  async save(settings: Partial<AppSettings>): Promise<ApiResponse<AppSettings>> {
    const payload: Record<string, unknown> = {}
    if (settings.language !== undefined) payload.language = settings.language
    if (settings.theme !== undefined) payload.theme = settings.theme
    if (settings.fontSize !== undefined) payload.font_size = settings.fontSize
    if (settings.workspace !== undefined) payload.workspace = settings.workspace
    if (settings.autoSave !== undefined) payload.auto_save = settings.autoSave
    if (settings.streamResponse !== undefined) payload.stream_response = settings.streamResponse
    if (settings.enable_skills !== undefined) payload.enable_skills = settings.enable_skills
    if (settings.useCoT !== undefined) payload.use_cot = settings.useCoT
    if (settings.autoContextCompaction !== undefined) {
      payload.auto_context_compaction = settings.autoContextCompaction
    }
    if (settings.contextCompactionTokenLimit !== undefined) {
      payload.context_compaction_token_limit = settings.contextCompactionTokenLimit
    }

    return request<ApiResponse<AppSettings>>('/settings', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async getWorkDirectory(): Promise<{ path: string }> {
    return request<{ path: string }>('/settings/work-directory')
  },

  async setWorkDirectory(path: string): Promise<ApiResponse<void>> {
    return request<ApiResponse<void>>('/settings/work-directory', {
      method: 'POST',
      body: JSON.stringify({ path }),
    })
  },
}

export const smartRoutingApi = {
  async get(): Promise<SmartRoutingConfig> {
    return request<SmartRoutingConfig>('/smart-routing')
  },

  async save(config: SmartRoutingConfig): Promise<ApiResponse<SmartRoutingConfig>> {
    return request<ApiResponse<SmartRoutingConfig>>('/smart-routing', {
      method: 'POST',
      body: JSON.stringify(config),
    })
  },
}

export interface WebSearchProviderStatus {
  name: string
  display_name: string
  supports_search: boolean
  supports_extract: boolean
  available: boolean
  requires_key: boolean
  note?: string
}

export interface WebSearchConfig {
  enabled: boolean
  search_backend: string
  extract_backend: string
  searxng_url: string
  api_keys: Record<string, string>
}

export interface WebSearchConfigResponse {
  success: boolean
  config: WebSearchConfig
  search_status: Record<string, WebSearchProviderStatus>
  extract_status: Record<string, WebSearchProviderStatus>
  error?: string
}

export const webSearchApi = {
  async getConfig(): Promise<WebSearchConfigResponse> {
    return request<WebSearchConfigResponse>('/web-search/config')
  },

  async saveConfig(config: WebSearchConfig): Promise<WebSearchConfigResponse> {
    return request<WebSearchConfigResponse>('/web-search/config', {
      method: 'POST',
      body: JSON.stringify(config),
    })
  },
}

export interface SkillConfig {
  name: string
  original_name?: string
  icon?: string
  description: string
  enabled: boolean
  path?: string
  source?: 'builtin' | 'plugin' | string
  source_label?: string
  plugin_id?: string | null
}

export const skillsApi = {
  async list(): Promise<SkillConfig[]> {
    return request<SkillConfig[]>('/skills')
  },

  async setEnabled(path: string, enabled: boolean): Promise<ApiResponse<{ path: string; enabled: boolean }>> {
    return request<ApiResponse<{ path: string; enabled: boolean }>>('/skills/config', {
      method: 'POST',
      body: JSON.stringify({ path, enabled }),
    })
  },
}

export interface MCPServerConfig {
  name: string
  original_name?: string
  type: 'stdio' | 'http' | 'sse' | string
  command?: string
  url?: string
  args?: string[]
  env?: Record<string, string>
  cwd?: string
  disabled?: boolean
  source?: 'user' | 'plugin' | string
  plugin_id?: string | null
  readonly?: boolean
  [key: string]: unknown
}

export const mcpApi = {
  async getConfig(): Promise<{ success: boolean; path: string; servers: MCPServerConfig[]; warnings?: Record<string, unknown>[]; error?: string }> {
    return request('/mcp/config')
  },

  async saveConfig(servers: MCPServerConfig[]): Promise<ApiResponse<{ path: string }>> {
    return request<ApiResponse<{ path: string }>>('/mcp/config', {
      method: 'POST',
      body: JSON.stringify({ servers }),
    })
  },

  async setPluginServerEnabled(pluginId: string, serverName: string, enabled: boolean): Promise<ApiResponse<{ plugin_id: string; server_name: string; enabled: boolean }>> {
    return request<ApiResponse<{ plugin_id: string; server_name: string; enabled: boolean }>>('/mcp/plugin-server', {
      method: 'POST',
      body: JSON.stringify({ plugin_id: pluginId, server_name: serverName, enabled }),
    })
  },
}

export interface PluginSummary {
  id: string
  name: string
  marketplace_name: string
  installed: boolean
  enabled: boolean
  local_version?: string | null
  install_policy?: string
  auth_policy?: string
  interface?: {
    displayName?: string
    display_name?: string
    shortDescription?: string
    short_description?: string
    longDescription?: string
    long_description?: string
    developerName?: string
    developer_name?: string
    category?: string
    capabilities?: string[]
    brandColor?: string
    brand_color?: string
    logo?: string
  }
  keywords?: string[]
}

export interface PluginMarketplace {
  name: string
  path?: string
  kind?: string
  interface?: { displayName?: string; display_name?: string }
  plugins: PluginSummary[]
}

export interface PluginDetail {
  marketplace_name: string
  marketplace_path?: string
  summary: PluginSummary
  description?: string | null
  skills: SkillConfig[]
  mcp_servers: { name: string; enabled: boolean; config: Record<string, unknown> }[]
  apps: unknown
  hooks: unknown
  settings?: {
    schema?: {
      title?: string
      description?: string
      fields: PluginSettingField[]
    } | null
    values: Record<string, unknown>
  }
}

export interface PluginSettingField {
  key: string
  type: 'text' | 'url' | 'secret' | 'model' | 'select' | 'boolean'
  label?: string
  description?: string
  default?: unknown
  required?: boolean
  options?: Array<{ label: string; value: string }>
}

export const pluginsApi = {
  async list(): Promise<{ success: boolean; marketplaces: PluginMarketplace[]; marketplace_load_errors?: { marketplace_name?: string; message: string }[] }> {
    return request('/plugins')
  },

  async read(pluginId: string): Promise<{ success: boolean; plugin: PluginDetail; error?: string }> {
    return request(`/plugins/${encodeURIComponent(pluginId)}`)
  },

  async install(pluginName: string, marketplaceName: string): Promise<ApiResponse<{ plugin_id: string; installed_version: string; installed_path: string }>> {
    return request('/plugins/install', {
      method: 'POST',
      body: JSON.stringify({ plugin_name: pluginName, marketplace_name: marketplaceName }),
    })
  },

  async uninstall(pluginId: string): Promise<ApiResponse<unknown>> {
    return request(`/plugins/${encodeURIComponent(pluginId)}`, { method: 'DELETE' })
  },

  async setEnabled(pluginId: string, enabled: boolean): Promise<ApiResponse<{ plugin_id: string; enabled: boolean }>> {
    return request(`/plugins/${encodeURIComponent(pluginId)}/${enabled ? 'enable' : 'disable'}`, { method: 'POST' })
  },

  async saveSettings(pluginId: string, values: Record<string, unknown>): Promise<{ success: boolean; plugin_id?: string; values?: Record<string, unknown>; error?: string }> {
    return request(`/plugins/${encodeURIComponent(pluginId)}/settings`, {
      method: 'PUT',
      body: JSON.stringify({ values }),
    })
  },

  async listMarketplaces(): Promise<{ success: boolean; marketplaces: { name: string; path: string; plugin_count: number; kind: string }[]; errors?: { marketplace_name?: string; message: string }[] }> {
    return request('/plugins/marketplaces')
  },

  async addMarketplace(source: string): Promise<ApiResponse<{ marketplace_name: string; path: string; installed_root?: string | null; already_added: boolean }>> {
    return request('/plugins/marketplaces', {
      method: 'POST',
      body: JSON.stringify({ source }),
    })
  },

  async removeMarketplace(name: string): Promise<ApiResponse<unknown>> {
    return request(`/plugins/marketplaces/${encodeURIComponent(name)}`, { method: 'DELETE' })
  },

  async upgradeMarketplaces(marketplaceName?: string): Promise<ApiResponse<unknown>> {
    return request('/plugins/marketplaces/upgrade', {
      method: 'POST',
      body: JSON.stringify({ marketplace_name: marketplaceName }),
    })
  },
}

export const logsApi = {
  async list(): Promise<{
    success: boolean
    path: string
    files: { name: string; path: string; size: number; updated_at: string; tail: string[] }[]
    error?: string
  }> {
    return request('/logs')
  },
}

export const tasksApi = {
  async list(): Promise<{
    success: boolean
    status: Record<string, unknown>
    tasks: Record<string, unknown>[]
    running: Record<string, unknown>[]
    pending: Record<string, unknown>[]
    completed: Record<string, unknown>[]
    error?: string
  }> {
    return request('/tasks')
  },
}

export const versionApi = {
  async get(): Promise<{ success: boolean; version: string; release_date: string; error?: string }> {
    return request('/version')
  },
}

export const runtimeCapabilitiesApi = {
  async get(): Promise<RuntimeCapabilities> {
    return request('/runtime/capabilities')
  },
}

// Dashboard API
export const dashboardApi = {
  async getStats(): Promise<{
    totalChats: number
    totalMessages: number
    activeAgents: number
    recentActivity: { date: string; count: number }[]
  }> {
    const data = await request<{
      total_chats?: number
      total_messages?: number
      active_agents?: number
      recent_activity?: { date: string; count: number }[]
    }>('/dashboard/stats')
    return {
      totalChats: data.total_chats ?? 0,
      totalMessages: data.total_messages ?? 0,
      activeAgents: data.active_agents ?? 0,
      recentActivity: data.recent_activity ?? [],
    }
  },
}

// Chat with agent (simple wrapper for streaming)
export async function chatWithAgent(
  runnerSessionId: string,
  message: string,
  onEvent: (event: AgentEvent) => void,
  attachments: ChatAttachment[] = [],
  workspaceSources: WorkspaceSource[] = [],
  selectedWorkspacePaths: string[] = [],
  toolAccessMode: 'default' | 'full' = 'default',
  profileId = 'main',
): Promise<void> {
  const messages: Message[] = [{ role: 'user' as const, content: message, attachments }]
  
  for await (const event of runAgentStream(runnerSessionId, messages, 'default', workspaceSources, selectedWorkspacePaths, toolAccessMode, profileId)) {
    onEvent(event)
  }
}

// File Upload API
export const fileApi = {
  /**
   * 上传文件
   */
  async upload(file: File): Promise<UploadedFile> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(`${API_BASE}/files/upload`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      throw new Error(`Upload failed: ${response.status}`)
    }
    return response.json()
  },

  async createLocalAttachments(paths: string[]): Promise<{ attachments: ChatAttachment[]; rejected: Array<{ path: string; reason: string }> }> {
    return request<{ attachments: ChatAttachment[]; rejected: Array<{ path: string; reason: string }> }>('/files/local-attachments', {
      method: 'POST',
      body: JSON.stringify({ paths }),
    })
  },

  async createWorkspaceSources(paths: string[]): Promise<{ sources: WorkspaceSource[]; rejected: Array<{ path: string; reason: string }> }> {
    return request<{ sources: WorkspaceSource[]; rejected: Array<{ path: string; reason: string }> }>('/workspace/local-sources', {
      method: 'POST',
      body: JSON.stringify({ paths }),
    })
  },

  async getWorkspaceSourcesState(): Promise<WorkspaceSourceState> {
    return request<WorkspaceSourceState>('/workspace/sources')
  },

  async saveWorkspaceSourcesState(state: WorkspaceSourceState): Promise<WorkspaceSourceState> {
    return request<WorkspaceSourceState>('/workspace/sources', {
      method: 'POST',
      body: JSON.stringify(state),
    })
  }
}

// ── Workspace Resource Manager API ──

export const workspaceApi = {
  // Workspace CRUD
  async listWorkspaces(): Promise<{ workspaces: Workspace[] }> {
    return request(`/workspace/`)
  },

  async createWorkspace(name: string, path?: string): Promise<{ workspace: Workspace }> {
    return request(`/workspace/`, {
      method: 'POST',
      body: JSON.stringify({ name, path }),
    })
  },

  async updateWorkspace(id: string, updates: { name?: string; path?: string }): Promise<{ workspace: Workspace }> {
    return request(`/workspace/${id}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    })
  },

  async deleteWorkspace(id: string): Promise<{ status: string }> {
    return request(`/workspace/${id}`, { method: 'DELETE' })
  },

  async setCurrentWorkspace(id: string): Promise<{ status: string }> {
    return request(`/workspace/${id}/set-current`, { method: 'PUT' })
  },

  // File operations
  async listFiles(wsId: string, path?: string): Promise<{ path: string; ws_path: string; files: FileEntry[] }> {
    const params = path ? `?path=${encodeURIComponent(path)}` : ''
    return request(`/workspace/${wsId}/files${params}`)
  },

  async readFile(wsId: string, path: string, offset?: number, limit?: number): Promise<{ ok: boolean; path: string; content: string; size: number }> {
    const params = new URLSearchParams({ path })
    if (offset !== undefined) params.set('offset', String(offset))
    if (limit !== undefined) params.set('limit', String(limit))
    return request(`/workspace/${wsId}/read?${params}`)
  },

  async writeFile(wsId: string, path: string, content: string): Promise<{ ok: boolean; path: string; size: number }> {
    return request(`/workspace/${wsId}/write`, {
      method: 'POST',
      body: JSON.stringify({ path, content }),
    })
  },

  async deleteFile(wsId: string, path: string): Promise<{ ok: boolean; path: string }> {
    return request(`/workspace/${wsId}/delete`, {
      method: 'POST',
      body: JSON.stringify({ path }),
    })
  },

  async mkdir(wsId: string, path: string): Promise<{ ok: boolean; path: string }> {
    return request(`/workspace/${wsId}/mkdir`, {
      method: 'POST',
      body: JSON.stringify({ path }),
    })
  },

  async rename(wsId: string, path: string, newName: string): Promise<{ ok: boolean; old_path: string; new_path: string }> {
    return request(`/workspace/${wsId}/rename`, {
      method: 'POST',
      body: JSON.stringify({ path, name: newName }),
    })
  },

  async upload(wsId: string, file: File, destPath?: string): Promise<{ ok: boolean; path: string; size: number }> {
    const formData = new FormData()
    formData.append('file', file)
    if (destPath) formData.append('dest_path', destPath)
    const res = await fetch(`${API_BASE}/workspace/${wsId}/upload`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`)
    return res.json()
  },

  // Search
  async search(wsId: string, pattern: string, path?: string): Promise<{ query: string; results: WorkspaceSearchResult[] }> {
    return request(`/workspace/${wsId}/search`, {
      method: 'POST',
      body: JSON.stringify({ pattern, path }),
    })
  },

  async glob(wsId: string, pattern: string): Promise<{ pattern: string; files: string[] }> {
    return request(`/workspace/${wsId}/glob`, {
      method: 'POST',
      body: JSON.stringify({ pattern }),
    })
  },

  async searchAll(pattern: string): Promise<{ query: string; results: any[] }> {
    return request(`/workspace/search-all`, {
      method: 'POST',
      body: JSON.stringify({ pattern }),
    })
  },
}

// Export unified api object for stores
export const api = {
  // Chat
  getChats: chatApi.list,
  createChat: chatApi.create,
  getChat: chatApi.get,
  getChatByRunnerSession: chatApi.getByRunnerSession,
  deleteChat: chatApi.delete,
  deleteChats: chatApi.deleteMany,
  getChatHistory: chatApi.getHistory,
  getChatContextStatus: chatApi.getContextStatus,
  listChatContextBlocks: chatApi.listContextBlocks,
  getChatContextBlock: chatApi.getContextBlock,
  clearChatMessages: chatApi.clearMessages,
  persistChatMessages: chatApi.persistMessages,
  forkChat: chatApi.fork,

  // Agent
  getAgents: agentApi.list,
  getAgent: agentApi.get,
  saveAgent: agentApi.save,
  deleteAgent: agentApi.delete,

  // Model Config
  getModelConfigs: modelConfigApi.list,
  saveModelConfig: modelConfigApi.save,
  deleteModelConfig: modelConfigApi.delete,
  setDefaultModelConfig: modelConfigApi.setDefault,
  diagnoseModelConfig: modelConfigApi.diagnose,
  resolveModelContextWindow: modelConfigApi.resolveContextWindow,

  // Provider
  getProviders: providerApi.list,
  getProviderModels: providerApi.getModels,
  diagnoseProvider: providerApi.diagnose,

  // Command
  getCommands: commandApi.list,

  // Settings
  getSettings: settingsApi.get,
  saveSettings: settingsApi.save,
  getWorkDirectory: settingsApi.getWorkDirectory,
  setWorkDirectory: settingsApi.setWorkDirectory,
  getSmartRouting: smartRoutingApi.get,
  saveSmartRouting: smartRoutingApi.save,
  getWebSearchConfig: webSearchApi.getConfig,
  saveWebSearchConfig: webSearchApi.saveConfig,

  // MCP
  getMcpConfig: mcpApi.getConfig,
  saveMcpConfig: mcpApi.saveConfig,

  // Logs / Tasks
  getLogs: logsApi.list,
  getTasks: tasksApi.list,
  getRuntimeCapabilities: runtimeCapabilitiesApi.get,

  // Runtime event replay
  getRuntimeThreads: runtimeApi.listThreads,
  getRuntimeThreadBySession: runtimeApi.getThreadBySession,
  getRuntimeThread: runtimeApi.getThread,
  getRuntimeTurns: runtimeApi.listTurns,
  getRuntimeEvents: runtimeApi.listEvents,

  // Sandbox
  getSandboxCliStatus: sandboxApi.getCliStatus,
  createSandboxSession: sandboxApi.createSession,
  deleteSandboxSession: sandboxApi.deleteSession,

  // Version
  getVersion: versionApi.get,

  // Dashboard
  getDashboardStats: dashboardApi.getStats,

  // Chat with agent (streaming)
  chat: chatWithAgent,
  cancelRunnerChat,

  // File Upload
  uploadFile: fileApi.upload,
  createLocalAttachments: fileApi.createLocalAttachments,
  createWorkspaceSources: fileApi.createWorkspaceSources,
  getWorkspaceSourcesState: fileApi.getWorkspaceSourcesState,
  saveWorkspaceSourcesState: fileApi.saveWorkspaceSourcesState,

  // Workspace Resource Manager
  listWorkspaces: workspaceApi.listWorkspaces,
  createWorkspace: workspaceApi.createWorkspace,
  updateWorkspace: workspaceApi.updateWorkspace,
  deleteWorkspace: workspaceApi.deleteWorkspace,
  setCurrentWorkspace: workspaceApi.setCurrentWorkspace,
  listWorkspaceFiles: workspaceApi.listFiles,
  readWorkspaceFile: workspaceApi.readFile,
  writeWorkspaceFile: workspaceApi.writeFile,
  deleteWorkspaceFile: workspaceApi.deleteFile,
  createWorkspaceFolder: workspaceApi.mkdir,
  renameWorkspaceItem: workspaceApi.rename,
  uploadWorkspaceFile: workspaceApi.upload,
  searchWorkspace: workspaceApi.search,
  globWorkspace: workspaceApi.glob,
  searchAllWorkspaces: workspaceApi.searchAll,
}
