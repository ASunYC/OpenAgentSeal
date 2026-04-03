<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('智能体设置', 'Agent Settings') }}</h3>
      <p>{{ t('管理您的 AI 智能体', 'Manage your AI agents') }}</p>
    </div>
    
    <div class="agents-list">
      <div 
        class="agent-card" 
        v-for="agent in agentStore.agents" 
        :key="agent.id"
      >
        <div class="agent-avatar" :style="{ background: getAgentColor(agent.id) }">
          {{ agent.name?.charAt(0)?.toUpperCase() }}
        </div>
        <div class="agent-info">
          <h4>{{ agent.name }}</h4>
          <p class="agent-model">{{ getModelName(agent.model_id) }}</p>
          <p class="agent-steps">{{ t('最大步骤', 'Max Steps') }}: {{ agent.max_steps || 100 }}</p>
        </div>
        <div class="agent-actions">
          <button class="btn-icon" @click="editAgent(agent)" :title="t('编辑', 'Edit')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
          <button class="btn-icon btn-delete" @click="deleteAgent(agent)" :title="t('删除', 'Delete')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3,6 5,6 21,6"/>
              <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
            </svg>
          </button>
        </div>
      </div>
      
      <div class="add-agent" @click="createAgent">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        <span>{{ t('新建智能体', 'New Agent') }}</span>
      </div>
    </div>

    <!-- 编辑智能体对话框 -->
    <div class="modal-overlay" v-if="showEditDialog" @click="closeEditDialog">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <h3>{{ editMode === 'edit' ? t('编辑智能体', 'Edit Agent') : t('新建智能体', 'New Agent') }}</h3>
          <button class="btn-close" @click="closeEditDialog">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>{{ t('智能体名称', 'Agent Name') }}</label>
            <input v-model="editingAgent.name" type="text" :placeholder="t('输入智能体名称', 'Enter agent name')" />
          </div>
          <div class="form-group">
            <label>{{ t('描述', 'Description') }}</label>
            <textarea v-model="editingAgent.description" :placeholder="t('输入描述', 'Enter description')" rows="2"></textarea>
          </div>
          <div class="form-group">
            <label>{{ t('关联模型', 'Model') }}</label>
            <select v-model="editingAgent.model_id">
              <option v-for="model in agentStore.modelConfigs" :key="model.id" :value="model.id">
                {{ model.display_name || model.name }}
              </option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ t('最大步骤数', 'Max Steps') }}</label>
            <input v-model.number="editingAgent.max_steps" type="number" min="1" max="500" :placeholder="t('默认 100', 'Default 100')" />
            <small class="form-hint">{{ t('设置智能体单次任务的最大步骤数', 'Set maximum steps for single task') }}</small>
          </div>
          <div class="form-group">
            <label>{{ t('温度参数', 'Temperature') }}</label>
            <input v-model.number="editingAgent.temperature" type="number" min="0" max="2" step="0.1" />
            <small class="form-hint">{{ t('控制回复的随机性 (0-2)', 'Controls randomness (0-2)') }}</small>
          </div>
          <div class="form-group">
            <label>{{ t('系统提示词', 'System Prompt') }}</label>
            <textarea v-model="editingAgent.system_prompt" :placeholder="t('输入系统提示词', 'Enter system prompt')" rows="4"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-cancel" @click="closeEditDialog">{{ t('取消', 'Cancel') }}</button>
          <button class="btn-save" @click="saveAgent">{{ t('保存', 'Save') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAgentStore } from '@/stores/agent'
import type { AgentConfig } from '@/types'

const settingsStore = useSettingsStore()
const agentStore = useAgentStore()

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

// 编辑对话框状态
const showEditDialog = ref(false)
const editMode = ref<'edit' | 'create'>('create')
const editingAgent = ref<AgentConfig>({
  id: '',
  name: '',
  model_id: '',
  description: '',
  avatar: '🤖',
  system_prompt: '',
  temperature: 0.7,
  max_tokens: 4096,
  max_steps: 100,
  tools: [],
  mcp_servers: [],
  created_at: '',
  updated_at: ''
})

// 获取智能体颜色
function getAgentColor(agentId: string): string {
  const agent = agentStore.agents.find(a => a.id === agentId)
  if (!agent) return '#3b82f6'
  const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4']
  const index = agent.name.charCodeAt(0) % colors.length
  return colors[index]
}

// 获取模型名称
function getModelName(modelId: string): string {
  const model = agentStore.modelConfigs.find(m => m.id === modelId)
  return model?.display_name || model?.name || t('未设置', 'Not set')
}

// 编辑智能体
function editAgent(agent: AgentConfig) {
  editMode.value = 'edit'
  editingAgent.value = { ...agent }
  showEditDialog.value = true
}

// 创建智能体
function createAgent() {
  editMode.value = 'create'
  const defaultModel = agentStore.modelConfigs.find(m => m.is_default)?.id || agentStore.modelConfigs[0]?.id || ''
  editingAgent.value = {
    id: `agent_${Date.now()}`,
    name: t('新智能体', 'New Agent'),
    model_id: defaultModel,
    description: '',
    avatar: '🤖',
    system_prompt: '',
    temperature: 0.7,
    max_tokens: 4096,
    max_steps: 100,
    tools: [],
    mcp_servers: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  }
  showEditDialog.value = true
}

// 删除智能体
async function deleteAgent(agent: AgentConfig) {
  if (confirm(t(`确定要删除智能体 "${agent.name}" 吗？`, `Are you sure you want to delete agent "${agent.name}"?`))) {
    await agentStore.deleteAgent(agent.id)
  }
}

// 保存智能体
async function saveAgent() {
  if (!editingAgent.value.name.trim()) {
    alert(t('请输入智能体名称', 'Please enter agent name'))
    return
  }
  
  editingAgent.value.updated_at = new Date().toISOString()
  const success = await agentStore.saveAgent(editingAgent.value)
  
  if (success) {
    closeEditDialog()
  } else {
    alert(t('保存失败，请重试', 'Failed to save, please try again'))
  }
}

// 关闭编辑对话框
function closeEditDialog() {
  showEditDialog.value = false
}

onMounted(async () => {
  await agentStore.loadAgents()
  await agentStore.loadModelConfigs()
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

.agents-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.agent-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--main-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.agent-avatar {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 600;
  flex-shrink: 0;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-info h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.agent-info .agent-model {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0 0 2px 0;
}

.agent-info .agent-steps {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
}

.agent-actions {
  display: flex;
  gap: 8px;
}

.btn-icon {
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

.btn-icon:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.btn-icon.btn-delete:hover {
  background: #fee2e2;
  color: #ef4444;
}

.btn-icon svg {
  width: 16px;
  height: 16px;
}

.add-agent {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px;
  background: var(--main-bg);
  border: 1px dashed var(--border-color);
  border-radius: 12px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s;
}

.add-agent:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.add-agent svg {
  width: 20px;
  height: 20px;
}

.add-agent span {
  font-size: 14px;
}

/* 对话框样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.modal {
  background: var(--card-bg);
  border-radius: 16px;
  width: 100%;
  max-width: 500px;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.btn-close {
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

.btn-close:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.btn-close svg {
  width: 16px;
  height: 16px;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.form-group input,
.form-group textarea,
.form-group select {
  padding: 10px 12px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
}

.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--primary-color);
}

.form-hint {
  font-size: 11px;
  color: var(--text-muted);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
}

.btn-cancel {
  padding: 10px 20px;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.btn-cancel:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.btn-save {
  padding: 10px 20px;
  background: var(--primary-color);
  border: none;
  border-radius: 8px;
  color: white;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.btn-save:hover {
  opacity: 0.9;
}
</style>