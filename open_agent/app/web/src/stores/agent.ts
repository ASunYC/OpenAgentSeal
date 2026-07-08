import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AgentConfig, ModelConfig } from '@/types'
import { api } from '@/api'

export const useAgentStore = defineStore('agent', () => {
  // 智能体列表
  const agents = ref<AgentConfig[]>([])
  
  // 当前选中的智能体ID
  const currentAgentId = ref<string>('')
  
  // 大模型配置列表
  const modelConfigs = ref<ModelConfig[]>([])
  
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
    const now = new Date().toISOString()
    const newAgent: AgentConfig = {
      id: `profile_${Date.now()}`,
      name: '新智能体',
      model_id: modelConfigs.value.find(c => c.is_default)?.id || modelConfigs.value[0]?.id || '',
      description: '',
      avatar: '',
      system_prompt: '',
      temperature: 0.7,
      max_tokens: 4096,
      max_steps: 100,
      tools: [],
      mcp_servers: [],
      permission_mode: 'default',
      allow_delegation: false,
      enabled: true,
      created_at: now,
      updated_at: now
    }
    return newAgent
  }

  return {
    agents,
    currentAgentId,
    currentAgent,
    modelConfigs,
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
