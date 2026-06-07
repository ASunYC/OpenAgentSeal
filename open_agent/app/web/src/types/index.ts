/**
 * TypeScript types matching the backend models
 */

export interface Chat {
  id: string
  name: string
  session_id: string
  user_id: string
  channel: string
  meta?: Record<string, any>
  created_at: string
  updated_at: string
}

export interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
  attachments?: ChatAttachment[]
  timestamp?: string
  userQuery?: string  // 用户输入的查询摘要
  isLoading?: boolean
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

export interface ContextCompactionStatus {
  session_id: string
  enabled: boolean
  used_tokens: number
  token_limit: number
  context_window: number
  context_window_source: string
  model_id?: string | null
  model_name?: string
  usage_percent: number
  compacted: boolean
  compaction_count: number
  updated_at?: string | null
}

export interface ChatAttachment {
  id: string
  name: string
  mime_type: string
  data: string
  size?: number
}

export interface WorkspaceSourceNode {
  id?: string
  name: string
  path: string
  type: 'file' | 'directory' | 'web'
  mime_type?: string | null
  size?: number | null
  modified_at?: number
  relative_path?: string
  children?: WorkspaceSourceNode[]
  children_count?: number
}

export interface WorkspaceSource {
  id: string
  name: string
  path: string
  type: 'file' | 'directory' | 'web'
  mime_type?: string | null
  size?: number | null
  modified_at?: number
  children?: WorkspaceSourceNode[]
  children_count?: number
}

export interface WorkspaceSourceState {
  sources: WorkspaceSource[]
  selected_paths: string[]
  expanded_paths: string[]
}

export interface ForkChatResponse {
  chat: Chat
  source_session_id: string
  copied_message_count: number
}

export interface AgentEvent {
  event: string
  session_id?: string
  thread_id?: string
  turn_id?: string
  seq?: number
  created_at?: string
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
  workspace_sources?: WorkspaceSource[]
  selected_workspace_paths?: string[]
  tool_access_mode?: 'default' | 'full'
}

export interface RuntimeThread {
  thread_id: string
  session_id: string
  user_id: string
  title: string
  status: string
  latest_event_seq: number
  created_at: string
  updated_at: string
  metadata?: Record<string, any>
}

export interface RuntimeTurn {
  turn_id: string
  thread_id: string
  session_id: string
  user_input: string
  status: string
  started_at: string
  completed_at?: string
  result?: any
  error?: string
  metadata?: Record<string, any>
}

export interface RuntimeEvent {
  event_id: string
  thread_id: string
  turn_id?: string
  session_id: string
  seq: number
  event_type: string
  payload: AgentEvent | Record<string, any>
  created_at: string
  metadata?: Record<string, any>
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
  context_window?: number
  context_window_source?: string
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
  permission_mode?: 'default' | 'full' | string
  allow_delegation?: boolean
  enabled?: boolean
  created_at: string
  updated_at: string
}

// Agent 类型别名，用于视图组件
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
  settingsVersion?: number
  fontSize: 'small' | 'medium' | 'large'
  workspace: string
  enable_skills?: boolean
  autoSave: boolean
  streamResponse: boolean
  useCoT: boolean  // 思考模式 (Chain of Thought)
  autoContextCompaction: boolean
  contextCompactionTokenLimit: number
}

// 统计数据
export interface DashboardStats {
  totalAgents: number
  totalChats: number
  totalMessages: number
  activeModels: number
  recentChats: Chat[]
}

// 菜单项定义
export interface MenuItem {
  id: string
  label: string
  labelEn: string
  icon: string
  children?: MenuItem[]
}

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
  settingsVersion?: number
  fontSize: 'small' | 'medium' | 'large'
  workspace: string
  autoSave: boolean
  streamResponse: boolean
  enable_skills?: boolean
  useCoT: boolean
  autoContextCompaction: boolean
  contextCompactionTokenLimit: number
}

export interface SmartRoutingConfig {
  enabled: boolean
  text_model_id: string
  vision_model_id: string
  audio_model_id: string
  fallback_model_id: string
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
