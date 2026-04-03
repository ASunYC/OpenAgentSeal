/**
 * API layer following CoPaw's pattern
 * Provides REST API calls and SSE streaming
 */

import type { Chat, ChatHistory, Message, AgentEvent, AgentConfig, ModelConfig, SessionInfo, CommandInfo, AppSettings, ApiResponse, ProviderInfo, ProviderModelsResponse, UploadedFile } from '@/types'

const API_BASE = '/api'

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

  async get(chatId: string): Promise<Chat> {
    return request<Chat>(`/chats/${chatId}`)
  },

  async delete(chatId: string): Promise<void> {
    await request(`/chats/${chatId}`, { method: 'DELETE' })
  },

  async getHistory(chatId: string): Promise<ChatHistory> {
    return request<ChatHistory>(`/chats/${chatId}/history`)
  },
}

// SSE Streaming following CoPaw's pattern
export async function* runAgentStream(
  sessionId: string,
  messages: Message[],
  userId = 'default'
): AsyncGenerator<AgentEvent> {
  const response = await fetch(`${API_BASE}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      user_id: userId,
      messages,
      stream: true,
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

// Cancel running session
export async function cancelSession(sessionId: string): Promise<boolean> {
  const result = await request<{ success: boolean }>(`/cancel?session_id=${sessionId}`, {
    method: 'POST',
  })
  return result.success
}

// Agent API
export const agentApi = {
  async list(): Promise<AgentConfig[]> {
    return request<AgentConfig[]>('/agents')
  },

  async get(agentId: string): Promise<AgentConfig> {
    return request<AgentConfig>(`/agents/${agentId}`)
  },

  async save(agent: AgentConfig): Promise<ApiResponse<AgentConfig>> {
    return request<ApiResponse<AgentConfig>>('/agents', {
      method: 'POST',
      body: JSON.stringify(agent),
    })
  },

  async delete(agentId: string): Promise<ApiResponse<void>> {
    return request<ApiResponse<void>>(`/agents/${agentId}`, { method: 'DELETE' })
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
}

// Session API
export const sessionApi = {
  async list(agentId?: string): Promise<SessionInfo[]> {
    const query = agentId ? `?agent_id=${agentId}` : ''
    return request<SessionInfo[]>(`/sessions${query}`)
  },

  async get(sessionId: string): Promise<SessionInfo> {
    return request<SessionInfo>(`/sessions/${sessionId}`)
  },

  async getMessages(sessionId: string): Promise<Message[]> {
    return request<Message[]>(`/sessions/${sessionId}/messages`)
  },

  async delete(sessionId: string): Promise<ApiResponse<void>> {
    return request<ApiResponse<void>>(`/sessions/${sessionId}`, { method: 'DELETE' })
  },
}

// Command API
export const commandApi = {
  async list(): Promise<CommandInfo[]> {
    return request<CommandInfo[]>('/commands')
  },
}

// Settings API
export const settingsApi = {
  async get(): Promise<AppSettings> {
    return request<AppSettings>('/settings')
  },

  async save(settings: Partial<AppSettings>): Promise<ApiResponse<AppSettings>> {
    return request<ApiResponse<AppSettings>>('/settings', {
      method: 'POST',
      body: JSON.stringify(settings),
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

// Dashboard API
export const dashboardApi = {
  async getStats(): Promise<{
    totalSessions: number
    totalMessages: number
    activeAgents: number
    recentActivity: { date: string; count: number }[]
  }> {
    return request('/dashboard/stats')
  },
}

// Chat with agent (simple wrapper for streaming)
export async function chatWithAgent(
  agentId: string,
  message: string,
  onEvent: (event: AgentEvent) => void
): Promise<void> {
  const messages: Message[] = [{ role: 'user' as const, content: message }]
  
  for await (const event of runAgentStream(agentId, messages)) {
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
  }
}

// Export unified api object for stores
export const api = {
  // Chat
  getChats: chatApi.list,
  createChat: chatApi.create,
  getChat: chatApi.get,
  deleteChat: chatApi.delete,
  getChatHistory: chatApi.getHistory,

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

  // Provider
  getProviders: providerApi.list,
  getProviderModels: providerApi.getModels,

  // Session
  getSessions: sessionApi.list,
  getSession: sessionApi.get,
  getSessionMessages: sessionApi.getMessages,
  deleteSession: sessionApi.delete,

  // Command
  getCommands: commandApi.list,

  // Settings
  getSettings: settingsApi.get,
  saveSettings: settingsApi.save,
  getWorkDirectory: settingsApi.getWorkDirectory,
  setWorkDirectory: settingsApi.setWorkDirectory,

  // Dashboard
  getDashboardStats: dashboardApi.getStats,

  // Chat with agent (streaming)
  chat: chatWithAgent,

  // File Upload
  uploadFile: fileApi.upload,
}
