<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('模型设置', 'Model Settings') }}</h3>
      <p>{{ t('配置大模型API', 'Configure LLM APIs') }}</p>
    </div>
    
    <div class="models-grid">
      <div 
        class="model-card" 
        v-for="config in modelConfigs" 
        :key="config.id"
        :class="{ 'new-card': config.isNew }"
      >
        <div class="card-header">
          <div class="provider-info">
            <div class="provider-icon" :style="{ background: getProviderColor(config.provider) }">
              {{ getProviderIcon(config.provider) }}
            </div>
            <div class="provider-name">
              <!-- 新卡片显示提供商选择下拉框 -->
              <template v-if="config.isNew">
                <select 
                  class="provider-select"
                  :value="config.provider"
                  @change="onProviderChange(config, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="" disabled>{{ t('选择提供商', 'Select Provider') }}</option>
                  <option 
                    v-for="p in availableProviders" 
                    :key="p.value" 
                    :value="p.value"
                    :disabled="isProviderExists(p.value)"
                  >
                    {{ p.label }}
                  </option>
                </select>
              </template>
              <template v-else>
                <h4>{{ config.provider_display_name || config.provider }}</h4>
                <span class="model-count">{{ config.models.length }} {{ t('个模型', 'models') }}</span>
              </template>
            </div>
          </div>
          <div class="header-actions">
            <!-- 新卡片标识 -->
            <span
              v-if="config.isNew"
              class="status-badge new-badge"
            >
              {{ t('新建', 'New') }}
            </span>
            <!-- API Key 状态指示器 -->
            <span
              v-else-if="config.has_api_key"
              class="status-badge configured"
              :title="t('API Key 已配置', 'API Key configured')"
            >
              {{ t('已配置', 'Configured') }}
            </span>
            <span
              v-else
              class="status-badge not-configured"
              :title="t('API Key 未配置', 'API Key not configured')"
            >
              {{ t('未配置', 'Not Configured') }}
            </span>
            <!-- 编辑按钮（所有卡片都显示） -->
            <button
              v-if="!config.isNew"
              class="btn-edit"
              @click="editConfig(config)"
              :title="config.editing ? t('取消编辑', 'Cancel Edit') : t('编辑', 'Edit')"
            >
              <svg v-if="config.editing" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 6L6 18M6 6l12 12"/>
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
            </button>
            <!-- 删除按钮（所有卡片都显示） -->
            <button
              class="btn-edit btn-delete"
              @click="config.isNew ? removeConfig(config) : deleteConfig(config)"
              :title="t('删除', 'Delete')"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                <line x1="10" y1="11" x2="10" y2="17"/>
                <line x1="14" y1="11" x2="14" y2="17"/>
              </svg>
            </button>
          </div>
        </div>
        
        <div class="card-body">
          <div class="form-group">
            <label>{{ t('API Key', 'API Key') }}</label>
            <div class="input-with-toggle">
              <input
                :type="config.showKey ? 'text' : 'password'"
                :value="config.apiKey"
                @input="updateApiKey(config, ($event.target as HTMLInputElement).value)"
                :placeholder="config.has_api_key ? t('已配置（输入可更新）', 'Configured (enter to update)') : t('输入API密钥', 'Enter API key')"
              />
              <button class="btn-toggle" @click="config.showKey = !config.showKey">
                <svg v-if="config.showKey" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                  <line x1="1" y1="1" x2="23" y2="23"/>
                </svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                  <circle cx="12" cy="12" r="3"/>
                </svg>
              </button>
            </div>
          </div>
          
          <!-- 新卡片显示 Base URL 输入框 -->
          <div class="form-group" v-if="config.isNew || config.editing">
            <label>{{ t('Base URL', 'Base URL') }}</label>
            <input 
              type="text"
              :value="config.base_url || ''"
              @input="updateBaseUrl(config, ($event.target as HTMLInputElement).value)"
              :placeholder="t('可选，自定义API地址', 'Optional, custom API endpoint')"
              class="model-name-input"
            />
          </div>
          
          <div class="form-group">
            <label>{{ t('模型名称', 'Model Name') }}</label>
            <!-- 可编辑的模型名称输入框 -->
            <input 
              type="text"
              v-model="config.selectedModel"
              @input="clearDiagnostic(config)"
              @change="resolveContextWindow(config)"
              :placeholder="t('输入或选择模型', 'Enter or select model')"
              class="model-name-input"
            />
          </div>

          <div class="form-group context-window-group">
            <div class="field-label-row">
              <label>{{ t('上下文大小（Token）', 'Context Window (Tokens)') }}</label>
              <span class="context-source" :class="`source-${config.contextWindowSource}`">
                {{ contextSourceLabel(config.contextWindowSource) }}
              </span>
            </div>
            <input
              type="number"
              v-model.number="config.contextWindow"
              min="8000"
              step="1000"
              class="model-name-input"
              @change="markContextWindowManual(config)"
            />
            <span class="field-hint">
              {{ t(
                `自动压缩约在 ${formatContextSize(Math.floor(config.contextWindow * 0.9))} Token 时触发`,
                `Auto compaction starts at about ${formatContextSize(Math.floor(config.contextWindow * 0.9))} tokens`
              ) }}
            </span>
          </div>
          
          <div class="form-group">
            <label>{{ t('可用模型', 'Available Models') }}</label>
            <div class="model-tags">
              <span 
                class="model-tag" 
                v-for="model in config.models" 
                :key="model"
                :class="{ active: model === config.selectedModel }"
                @click="selectModel(config, model)"
              >
                {{ model }}
              </span>
              <!-- 刷新模型列表按钮 -->
              <button 
                class="model-tag refresh-btn" 
                @click="refreshModels(config)"
                :disabled="config.loadingModels || !config.provider"
                :title="t('从厂商获取模型列表', 'Fetch models from provider')"
              >
                <svg v-if="config.loadingModels" class="spinning" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/>
                </svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M23 4v6h-6M1 20v-6h6"/>
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                </svg>
              </button>
            </div>
          </div>
          
          <div class="form-group" v-if="config.editing || config.isNew">
            <label>{{ t('添加自定义模型', 'Add Custom Model') }}</label>
            <div class="input-with-btn">
              <input 
                v-model="config.newModel" 
                :placeholder="t('输入模型名称', 'Enter model name')"
                @keyup.enter="addCustomModel(config)"
              />
              <button class="btn-add" @click="addCustomModel(config)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="12" y1="5" x2="12" y2="19"/>
                  <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
        
        <div
          v-if="config.diagnostic || config.diagnosticError"
          class="diagnostic-panel"
          :class="config.diagnostic ? `diagnostic-${config.diagnostic.status}` : 'diagnostic-error'"
        >
          <div class="diagnostic-header">
            <span>{{ t('诊断结果', 'Diagnostics') }}</span>
            <strong>{{ diagnosticStatusLabel(config) }}</strong>
          </div>
          <p v-if="config.diagnosticError" class="diagnostic-message">{{ config.diagnosticError }}</p>
          <template v-else-if="config.diagnostic">
            <p class="diagnostic-message">
              {{ config.diagnostic.route.provider }} / {{ config.diagnostic.route.api_protocol }}
              <span v-if="config.diagnostic.route.api_base"> · {{ config.diagnostic.route.api_base }}</span>
            </p>
            <ul class="diagnostic-checks">
              <li
                v-for="(check, key) in config.diagnostic.checks"
                :key="key"
                :class="`check-${check.status}`"
              >
                <span class="check-name">{{ diagnosticCheckLabel(String(key)) }}</span>
                <span>{{ check.message }}</span>
              </li>
            </ul>
          </template>
        </div>

        <div
          v-if="config.liveTest || config.liveTestError"
          class="diagnostic-panel"
          :class="config.liveTest ? `diagnostic-${config.liveTest.status}` : 'diagnostic-error'"
        >
          <div class="diagnostic-header">
            <span>{{ t('真实测试', 'Live test') }}</span>
            <strong>{{ liveTestStatusLabel(config) }}</strong>
          </div>
          <p v-if="config.liveTestError" class="diagnostic-message">{{ config.liveTestError }}</p>
          <template v-else-if="config.liveTest">
            <p class="diagnostic-message">
              {{ config.liveTest.route.provider }} / {{ config.liveTest.route.model }}
              <span v-if="config.liveTest.latency_ms"> · {{ config.liveTest.latency_ms }}ms</span>
            </p>
            <p v-if="config.liveTest.response_preview" class="diagnostic-message">
              {{ t('响应预览：', 'Response: ') }}{{ config.liveTest.response_preview }}
            </p>
            <ul class="diagnostic-checks">
              <li
                v-for="(check, key) in config.liveTest.checks"
                :key="key"
                :class="`check-${check.status}`"
              >
                <span class="check-name">{{ diagnosticCheckLabel(String(key)) }}</span>
                <span>{{ check.message }}</span>
              </li>
            </ul>
          </template>
        </div>

        <div class="card-footer">
          <button
            class="btn-diagnose"
            @click="diagnoseConfig(config)"
            :disabled="config.diagnosing || !config.provider"
          >
            {{ config.diagnosing ? t('诊断中...', 'Checking...') : t('诊断', 'Diagnose') }}
          </button>
          <button
            class="btn-diagnose"
            @click="liveTestConfig(config)"
            :disabled="config.testingLive || !config.provider"
          >
            {{ config.testingLive ? t('测试中...', 'Testing...') : t('真实测试', 'Live test') }}
          </button>
          <button class="btn-save" @click="saveConfig(config)" :disabled="config.saving || (config.isNew && !config.provider)">
            {{ config.saving ? t('保存中...', 'Saving...') : t('保存', 'Save') }}
          </button>
        </div>
      </div>
      
      <div class="model-card add-card" @click="createNewModel">
        <div class="add-content">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          <span>{{ t('新建模型', 'New Model') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAgentStore } from '@/stores/agent'
import { api } from '@/api'
import type { ModelConfig, ProviderDiagnostic, ProviderInfo, ProviderLiveTest } from '@/types'

const settingsStore = useSettingsStore()
const agentStore = useAgentStore()

interface LocalModelConfig {
  id: string
  provider: string
  provider_display_name: string
  apiKey: string
  apiKeyLength: number  // 后端返回的 API Key 长度
  has_api_key: boolean
  isUserInput: boolean  // 是否为用户输入的新 API Key（非后端返回的掩码）
  isNew: boolean  // 是否为新建的配置卡片
  models: string[]
  selectedModel: string
  contextWindow: number
  contextWindowSource: string
  display_name: string
  base_url?: string
  provider_type?: string
  is_default?: boolean
  showKey: boolean
  saving: boolean
  editing: boolean
  loadingModels: boolean
  diagnosing: boolean
  diagnostic?: ProviderDiagnostic
  diagnosticError?: string
  testingLive: boolean
  liveTest?: ProviderLiveTest
  liveTestError?: string
  newModel: string
}

interface ProviderOption {
  value: string
  label: string
  defaultBaseUrl: string
  defaultModels: string[]
  apiProtocol: string
}

const modelConfigs = reactive<LocalModelConfig[]>([])
const DEFAULT_CONTEXT_WINDOW = 1_000_000

const fallbackProviders: ProviderOption[] = [
  { value: 'openai', label: 'OpenAI (GPT)', defaultBaseUrl: 'https://api.openai.com/v1', defaultModels: ['gpt-4o', 'gpt-4o-mini'], apiProtocol: 'openai' },
  { value: 'anthropic', label: 'Anthropic (Claude)', defaultBaseUrl: 'https://api.anthropic.com', defaultModels: ['claude-3-5-sonnet-20241022'], apiProtocol: 'anthropic' },
  { value: 'volcano', label: 'Volcano', defaultBaseUrl: 'https://ark.cn-beijing.volces.com/api/coding/v3', defaultModels: ['glm-5-2-260617'], apiProtocol: 'openai' },
  { value: 'custom', label: 'Custom', defaultBaseUrl: '', defaultModels: [], apiProtocol: 'openai' },
]
const availableProviders = reactive<ProviderOption[]>([])

function providerOptionFromApi(provider: ProviderInfo): ProviderOption {
  return {
    value: provider.id,
    label: provider.display_name || provider.name || provider.id,
    defaultBaseUrl: provider.default_base_url || '',
    defaultModels: provider.default_models || [],
    apiProtocol: provider.api_protocol || provider.provider_type || 'openai',
  }
}

async function loadProviderProfiles() {
  try {
    const providers = await api.getProviders()
    const options = providers.map(providerOptionFromApi)
    availableProviders.splice(
      0,
      availableProviders.length,
      ...(options.length > 0 ? options : fallbackProviders),
    )
  } catch (error) {
    console.error('Failed to load providers:', error)
    if (availableProviders.length === 0) {
      availableProviders.splice(0, availableProviders.length, ...fallbackProviders)
    }
  }
}

// 检查提供商是否已存在
function isProviderExists(provider: string): boolean {
  return modelConfigs.some(c => c.provider.toLowerCase() === provider.toLowerCase() && !c.isNew)
}

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function getProviderColor(provider: string): string {
  const colors: Record<string, string> = {
    openai: '#10a37f',
    anthropic: '#d97706',
    deepseek: '#3b82f6',
    zhipu: '#8b5cf6',
    qwen: '#f59e0b',
    moonshot: '#ec4899',
    minimax: '#06b6d4',
    volcano: '#ef4444',
    siliconflow: '#6366f1',
    baichuan: '#84cc16',
    ollama: '#6b7280',
    custom: '#6b7280'
  }
  return colors[provider.toLowerCase()] || '#6b7280'
}

function getProviderIcon(provider: string): string {
  // 返回提供商首字母或图标
  const icons: Record<string, string> = {
    openai: 'O',
    anthropic: 'A',
    deepseek: 'D',
    zhipu: '智',
    qwen: '通',
    moonshot: '月',
    minimax: 'M',
    volcano: '火',
    siliconflow: '硅',
    baichuan: '百',
    ollama: 'O',
    custom: 'C'
  }
  return icons[provider.toLowerCase()] || provider.charAt(0).toUpperCase()
}

// 创建新的模型配置卡片
function createNewModel() {
  const newId = `new_${Date.now()}`
  modelConfigs.push({
    id: newId,
    provider: '',
    provider_display_name: '',
    apiKey: '',
    apiKeyLength: 0,
    has_api_key: false,
    isUserInput: false,
    isNew: true,
    models: [],
    selectedModel: '',
    contextWindow: DEFAULT_CONTEXT_WINDOW,
    contextWindowSource: 'fallback',
    display_name: '',
    base_url: '',
    provider_type: 'openai',
    showKey: false,
    saving: false,
    editing: true,
    loadingModels: false,
    diagnosing: false,
    testingLive: false,
    newModel: ''
  })
}

// 移除配置卡片（仅用于新建的卡片）
function removeConfig(config: LocalModelConfig) {
  const index = modelConfigs.findIndex(c => c.id === config.id)
  if (index !== -1 && config.isNew) {
    modelConfigs.splice(index, 1)
  }
}

// 删除已保存的配置（带确认提示）
async function deleteConfig(config: LocalModelConfig) {
  // 确认删除
  const confirmed = confirm(t(
    `确定要删除 "${config.provider_display_name || config.provider}" 配置吗？`,
    `Are you sure you want to delete "${config.provider_display_name || config.provider}" configuration?`
  ))
  if (!confirmed) return
  
  try {
    const result = await api.deleteModelConfig(config.id)
    if (result.success) {
      // 从本地列表中移除
      const index = modelConfigs.findIndex(c => c.id === config.id)
      if (index !== -1) {
        modelConfigs.splice(index, 1)
      }
      // 刷新 store 中的配置
      await agentStore.loadModelConfigs()
      alert(t('配置已删除', 'Configuration deleted'))
    } else {
      alert(result.error || t('删除失败', 'Delete failed'))
    }
  } catch (error) {
    console.error('Failed to delete config:', error)
    alert(t('删除失败', 'Delete failed'))
  }
}

// 提供商变更时更新相关信息
async function onProviderChange(config: LocalModelConfig, provider: string) {
  const providerInfo = availableProviders.find(p => p.value === provider)
  if (providerInfo) {
    config.provider = provider
    config.provider_display_name = providerInfo.label
    config.provider_type = providerInfo.apiProtocol || (provider === 'anthropic' ? 'anthropic' : 'openai')
    clearDiagnostic(config)

    config.base_url = providerInfo.defaultBaseUrl
    config.models = [...providerInfo.defaultModels]
    if (config.models.length > 0) {
      config.selectedModel = config.models[0]
    }
    
    // 尝试从后端获取模型列表
    config.loadingModels = true
    try {
      const result = await api.getProviderModels(provider)
      if (result.models && result.models.length > 0) {
        config.models = result.models
        if (config.models.length > 0) {
          config.selectedModel = config.models[0]
        }
      }
    } catch (error) {
      console.error('Failed to fetch models for provider:', provider, error)
    } finally {
      config.loadingModels = false
    }
    await resolveContextWindow(config)
  }
}

async function selectModel(config: LocalModelConfig, model: string) {
  config.selectedModel = model
  clearDiagnostic(config)
  await resolveContextWindow(config)
}

async function resolveContextWindow(config: LocalModelConfig) {
  const modelName = config.selectedModel.trim()
  if (!modelName) return
  try {
    const result = await api.resolveModelContextWindow(modelName, config.provider)
    config.contextWindow = result.context_window
    config.contextWindowSource = result.source
  } catch (error) {
    console.error('Failed to resolve model context window:', error)
    config.contextWindow = config.contextWindow || DEFAULT_CONTEXT_WINDOW
    config.contextWindowSource = 'fallback'
  }
}

function markContextWindowManual(config: LocalModelConfig) {
  config.contextWindow = Math.max(8000, Number(config.contextWindow) || DEFAULT_CONTEXT_WINDOW)
  config.contextWindowSource = 'manual'
}

function contextSourceLabel(source: string): string {
  const labels: Record<string, [string, string]> = {
    manual: ['手动设置', 'Manual'],
    provider: ['供应商返回', 'Provider'],
    catalog: ['自动识别', 'Detected'],
    fallback: ['默认值', 'Default'],
  }
  const label = labels[source] || labels.fallback
  return t(label[0], label[1])
}

function formatContextSize(value: number): string {
  if (value >= 1_000_000) {
    return `${Number((value / 1_000_000).toFixed(1))}M`
  }
  if (value >= 1_000) {
    return `${Number((value / 1_000).toFixed(1))}K`
  }
  return String(value)
}

function editConfig(config: LocalModelConfig) {
  config.editing = !config.editing
}

function updateApiKey(config: LocalModelConfig, key: string) {
  config.apiKey = key
  // 标记为用户输入的新 API Key（非后端返回的掩码）
  config.isUserInput = true
  clearDiagnostic(config)
}

function updateBaseUrl(config: LocalModelConfig, url: string) {
  config.base_url = url
  clearDiagnostic(config)
}

async function refreshModels(config: LocalModelConfig) {
  if (!config.provider) return
  config.loadingModels = true
  try {
    const result = await api.getProviderModels(config.provider)
    if (result.models && result.models.length > 0) {
      // 合并新模型到现有列表，避免重复
      const newModels = result.models.filter(m => !config.models.includes(m))
      config.models = [...config.models, ...newModels]
    }
  } catch (error) {
    console.error('Failed to refresh models:', error)
  } finally {
    config.loadingModels = false
  }
}

function addCustomModel(config: LocalModelConfig) {
  if (config.newModel && config.newModel.trim()) {
    const model = config.newModel.trim()
    if (!config.models.includes(model)) {
      config.models.push(model)
    }
    // 自动选中新添加的模型
    config.selectedModel = model
    config.newModel = ''
    clearDiagnostic(config)
  }
}

function clearDiagnostic(config: LocalModelConfig) {
  config.diagnostic = undefined
  config.diagnosticError = ''
  config.liveTest = undefined
  config.liveTestError = ''
}

function diagnosticApiKey(config: LocalModelConfig): string {
  if (config.apiKey && (config.isNew || config.isUserInput)) {
    return config.apiKey
  }
  return config.has_api_key ? '__configured__' : ''
}

async function diagnoseConfig(config: LocalModelConfig) {
  if (!config.provider) return
  config.diagnosing = true
  config.diagnosticError = ''
  try {
    const result = config.isNew || config.editing
      ? await api.diagnoseProvider(config.provider, {
          name: config.selectedModel,
          api_key: diagnosticApiKey(config),
          base_url: config.base_url,
          provider_type: config.provider_type || 'openai',
        })
      : await api.diagnoseModelConfig(config.id)

    if (result.success && result.diagnostic) {
      config.diagnostic = result.diagnostic
    } else {
      config.diagnostic = undefined
      config.diagnosticError = result.error || t('诊断失败', 'Diagnostics failed')
    }
  } catch (error) {
    config.diagnostic = undefined
    config.diagnosticError = error instanceof Error ? error.message : t('诊断失败', 'Diagnostics failed')
  } finally {
    config.diagnosing = false
  }
}

async function liveTestConfig(config: LocalModelConfig) {
  if (!config.provider) return
  config.testingLive = true
  config.liveTestError = ''
  try {
    const result = config.isNew || config.editing
      ? await api.liveTestProvider(config.provider, {
          name: config.selectedModel,
          api_key: diagnosticApiKey(config),
          base_url: config.base_url,
          provider_type: config.provider_type || 'openai',
        })
      : await api.liveTestModelConfig(config.id)

    if (result.success && result.live_test) {
      config.liveTest = result.live_test
      config.diagnostic = {
        status: result.live_test.diagnostic_status,
        id: result.live_test.id,
        display_name: result.live_test.display_name,
        route: result.live_test.route,
        checks: Object.fromEntries(
          Object.entries(result.live_test.checks).filter(([key]) => key !== 'live_request'),
        ),
      }
    } else {
      config.liveTest = undefined
      config.liveTestError = result.error || t('真实测试失败', 'Live test failed')
    }
  } catch (error) {
    config.liveTest = undefined
    config.liveTestError = error instanceof Error ? error.message : t('真实测试失败', 'Live test failed')
  } finally {
    config.testingLive = false
  }
}

function diagnosticStatusLabel(config: LocalModelConfig): string {
  if (config.diagnosticError) return t('失败', 'Failed')
  const status = config.diagnostic?.status
  if (status === 'ok') return t('正常', 'OK')
  if (status === 'warning') return t('需确认', 'Warning')
  if (status === 'error') return t('有问题', 'Error')
  return status || ''
}

function liveTestStatusLabel(config: LocalModelConfig): string {
  if (config.liveTestError) return t('失败', 'Failed')
  const status = config.liveTest?.status
  if (status === 'ok') return t('已通过', 'Passed')
  if (status === 'warning') return t('需确认', 'Warning')
  if (status === 'error') return t('失败', 'Failed')
  return status || ''
}

function diagnosticCheckLabel(key: string): string {
  const labels: Record<string, [string, string]> = {
    provider: ['提供商', 'Provider'],
    protocol: ['协议', 'Protocol'],
    api_base: ['API 地址', 'API Base'],
    api_key: ['API Key', 'API Key'],
    model: ['模型', 'Model'],
    live_request: ['真实请求', 'Live request'],
  }
  const label = labels[key]
  return label ? t(label[0], label[1]) : key
}

function defaultProviderOptions(): ProviderOption[] {
  const byId = new Map(availableProviders.map(provider => [provider.value, provider]))
  const preferred = ['openai', 'anthropic']
    .map(provider => byId.get(provider))
    .filter((provider): provider is ProviderOption => Boolean(provider))

  if (preferred.length > 0) return preferred
  return availableProviders.length > 0 ? availableProviders.slice(0, 2) : fallbackProviders.slice(0, 2)
}

function createDefaultLocalConfig(provider: ProviderOption, index: number): LocalModelConfig {
  const selectedModel = provider.defaultModels[0] || ''
  return {
    id: `default_${provider.value}`,
    provider: provider.value,
    provider_display_name: provider.label,
    apiKey: '',
    apiKeyLength: 0,
    has_api_key: false,
    isUserInput: false,
    isNew: false,
    models: [...provider.defaultModels],
    selectedModel,
    contextWindow: DEFAULT_CONTEXT_WINDOW,
    contextWindowSource: 'fallback',
    display_name: selectedModel ? `${provider.label} (${selectedModel})` : provider.label,
    base_url: provider.defaultBaseUrl,
    provider_type: provider.apiProtocol || 'openai',
    is_default: index === 0,
    showKey: false,
    saving: false,
    editing: false,
    loadingModels: false,
    diagnosing: false,
    testingLive: false,
    newModel: ''
  }
}

async function saveConfig(config: LocalModelConfig) {
  // 验证必填字段
  if (!config.provider) {
    alert(t('请选择提供商', 'Please select a provider'))
    return
  }
  
  config.saving = true
  try {
    // 构造符合 ModelConfig 类型的对象
    const modelConfig: ModelConfig = {
      id: config.isNew ? '' : config.id,  // 新建配置传空ID，后端会生成新ID
      name: config.selectedModel,
      display_name: config.display_name || `${config.provider_display_name} (${config.selectedModel})`,
      provider: config.provider,
      api_key: config.apiKey,
      base_url: config.base_url,
      provider_type: config.provider_type || 'openai',
      is_default: config.is_default,
      context_window: Math.max(8000, Number(config.contextWindow) || DEFAULT_CONTEXT_WINDOW),
      context_window_source: config.contextWindowSource || 'manual'
    }
    
    const result = await api.saveModelConfig(modelConfig)
    if (result.success) {
      // 如果是新建配置，更新ID
      if (config.isNew && result.data?.id) {
        config.id = result.data.id
      }
      // 更新状态
      config.has_api_key = !!config.apiKey
      config.isNew = false
      config.editing = false
      await agentStore.loadModelConfigs()
      alert(t('保存成功', 'Saved successfully'))
    } else {
      alert(result.error || t('保存失败', 'Save failed'))
    }
  } catch (error) {
    console.error('Failed to save config:', error)
    alert(t('保存失败', 'Save failed'))
  } finally {
    config.saving = false
  }
}

onMounted(async () => {
  await loadProviderProfiles()
  await agentStore.loadModelConfigs()
  
  // 转换store中的配置到本地响应式对象
  agentStore.modelConfigs.forEach((config: any) => {
    // 后端返回的数据格式：{ id, name, display_name, provider, provider_display_name, base_url, provider_type, is_default, available_models, has_api_key }
    const availableModels = config.available_models || []
    const models = availableModels.length > 0 ? availableModels : (config.name ? [config.name] : [])
    
    modelConfigs.push({
      id: config.id,
      provider: config.provider,
      provider_display_name: config.provider_display_name || config.provider,
      apiKey: config.api_key || '',  // 显示后端返回的掩码值（如 "********************************"）
      apiKeyLength: config.api_key_length || 0,  // 后端返回的 API Key 长度
      has_api_key: config.has_api_key || false,
      isUserInput: false,  // 初始为后端返回的掩码，非用户输入
      isNew: false,  // 从后端加载的配置不是新建的
      models: models,
      selectedModel: config.name || '',
      contextWindow: config.context_window || DEFAULT_CONTEXT_WINDOW,
      contextWindowSource: config.context_window_source || 'fallback',
      display_name: config.display_name || '',
      base_url: config.base_url,
      provider_type: config.provider_type || 'openai',
      is_default: config.is_default,
      showKey: false,
      saving: false,
      editing: false,
      loadingModels: false,
      diagnosing: false,
      testingLive: false,
      newModel: ''
    })
  })
  
  // 如果没有配置，添加默认提供商
  if (modelConfigs.length === 0) {
    modelConfigs.push(...defaultProviderOptions().map(createDefaultLocalConfig))
  }
})
</script>

<style scoped>
.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.content-header {
  margin-bottom: 8px;
}

.content-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.content-header p {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.model-card {
  background: var(--main-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border-color);
}

.provider-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.provider-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 16px;
}

.provider-name h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.model-count {
  font-size: 12px;
  color: var(--text-muted);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-badge {
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.status-badge.configured {
  background: rgba(16, 163, 127, 0.2);
  color: #10a37f;
}

.status-badge.not-configured {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

.btn-edit {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.btn-edit:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.btn-edit svg {
  width: 16px;
  height: 16px;
}

.card-body {
  padding: 16px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group:last-child {
  margin-bottom: 0;
}

.form-group label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.field-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.field-label-row label {
  margin-bottom: 0;
}

.context-source {
  flex: none;
  padding: 2px 6px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-muted);
  background: var(--hover-bg);
  font-size: 10px;
  line-height: 1.4;
}

.context-source.source-manual {
  color: var(--primary-color);
  border-color: color-mix(in srgb, var(--primary-color) 45%, var(--border-color));
  background: color-mix(in srgb, var(--primary-color) 8%, transparent);
}

.context-source.source-catalog,
.context-source.source-provider {
  color: #059669;
  border-color: rgba(5, 150, 105, 0.35);
  background: rgba(5, 150, 105, 0.08);
}

.field-hint {
  display: block;
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.45;
}

.input-with-toggle {
  display: flex;
  gap: 8px;
}

.input-with-toggle input,
.model-name-input,
.input-with-btn input {
  flex: 1;
  padding: 8px 12px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
}

.input-with-toggle input:focus,
.model-name-input:focus,
.input-with-btn input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.btn-toggle,
.btn-add {
  width: 36px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--hover-bg);
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-toggle svg,
.btn-add svg {
  width: 16px;
  height: 16px;
}

.input-with-btn {
  display: flex;
  gap: 8px;
}

.model-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.model-tag {
  padding: 4px 10px;
  background: var(--hover-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.model-tag:hover {
  border-color: var(--primary-color);
}

.model-tag.active {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: white;
}

.model-tag.refresh-btn {
  background: transparent;
  border-style: dashed;
  padding: 4px 8px;
}

.model-tag.refresh-btn:hover:not(:disabled) {
  background: var(--hover-bg);
  border-color: var(--primary-color);
}

.model-tag.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.model-tag.refresh-btn svg {
  width: 14px;
  height: 14px;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.card-footer {
  display: grid;
  grid-template-columns: minmax(76px, 0.32fr) minmax(88px, 0.34fr) minmax(96px, 0.34fr);
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}

.btn-diagnose,
.btn-save {
  width: 100%;
  padding: 8px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-diagnose {
  background: var(--hover-bg);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
}

.btn-save {
  background: var(--primary-color);
  border: none;
  color: white;
}

.btn-diagnose:hover:not(:disabled),
.btn-save:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-diagnose:disabled,
.btn-save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.diagnostic-panel {
  margin: 0 16px 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--hover-bg);
}

.diagnostic-ok {
  border-color: rgba(5, 150, 105, 0.35);
  background: rgba(5, 150, 105, 0.06);
}

.diagnostic-warning {
  border-color: rgba(217, 119, 6, 0.35);
  background: rgba(217, 119, 6, 0.06);
}

.diagnostic-error {
  border-color: rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.06);
}

.diagnostic-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}

.diagnostic-header strong {
  flex: none;
  color: var(--text-secondary);
  font-size: 11px;
}

.diagnostic-message {
  margin: 6px 0 0;
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.diagnostic-checks {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.diagnostic-checks li {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.4;
}

.check-name {
  color: var(--text-muted);
}

.check-ok {
  color: #059669;
}

.check-warning {
  color: #d97706;
}

.check-error {
  color: #dc2626;
}

.add-card {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 180px;
  border-style: dashed;
  cursor: pointer;
  transition: all 0.2s;
}

.add-card:hover {
  border-color: var(--primary-color);
  background: var(--hover-bg);
}

.add-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
}

.add-content svg {
  width: 24px;
  height: 24px;
}

.add-content span {
  font-size: 13px;
}

/* 新建卡片样式 */
.new-card {
  border: 2px solid var(--primary-color);
  box-shadow: 0 0 12px rgba(var(--primary-color-rgb), 0.2);
}

.new-card .card-header {
  background: linear-gradient(135deg, rgba(var(--primary-color-rgb), 0.1) 0%, transparent 100%);
}

/* 新建标识样式 */
.status-badge.new-badge {
  background: rgba(99, 102, 241, 0.2);
  color: #6366f1;
}

/* 提供商选择下拉框 */
.provider-select {
  width: 100%;
  padding: 6px 10px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  outline: none;
}

.provider-select:focus {
  border-color: var(--primary-color);
}

.provider-select option {
  padding: 6px;
  background: var(--main-bg);
  color: var(--text-primary);
}

.provider-select option:disabled {
  color: var(--text-muted);
  background: var(--hover-bg);
}

/* 删除按钮样式 */
.btn-delete {
  color: #ef4444;
}

.btn-delete:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}
</style>
