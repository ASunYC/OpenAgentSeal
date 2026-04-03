import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AgentConfig, ModelConfig, ModelProvider } from '@/types'
import { api } from '@/api'

export const useAgentStore = defineStore('agent', () => {
  // 智能体列表
  const agents = ref<AgentConfig[]>([])
  
  // 当前选中的智能体ID
  const currentAgentId = ref<string>('')
  
  // 大模型配置列表
  const modelConfigs = ref<ModelConfig[]>([])
  
  // 大模型提供商列表
  const modelProviders = ref<ModelProvider[]>([
    {
      id: 'openai',
      name: 'OpenAI',
      models: [
        { id: 'gpt-4o', name: 'GPT-4o', description: '最新多模态模型' },
        { id: 'gpt-4-turbo', name: 'GPT-4 Turbo', description: '高性能推理模型' },
        { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo', description: '快速响应模型' }
      ]
    },
    {
      id: 'anthropic',
      name: 'Anthropic',
      models: [
        { id: 'claude-3-5-sonnet-20241022', name: 'Claude 3.5 Sonnet', description: '最新Claude模型' },
        { id: 'claude-3-opus-20240229', name: 'Claude 3 Opus', description: '最强推理能力' },
        { id: 'claude-3-haiku-20240307', name: 'Claude 3 Haiku', description: '快速响应模型' }
      ]
    },
    {
      id: 'deepseek',
      name: 'DeepSeek',
      models: [
        { id: 'deepseek-chat', name: 'DeepSeek Chat', description: '对话模型' },
        { id: 'deepseek-coder', name: 'DeepSeek Coder', description: '代码专用模型' }
      ]
    },
    {
      id: 'zhipu',
      name: '智谱AI',
      models: [
        { id: 'glm-4', name: 'GLM-4', description: '智谱最新模型' },
        { id: 'glm-4-flash', name: 'GLM-4-Flash', description: '快速响应模型' }
      ]
    },
    {
      id: 'moonshot',
      name: 'Moonshot',
      models: [
        { id: 'moonshot-v1-8k', name: 'Moonshot V1 8K', description: '8K上下文' },
        { id: 'moonshot-v1-32k', name: 'Moonshot V1 32K', description: '32K上下文' },
        { id: 'moonshot-v1-128k', name: 'Moonshot V1 128K', description: '128K上下文' }
      ]
    },
    {
      id: 'ollama',
      name: 'Ollama (本地)',
      models: [
        { id: 'llama3', name: 'Llama 3', description: 'Meta开源模型' },
        { id: 'qwen2', name: 'Qwen 2', description: '通义千问开源版' },
        { id: 'mistral', name: 'Mistral', description: 'Mistral AI模型' }
      ]
    }
  ])

  // 当前选中的智能体
  const currentAgent = computed(() => {
    return agents.value.find(a => a.id === currentAgentId.value)
  })

  // 加载智能体列表
  async function loadAgents() {
    try {
      agents.value = await api.getAgents()
    } catch (e) {
      console.error('Failed to load agents:', e)
    }
  }

  // 加载大模型配置
  async function loadModelConfigs() {
    try {
      modelConfigs.value = await api.getModelConfigs()
    } catch (e) {
      console.error('Failed to load model configs:', e)
    }
  }

  // 保存智能体配置
  async function saveAgent(agent: AgentConfig) {
    try {
      const response = await api.saveAgent(agent)
      if (response.success) {
        const index = agents.value.findIndex(a => a.id === agent.id)
        if (index >= 0) {
          agents.value[index] = agent
        } else {
          agents.value.push(agent)
        }
        return true
      }
    } catch (e) {
      console.error('Failed to save agent:', e)
    }
    return false
  }

  // 删除智能体
  async function deleteAgent(agentId: string) {
    try {
      const response = await api.deleteAgent(agentId)
      if (response.success) {
        agents.value = agents.value.filter(a => a.id !== agentId)
        if (currentAgentId.value === agentId) {
          currentAgentId.value = agents.value[0]?.id || ''
        }
        return true
      }
    } catch (e) {
      console.error('Failed to delete agent:', e)
    }
    return false
  }

  // 保存大模型配置
  async function saveModelConfig(config: ModelConfig) {
    try {
      const response = await api.saveModelConfig(config)
      if (response.success) {
        const index = modelConfigs.value.findIndex(c => c.id === config.id)
        if (index >= 0) {
          modelConfigs.value[index] = config
        } else {
          modelConfigs.value.push(config)
        }
        return true
      }
    } catch (e) {
      console.error('Failed to save model config:', e)
    }
    return false
  }

  // 删除大模型配置
  async function deleteModelConfig(configId: string) {
    try {
      const response = await api.deleteModelConfig(configId)
      if (response.success) {
        modelConfigs.value = modelConfigs.value.filter(c => c.id !== configId)
        return true
      }
    } catch (e) {
      console.error('Failed to delete model config:', e)
    }
    return false
  }

  // 选择智能体
  function selectAgent(agentId: string) {
    currentAgentId.value = agentId
  }

  // 创建新智能体
  function createNewAgent(): AgentConfig {
    const newAgent: AgentConfig = {
      id: `agent-${Date.now()}`,
      name: '新智能体',
      modelId: modelConfigs.value.find(c => c.isDefault)?.id || modelConfigs.value[0]?.id || '',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    }
    return newAgent
  }

  return {
    agents,
    currentAgentId,
    currentAgent,
    modelConfigs,
    modelProviders,
    loadAgents,
    loadModelConfigs,
    saveAgent,
    deleteAgent,
    saveModelConfig,
    deleteModelConfig,
    selectAgent,
    createNewAgent
  }
})