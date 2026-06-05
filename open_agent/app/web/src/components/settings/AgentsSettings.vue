<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('智能体设置', 'Agent Settings') }}</h3>
      <p>{{ t('管理您的 AI 智能体', 'Manage your AI agents') }}</p>
    </div>
    
    <div class="settings-search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.3-4.3"/>
      </svg>
      <input v-model="searchQuery" type="search" :placeholder="t('搜索智能体名称、描述或模型', 'Search agents by name, description, or model')" />
      <button v-if="searchQuery" type="button" @click="searchQuery = ''">{{ t('清除', 'Clear') }}</button>
    </div>

    <div class="agents-list">
      <div 
        class="agent-card" 
        v-for="agent in filteredAgents" 
        :key="agent.id"
      >
        <div class="agent-avatar seal-avatar" :style="{ background: getAgentColor(agent.id) }" :aria-label="agent.name">
          <span class="seal-avatar-body">
            <span class="seal-avatar-face">
              <span class="seal-avatar-eye left"></span>
              <span class="seal-avatar-eye right"></span>
              <span class="seal-avatar-nose"></span>
            </span>
            <span class="seal-avatar-flipper left"></span>
            <span class="seal-avatar-flipper right"></span>
          </span>
        </div>
        <div class="agent-info">
          <div class="agent-title-row">
            <h4>{{ agent.name }}</h4>
            <span class="agent-badge" :class="{ primary: isMainAgent(agent) }">
              {{ isMainAgent(agent) ? t('主智能体', 'Main') : t('角色智能体', 'Profile') }}
            </span>
            <span v-if="!agent.enabled" class="agent-badge muted">{{ t('已停用', 'Disabled') }}</span>
          </div>
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
          <button v-if="!isMainAgent(agent)" class="btn-icon btn-delete" @click="deleteAgent(agent)" :title="t('删除', 'Delete')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3,6 5,6 21,6"/>
              <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
            </svg>
          </button>
        </div>
      </div>
      
      <div v-if="filteredAgents.length === 0" class="empty-state">
        {{ t('没有匹配的智能体', 'No matching agents') }}
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
          <div class="form-group" v-if="!isEditingMainAgent">
            <label>{{ t('状态', 'Status') }}</label>
            <label class="switch-row">
              <input v-model="editingAgent.enabled" type="checkbox" />
              <span>{{ editingAgent.enabled ? t('启用角色智能体', 'Profile enabled') : t('停用角色智能体', 'Profile disabled') }}</span>
            </label>
          </div>
          <div class="form-group">
            <label>{{ t('访问权限', 'Access Permission') }}</label>
            <select v-model="editingAgent.permission_mode">
              <option value="default">{{ t('默认权限（需要审批）', 'Default access (approval required)') }}</option>
              <option value="full">{{ t('完全访问权限', 'Full access') }}</option>
            </select>
          </div>
          <div class="form-group" v-if="!isEditingMainAgent">
            <label>{{ t('协作能力', 'Delegation') }}</label>
            <label class="switch-row">
              <input v-model="editingAgent.allow_delegation" type="checkbox" />
              <span>{{ t('允许该角色继续调用其他角色智能体', 'Allow this profile to delegate to other agents') }}</span>
            </label>
          </div>
          <div class="profile-capabilities" v-if="!isEditingMainAgent && editMode === 'edit'">
            <div class="section-title-row">
              <div>
                <h4>{{ t('角色能力', 'Profile Capabilities') }}</h4>
                <p>{{ t('只影响当前角色自己的技能和 MCP 配置', 'Only affects this profile skills and MCP config') }}</p>
              </div>
              <button class="btn-secondary small" @click="loadProfileCapabilities">{{ t('刷新', 'Refresh') }}</button>
            </div>

            <div class="capability-panel">
              <div class="capability-header">
                <strong>{{ t('角色技能', 'Profile Skills') }}</strong>
                <span>{{ profileSkills.length }}</span>
              </div>
              <div class="profile-skill-list" v-if="profileSkills.length">
                <div class="profile-skill-item" v-for="skill in profileSkills" :key="skill.name">
                  <div>
                    <strong>{{ skill.name }}</strong>
                    <p>{{ skill.description }}</p>
                  </div>
                  <button class="btn-icon btn-delete" @click="deleteProfileSkill(skill.name)" :title="t('删除', 'Delete')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3,6 5,6 21,6"/>
                      <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
                    </svg>
                  </button>
                </div>
              </div>
              <p v-else class="empty-hint">{{ t('当前角色还没有自己的技能', 'No profile-specific skills yet') }}</p>
              <div class="new-skill-form">
                <input v-model="newSkill.name" type="text" :placeholder="t('技能名称', 'Skill name')" />
                <input v-model="newSkill.description" type="text" :placeholder="t('技能描述', 'Skill description')" />
                <textarea v-model="newSkill.content" rows="3" :placeholder="t('技能正文，会写入 SKILL.md', 'Skill body written to SKILL.md')"></textarea>
                <button class="btn-secondary" @click="saveProfileSkill">{{ t('保存角色技能', 'Save Profile Skill') }}</button>
              </div>
            </div>

            <div class="capability-panel">
              <div class="capability-header">
                <strong>{{ t('角色 MCP', 'Profile MCP') }}</strong>
                <span>{{ profileMcpPath }}</span>
              </div>
              <textarea class="mcp-json-editor" v-model="profileMcpJson" rows="7"></textarea>
              <button class="btn-secondary" @click="saveProfileMcp">{{ t('保存角色 MCP', 'Save Profile MCP') }}</button>
            </div>
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
import { ref, computed, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useAgentStore } from '@/stores/agent'
import { agentApi } from '@/api'
import type { AgentConfig } from '@/types'

const settingsStore = useSettingsStore()
const agentStore = useAgentStore()
const searchQuery = ref('')

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
  permission_mode: 'default',
  allow_delegation: false,
  enabled: true,
  created_at: '',
  updated_at: ''
})

const isEditingMainAgent = computed(() => editingAgent.value.id === 'main')
const profileSkills = ref<Array<{ name: string; description: string; path: string; content: string }>>([])
const profileMcpJson = ref('{\n  "mcpServers": {}\n}')
const profileMcpPath = ref('')
const newSkill = ref({
  name: '',
  description: '',
  content: '',
})

function isMainAgent(agent: AgentConfig): boolean {
  return agent.id === 'main'
}

const filteredAgents = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return agentStore.agents
  return agentStore.agents.filter((agent) => {
    const modelName = getModelName(agent.model_id)
    const role = isMainAgent(agent) ? 'main 主智能体' : 'profile 角色智能体'
    const status = agent.enabled === false ? 'disabled 已停用' : 'enabled 已启用'
    return [
      agent.id,
      agent.name,
      agent.description,
      agent.system_prompt,
      agent.model_id,
      modelName,
      role,
      status,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
      .includes(query)
  })
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
  if (agent.id !== 'main') {
    loadProfileCapabilities()
  }
}

// 创建智能体
function createAgent() {
  editMode.value = 'create'
  const defaultModel = agentStore.modelConfigs.find(m => m.is_default)?.id || agentStore.modelConfigs[0]?.id || ''
  editingAgent.value = {
    id: `profile_${Date.now()}`,
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
    permission_mode: 'default',
    allow_delegation: false,
    enabled: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  }
  showEditDialog.value = true
  profileSkills.value = []
  profileMcpJson.value = '{\n  "mcpServers": {}\n}'
  profileMcpPath.value = ''
}

async function loadProfileCapabilities() {
  if (!editingAgent.value.id || editingAgent.value.id === 'main') return
  try {
    const [skills, mcp] = await Promise.all([
      agentApi.listProfileSkills(editingAgent.value.id),
      agentApi.getProfileMcp(editingAgent.value.id),
    ])
    profileSkills.value = skills.skills || []
    profileMcpPath.value = mcp.path || ''
    profileMcpJson.value = JSON.stringify(mcp.config || { mcpServers: {} }, null, 2)
  } catch (error) {
    console.error('Failed to load profile capabilities:', error)
  }
}

async function saveProfileSkill() {
  if (!editingAgent.value.id || editingAgent.value.id === 'main') return
  if (!newSkill.value.name.trim() || !newSkill.value.description.trim() || !newSkill.value.content.trim()) {
    alert(t('请填写技能名称、描述和正文', 'Please fill skill name, description and body'))
    return
  }
  try {
    const result = await agentApi.saveProfileSkill(editingAgent.value.id, { ...newSkill.value })
    if (result.success) {
      newSkill.value = { name: '', description: '', content: '' }
      await loadProfileCapabilities()
    } else {
      alert(result.error || t('保存技能失败', 'Failed to save skill'))
    }
  } catch (error) {
    console.error('Failed to save profile skill:', error)
    alert(t('保存技能失败', 'Failed to save skill'))
  }
}

async function deleteProfileSkill(skillName: string) {
  if (!editingAgent.value.id || editingAgent.value.id === 'main') return
  if (!confirm(t(`确定删除角色技能 "${skillName}" 吗？`, `Delete profile skill "${skillName}"?`))) return
  try {
    const result = await agentApi.deleteProfileSkill(editingAgent.value.id, skillName)
    if (result.success) {
      await loadProfileCapabilities()
    } else {
      alert(result.error || t('删除技能失败', 'Failed to delete skill'))
    }
  } catch (error) {
    console.error('Failed to delete profile skill:', error)
    alert(t('删除技能失败', 'Failed to delete skill'))
  }
}

async function saveProfileMcp() {
  if (!editingAgent.value.id || editingAgent.value.id === 'main') return
  try {
    const config = JSON.parse(profileMcpJson.value || '{}')
    const result = await agentApi.saveProfileMcp(editingAgent.value.id, config)
    if (result.success) {
      profileMcpPath.value = result.data?.path || profileMcpPath.value
      profileMcpJson.value = JSON.stringify(result.data?.config || config, null, 2)
    } else {
      alert(result.error || t('保存 MCP 失败', 'Failed to save MCP'))
    }
  } catch (error) {
    console.error('Failed to save profile MCP:', error)
    alert(t('MCP JSON 格式不正确', 'Invalid MCP JSON'))
  }
}

// 删除智能体
async function deleteAgent(agent: AgentConfig) {
  if (isMainAgent(agent)) {
    return
  }
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
  
  if (editingAgent.value.id === 'main') {
    editingAgent.value.enabled = true
    editingAgent.value.allow_delegation = true
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
  profileSkills.value = []
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

.settings-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
}

.settings-search svg {
  width: 16px;
  height: 16px;
  color: var(--text-muted);
  flex: 0 0 auto;
}

.settings-search input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
}

.settings-search button {
  flex: 0 0 auto;
  border: 0;
  background: transparent;
  color: var(--primary-color);
  cursor: pointer;
  font-size: 12px;
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
  border-radius: 14px;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 600;
  flex-shrink: 0;
}

.seal-avatar {
  position: relative;
  overflow: visible;
  background: linear-gradient(145deg, #dff3ff 0%, #9cc4df 100%) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.58), 0 8px 18px rgba(72, 104, 132, 0.16);
}

.seal-avatar-body {
  position: relative;
  width: 72%;
  height: 58%;
  border-radius: 60% 58% 52% 54%;
  background: linear-gradient(145deg, #f7fbff 0%, #cbddeb 62%, #91a9bd 100%);
  box-shadow: inset 0 1px 3px rgba(255, 255, 255, 0.85), 0 3px 8px rgba(72, 104, 132, 0.18);
}

.seal-avatar-face {
  position: absolute;
  top: 24%;
  right: 17%;
  width: 45%;
  height: 46%;
}

.seal-avatar-eye {
  position: absolute;
  top: 6%;
  width: 18%;
  height: 18%;
  border-radius: 50%;
  background: #263746;
}

.seal-avatar-eye.left {
  left: 8%;
}

.seal-avatar-eye.right {
  right: 8%;
}

.seal-avatar-nose {
  position: absolute;
  left: 42%;
  top: 50%;
  width: 20%;
  height: 16%;
  border-radius: 50%;
  background: #38495a;
}

.seal-avatar-flipper {
  position: absolute;
  bottom: -14%;
  width: 32%;
  height: 30%;
  border-radius: 999px;
  background: #91a9bd;
}

.seal-avatar-flipper.left {
  left: 8%;
  transform: rotate(-24deg);
}

.seal-avatar-flipper.right {
  right: 8%;
  transform: rotate(24deg);
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-info h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.agent-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.agent-badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
  font-size: 11px;
  line-height: 1;
}

.agent-badge.primary {
  color: var(--primary-color);
  background: var(--primary-light, rgba(59, 130, 246, 0.1));
  border-color: rgba(59, 130, 246, 0.28);
}

.agent-badge.muted {
  color: var(--text-muted);
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

.empty-state {
  padding: 18px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
  color: var(--text-muted);
  text-align: center;
  font-size: 13px;
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
  max-width: 720px;
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

.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 36px;
  padding: 8px 10px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  font-weight: 400;
  cursor: pointer;
}

.switch-row input {
  width: 16px;
  height: 16px;
  accent-color: var(--primary-color);
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

.form-group .switch-row input {
  width: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  accent-color: var(--primary-color);
  flex: 0 0 auto;
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

.profile-capabilities {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
}

.section-title-row,
.capability-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-title-row h4 {
  margin: 0 0 4px 0;
  font-size: 14px;
  color: var(--text-primary);
}

.section-title-row p,
.empty-hint {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.capability-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--card-bg);
}

.capability-header strong {
  font-size: 13px;
  color: var(--text-primary);
}

.capability-header span {
  min-width: 0;
  color: var(--text-muted);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-skill-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 180px;
  overflow-y: auto;
}

.profile-skill-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--input-bg);
}

.profile-skill-item strong {
  display: block;
  font-size: 13px;
  color: var(--text-primary);
  margin-bottom: 3px;
}

.profile-skill-item p {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.new-skill-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.new-skill-form input,
.new-skill-form textarea,
.mcp-json-editor {
  padding: 10px 12px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
}

.mcp-json-editor {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  resize: vertical;
}

.btn-secondary {
  align-self: flex-start;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--input-bg);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.btn-secondary:hover {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.btn-secondary.small {
  padding: 6px 10px;
  font-size: 12px;
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
