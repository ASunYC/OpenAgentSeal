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
              :placeholder="t('输入或选择模型', 'Enter or select model')"
              class="model-name-input"
            />
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
        
        <div class="card-footer">
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
import type { ModelConfig } from '@/types'

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
  display_name: string
  base_url?: string
  provider_type?: string
  is_default?: boolean
  showKey: boolean
  saving: boolean
  editing: boolean
  loadingModels: boolean
  newModel: string
}

const modelConfigs = reactive<LocalModelConfig[]>([])

// 可用的提供商列表
const availableProviders = [
  { value: 'openai', label: '🌐 OpenAI (GPT)' },
  { value: 'anthropic', label: '💜 Anthropic (Claude)' },
  { value: 'deepseek', label: '🐋 DeepSeek' },
  { value: 'zhipu', label: '🔮 智谱 AI (GLM)' },
  { value: 'qwen', label: '🌟 通义千问 (Qwen)' },
  { value: 'moonshot', label: '🌙 Moonshot (Kimi)' },
  { value: 'minimax', label: '🎯 MiniMax' },
  { value: 'volcano', label: '🔥 火山引擎' },
  { value: 'siliconflow', label: '💎 SiliconFlow' },
  { value: 'baichuan', label: '🏔️ 百川智能' },
  { value: 'ollama', label: '🦙 Ollama (本地)' },
  { value: 'custom', label: '⚙️ 自定义提供商' }
]

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
    display_name: '',
    base_url: '',
    provider_type: 'openai',
    showKey: false,
    saving: false,
    editing: true,
    loadingModels: false,
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
    config.provider_type = provider === 'anthropic' ? 'anthropic' : 'openai'
    
    // 设置默认 Base URL
    const defaultUrls: Record<string, string> = {
      openai: 'https://api.openai.com/v1',
      anthropic: 'https://api.anthropic.com',
      deepseek: 'https://api.deepseek.com',
      zhipu: 'https://open.bigmodel.cn/api/paas/v4',
      qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
      moonshot: 'https://api.moonshot.cn/v1',
      minimax: 'https://api.minimax.chat/v1',
      volcano: 'https://ark.cn-beijing.volces.com/api/v3',
      siliconflow: 'https://api.siliconflow.cn/v1',
      baichuan: 'https://api.baichuan-ai.com/v1',
      ollama: 'http://localhost:11434/v1'
    }
    config.base_url = defaultUrls[provider] || ''
    
    // 设置默认模型列表
    const defaultModels: Record<string, string[]> = {
      openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo', 'o1', 'o1-mini'],
      anthropic: ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229', 'claude-3-haiku-20240307', 'claude-3-5-haiku-20241022'],
      deepseek: ['deepseek-chat', 'deepseek-coder', 'deepseek-reasoner'],
      zhipu: ['glm-4', 'glm-4-flash', 'glm-4-plus', 'glm-3-turbo'],
      qwen: ['qwen-turbo', 'qwen-plus', 'qwen-max', 'qwen-max-longcontext'],
      moonshot: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'],
      minimax: ['abab6.5-chat', 'abab5.5-chat', 'abab5.5s-chat'],
      volcano: ['doubao-pro-32k', 'doubao-lite-32k'],
      siliconflow: ['Qwen/Qwen2.5-72B-Instruct', 'deepseek-ai/DeepSeek-V2.5'],
      baichuan: ['Baichuan4', 'Baichuan3-Turbo', 'Baichuan3-Turbo-128k'],
      ollama: ['llama3', 'llama3.1', 'mistral', 'codellama', 'qwen2']
    }
    config.models = defaultModels[provider] || []
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
  }
}

function selectModel(config: LocalModelConfig, model: string) {
  config.selectedModel = model
}

function editConfig(config: LocalModelConfig) {
  config.editing = !config.editing
}

function updateApiKey(config: LocalModelConfig, key: string) {
  config.apiKey = key
  // 标记为用户输入的新 API Key（非后端返回的掩码）
  config.isUserInput = true
}

function updateBaseUrl(config: LocalModelConfig, url: string) {
  config.base_url = url
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
      is_default: config.is_default
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
      display_name: config.display_name || '',
      base_url: config.base_url,
      provider_type: config.provider_type || 'openai',
      is_default: config.is_default || config.isDefault,
      showKey: false,
      saving: false,
      editing: false,
      loadingModels: false,
      newModel: ''
    })
  })
  
  // 如果没有配置，添加默认提供商
  if (modelConfigs.length === 0) {
    modelConfigs.push(
      {
        id: 'default_openai',
        provider: 'openai',
        provider_display_name: '🌐 OpenAI (GPT)',
        apiKey: '',
        apiKeyLength: 0,
        has_api_key: false,
        isUserInput: false,
        isNew: false,
        models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo', 'o1', 'o1-mini'],
        selectedModel: 'gpt-4o',
        display_name: '',
        showKey: false,
        saving: false,
        editing: false,
        loadingModels: false,
        newModel: ''
      },
      {
        id: 'default_anthropic',
        provider: 'anthropic',
        provider_display_name: '💜 Anthropic (Claude)',
        apiKey: '',
        apiKeyLength: 0,
        has_api_key: false,
        isUserInput: false,
        isNew: false,
        models: ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229', 'claude-3-haiku-20240307', 'claude-3-5-haiku-20241022'],
        selectedModel: 'claude-3-5-sonnet-20241022',
        display_name: '',
        showKey: false,
        saving: false,
        editing: false,
        loadingModels: false,
        newModel: ''
      }
    )
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
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}

.btn-save {
  width: 100%;
  padding: 8px;
  background: var(--primary-color);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 13px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-save:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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