<template>
  <div class="agent-config-view">
    <header class="view-header">
      <h1>{{ t('智能体配置', 'Agent Configuration') }}</h1>
      <p class="subtitle">{{ t('配置智能体参数和行为', 'Configure agent parameters and behaviors') }}</p>
    </header>
    
    <div class="agent-list" v-if="!selectedAgent">
      <div class="list-header">
        <h3>{{ t('选择智能体', 'Select Agent') }}</h3>
        <button class="btn-add-agent" @click="createNewAgent">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          {{ t('新建智能体', 'New Agent') }}
        </button>
      </div>
      
      <div class="agent-cards">
        <div 
          class="agent-card" 
          v-for="agent in agents" 
          :key="agent.id"
          @click="selectAgent(agent)"
        >
          <div class="agent-avatar" :style="{ background: getAvatarColor(agent.name) }">
            {{ agent.name.charAt(0).toUpperCase() }}
          </div>
          <div class="agent-info">
            <h4>{{ agent.name }}</h4>
            <p>{{ agent.description || t('暂无描述', 'No description') }}</p>
          </div>
          <div class="agent-meta">
            <span class="model-badge">{{ agent.modelId }}</span>
          </div>
        </div>
      </div>
    </div>
    
    <div class="agent-edit" v-else>
      <div class="back-btn" @click="selectedAgent = null">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="15,18 9,12 15,6"/>
        </svg>
        {{ t('返回列表', 'Back to List') }}
      </div>
      
      <div class="edit-form">
        <div class="form-section">
          <h3>{{ t('基本信息', 'Basic Info') }}</h3>
          
          <div class="form-group">
            <label>{{ t('头像', 'Avatar') }}</label>
            <div class="avatar-editor">
              <div class="avatar-preview" :style="{ background: getAvatarColor(selectedAgent.name) }">
                {{ selectedAgent.name.charAt(0).toUpperCase() }}
              </div>
              <div class="avatar-actions">
                <button class="btn-secondary" @click="changeAvatarColor">
                  {{ t('更换颜色', 'Change Color') }}
                </button>
              </div>
            </div>
          </div>
          
          <div class="form-group">
            <label>{{ t('名称', 'Name') }}</label>
            <input 
              type="text" 
              v-model="selectedAgent.name"
              :placeholder="t('输入智能体名称', 'Enter agent name')"
            />
          </div>
          
          <div class="form-group">
            <label>{{ t('描述', 'Description') }}</label>
            <textarea 
              v-model="selectedAgent.description"
              :placeholder="t('输入智能体描述', 'Enter agent description')"
              rows="3"
            ></textarea>
          </div>
        </div>
        
        <div class="form-section">
          <h3>{{ t('模型配置', 'Model Config') }}</h3>
          
          <div class="form-group">
            <label>{{ t('选择模型', 'Select Model') }}</label>
            <select v-model="selectedAgent.modelId">
              <option v-for="config in modelConfigs" :key="config.provider" :value="config.model">
                {{ config.provider }} - {{ config.model }}
              </option>
            </select>
          </div>
          
          <div class="form-group">
            <label>{{ t('系统提示词', 'System Prompt') }}</label>
            <textarea 
              v-model="selectedAgent.systemPrompt"
              :placeholder="t('输入系统提示词', 'Enter system prompt')"
              rows="5"
            ></textarea>
          </div>
        </div>
        
        <div class="form-section">
          <h3>{{ t('个性化设置', 'Personalization') }}</h3>
          
          <div class="form-group">
            <label>{{ t('温度 (Temperature)', 'Temperature') }}</label>
            <div class="slider-input">
              <input 
                type="range" 
                v-model.number="selectedAgent.temperature"
                min="0" 
                max="2" 
                step="0.1"
              />
              <span>{{ selectedAgent.temperature }}</span>
            </div>
            <p class="hint">{{ t('较低的值产生更一致的输出，较高的值产生更多样化的输出', 'Lower values produce more consistent output, higher values produce more diverse output') }}</p>
          </div>
          
          <div class="form-group">
            <label>{{ t('最大令牌数', 'Max Tokens') }}</label>
            <input 
              type="number" 
              v-model.number="selectedAgent.maxTokens"
              min="100"
              max="128000"
            />
          </div>
        </div>
        
        <div class="form-actions">
          <button class="btn-danger" @click="deleteAgent" v-if="!isNewAgent">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3,6 5,6 21,6"/>
              <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
            </svg>
            {{ t('删除智能体', 'Delete Agent') }}
          </button>
          <button class="btn-primary" @click="saveAgent" :disabled="saving">
            {{ saving ? t('保存中...', 'Saving...') : t('保存配置', 'Save Config') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAgentStore } from '@/stores/agent'
import { api } from '@/api'
import type { AgentConfig } from '@/types'

const settingsStore = useSettingsStore()
const agentStore = useAgentStore()

const agents = ref<AgentConfig[]>([])
const selectedAgent = ref<AgentConfig | null>(null)
const isNewAgent = ref(false)
const saving = ref(false)
const modelConfigs = ref<{provider: string, model: string}[]>([])

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function getAvatarColor(name: string): string {
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
  const index = name.charCodeAt(0) % colors.length
  return colors[index]
}

function changeAvatarColor() {
  // 随机更改颜色（通过修改名称的第一个字符触发不同颜色）
  // 实际应用中可以有更好的方式
  alert(t('头像颜色根据名称自动生成', 'Avatar color is auto-generated based on name'))
}

function selectAgent(agent: AgentConfig) {
  selectedAgent.value = { ...agent }
  isNewAgent.value = false
}

function createNewAgent() {
  const now = new Date().toISOString()
  selectedAgent.value = {
    id: '',
    name: t('新智能体', 'New Agent'),
    description: '',
    modelId: modelConfigs.value[0]?.model || 'gpt-4o',
    systemPrompt: '',
    temperature: 0.7,
    maxTokens: 4096,
    created_at: now,
    updated_at: now
  }
  isNewAgent.value = true
}

async function saveAgent() {
  if (!selectedAgent.value) return
  
  if (!selectedAgent.value.name.trim()) {
    alert(t('请输入智能体名称', 'Please enter agent name'))
    return
  }
  
  saving.value = true
  try {
    const result = await api.saveAgent(selectedAgent.value)
    if (result.success) {
      await agentStore.loadAgents()
      agents.value = [...agentStore.agents]
      selectedAgent.value = null
      isNewAgent.value = false
      alert(t('智能体已保存', 'Agent saved'))
    } else {
      alert(result.error || t('保存失败', 'Save failed'))
    }
  } catch (error) {
    console.error('Failed to save agent:', error)
    alert(t('保存失败', 'Save failed'))
  } finally {
    saving.value = false
  }
}

async function deleteAgent() {
  if (!selectedAgent.value) return
  
  if (!confirm(t('确定要删除这个智能体吗？', 'Are you sure you want to delete this agent?'))) {
    return
  }
  
  try {
    const result = await api.deleteAgent(selectedAgent.value.id)
    if (result.success) {
      await agentStore.loadAgents()
      agents.value = [...agentStore.agents]
      selectedAgent.value = null
      alert(t('智能体已删除', 'Agent deleted'))
    } else {
      alert(result.error || t('删除失败', 'Delete failed'))
    }
  } catch (error) {
    console.error('Failed to delete agent:', error)
    alert(t('删除失败', 'Delete failed'))
  }
}

onMounted(async () => {
  await agentStore.loadAgents()
  agents.value = [...agentStore.agents]
  
  await agentStore.loadModelConfigs()
  modelConfigs.value = agentStore.modelConfigs.map(c => ({
    provider: c.provider,
    model: c.model
  }))
  
  if (modelConfigs.value.length === 0) {
    modelConfigs.value = [
      { provider: 'OpenAI', model: 'gpt-4o' },
      { provider: 'Anthropic', model: 'claude-3-5-sonnet-20241022' },
      { provider: 'DeepSeek', model: 'deepseek-chat' }
    ]
  }
})
</script>

<style scoped>
.agent-config-view {
  padding: 32px;
}

.view-header {
  margin-bottom: 32px;
}

.view-header h1 {
  font-size: 28px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 16px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.list-header h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.btn-add-agent {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--primary-color);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-add-agent:hover {
  opacity: 0.9;
}

.btn-add-agent svg {
  width: 18px;
  height: 18px;
}

.agent-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.agent-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.agent-card:hover {
  border-color: var(--primary-color);
  background: var(--hover-bg);
}

.agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 20px;
  flex-shrink: 0;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-info h4 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.agent-info p {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.agent-meta {
  flex-shrink: 0;
}

.model-badge {
  padding: 4px 8px;
  background: var(--hover-bg);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  margin-bottom: 24px;
  transition: color 0.2s;
}

.back-btn:hover {
  color: var(--text-primary);
}

.back-btn svg {
  width: 20px;
  height: 20px;
}

.edit-form {
  max-width: 800px;
}

.form-section {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
}

.form-section h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 20px 0;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.form-group {
  margin-bottom: 20px;
}

.form-group:last-child {
  margin-bottom: 0;
}

.form-group label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.form-group input[type="text"],
.form-group input[type="number"],
.form-group textarea,
.form-group select {
  width: 100%;
  padding: 12px 16px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
}

.form-group textarea {
  resize: vertical;
  min-height: 100px;
}

.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--primary-color);
}

.avatar-editor {
  display: flex;
  align-items: center;
  gap: 20px;
}

.avatar-preview {
  width: 64px;
  height: 64px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 28px;
}

.btn-secondary {
  padding: 10px 16px;
  background: var(--hover-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: var(--border-color);
}

.slider-input {
  display: flex;
  align-items: center;
  gap: 16px;
}

.slider-input input[type="range"] {
  flex: 1;
  height: 6px;
  background: var(--border-color);
  border-radius: 3px;
  -webkit-appearance: none;
  appearance: none;
}

.slider-input input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  background: var(--primary-color);
  border-radius: 50%;
  cursor: pointer;
}

.slider-input span {
  width: 40px;
  text-align: center;
  font-weight: 500;
  color: var(--text-primary);
}

.hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.form-actions {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.btn-primary {
  padding: 12px 24px;
  background: var(--primary-color);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
  margin-left: auto;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-danger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: transparent;
  border: 1px solid #ef4444;
  border-radius: 8px;
  color: #ef4444;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-danger:hover {
  background: #ef4444;
  color: white;
}

.btn-danger svg {
  width: 18px;
  height: 18px;
}
</style>