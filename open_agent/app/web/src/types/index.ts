/**
 * TypeScript types matching the backend models
 */

export interface Chat {
  id: string
  name: string
  session_id: string
  user_id: string
  channel: string
  created_at: string
  updated_at: string
}

export interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: string
  userQuery?: string  // 用户输入的查询摘要
  thinking?: {
    isThinking: boolean
    steps: ThinkingStep[]
  }
}

export interface ChatHistory {
  chat_id: string
  total: number
  messages: Message[]
}

export interface AgentEvent {
  event: string
  session_id?: string
  status?: string
  content?: string
  step?: number
  max_steps?: number
  tool_name?: string
  arguments?: Record<string, any>
  result?: any
  success?: boolean
  error?: string
  message?: string
  elapsed?: number  // 步骤耗时（秒）
  total_elapsed?: number  // 总耗时（秒）
}

export interface RunRequest {
  session_id: string
  user_id?: string
  messages: Message[]
  stream?: boolean
}

// 大模型提供商
export interface ModelProvider {
  id: string
  name: string
  models: Model[]
}

export interface Model {
  id: string
  name: string
  description?: string
}

// 大模型配置
export interface ModelConfig {
  id: string
  name: string
  display_name: string
  provider: string
  provider_display_name?: string  // 提供商友好名称
  api_key?: string
  api_key_length?: number  // API Key 长度（用于前端显示掩码）
  has_api_key?: boolean  // API Key 配置状态
  base_url?: string
  provider_type: string
  is_default?: boolean
  available_models?: string[]  // 可用模型列表
}

// 提供商信息
export interface ProviderInfo {
  id: string
  name: string
  display_name: string
  default_base_url: string
  default_models: string[]
}

// 提供商模型响应
export interface ProviderModelsResponse {
  models: string[]
  provider: string
  display_name: string
  error?: string
}

// 智能体配置
export interface AgentConfig {
  id: string
  name: string
  model_id: string
  description?: string
  avatar?: string
  system_prompt?: string
  temperature: number
  max_tokens: number
  max_steps: number
  tools: string[]
  mcp_servers: string[]
  created_at: string
  updated_at: string
}

// Agent 类型别名，用于视图组件
export interface Agent {
  id: string
  name: string
  description?: string
  model: string
  systemPrompt?: string
  temperature?: number
  maxTokens?: number
  avatar?: string
  createdAt: string
  updatedAt: string
}

// 会话历史
export interface SessionHistory {
  session_id: string
  agent_id: string
  agent_name: string
  created_at: string
  updated_at: string
  message_count: number
  preview?: string
}

// 指令定义
export interface Command {
  name: string
  description: string
  usage: string
  args?: CommandArg[]
  examples?: string[]
}

export interface CommandArg {
  name: string
  type: string
  required: boolean
  description: string
  default?: string
}

// 系统设置
export interface SystemSettings {
  language: 'zh-CN' | 'en-US'
  theme: 'light' | 'dark' | 'system'
  fontSize: 'small' | 'medium' | 'large'
  workspace: string
  autoSave: boolean
  streamResponse: boolean
  useCoT: boolean  // 思考模式 (Chain of Thought)
}

// 统计数据
export interface DashboardStats {
  totalAgents: number
  totalSessions: number
  totalMessages: number
  activeModels: number
  recentSessions: SessionHistory[]
}

// 菜单项定义
export interface MenuItem {
  id: string
  label: string
  labelEn: string
  icon: string
  children?: MenuItem[]
}

// 会话信息 (用于历史会话列表)
export interface SessionInfo {
  id: string
  agent_id: string
  agent_name: string
  created_at: string
  updated_at: string
  message_count: number
  preview?: string
}

// ChatSession 类型别名，用于历史会话视图
export type ChatSession = SessionInfo

// 指令信息 (用于指令展示)
export interface CommandInfo {
  agent_id: string
  agent_name: string
  commands: Command[]
}

// 应用设置
export interface AppSettings {
  language: 'zh-CN' | 'en-US'
  theme: 'light' | 'dark' | 'system'
  fontSize: 'small' | 'medium' | 'large'
  workspace: string
  autoSave: boolean
  streamResponse: boolean
}

// 思考步骤
export interface ThinkingStep {
  id: string
  type: 'thinking' | 'tool_call' | 'tool_result' | 'observation'
  content: string
  toolName?: string
  toolOutput?: string
  timestamp: string
}

// 思考状态
export interface ThinkingState {
  isThinking: boolean
  steps: ThinkingStep[]
}

// API响应类型
export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  message?: string
}

// ==================== File Upload Types ====================

// 文件上传相关类型
export interface UploadedFile {
  file_id: string
  file_name: string
  file_path: string
  file_type: string
  file_size: number
}
