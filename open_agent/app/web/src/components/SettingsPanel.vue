<template>
  <div 
    class="settings-panel"
    :style="{ width: panelWidth + 'px' }"
  >
    <!-- 左侧拖拽手柄 -->
    <div
      class="resizer"
      :class="{ dragging: isDragging }"
      @mousedown="startDrag"
      title="拖拽调整宽度"
    >
      <div class="resizer-indicator"></div>
    </div>
    <!-- 面板头部 -->
    <header class="panel-header">
      <h2>{{ t('设置', 'Settings') }}</h2>
      <button class="btn-close" @click="$emit('close')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </header>
    
    <!-- 菜单列表 -->
    <div class="panel-body">
      <nav class="settings-menu">
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'dashboard' }"
          @click="switchTab('dashboard')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="7" height="7"/>
            <rect x="14" y="3" width="7" height="7"/>
            <rect x="14" y="14" width="7" height="7"/>
            <rect x="3" y="14" width="7" height="7"/>
          </svg>
          <span>{{ t('数据面板', 'Dashboard') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'workspace' }"
          @click="switchTab('workspace')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          <span>{{ t('工作目录', 'Workspace') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'user' }"
          @click="switchTab('user')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
          <span>{{ t('用户', 'User') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'models' }"
          @click="switchTab('models')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09A1.65 1.65 0 0 0 19.4 15z"/>
          </svg>
          <span>{{ t('模型', 'Models') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'agents' }"
          @click="switchTab('agents')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
            <circle cx="9" cy="7" r="4"/>
            <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
            <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
          </svg>
          <span>{{ t('智能体', 'Agents') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'sessions' }"
          @click="switchTab('sessions')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          <span>{{ t('会话', 'Sessions') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'skills' }"
          @click="switchTab('skills')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
          </svg>
          <span>{{ t('技能', 'Skills') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'mcp' }"
          @click="switchTab('mcp')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="4" y="4" width="16" height="16" rx="2" ry="2"/>
            <rect x="9" y="9" width="6" height="6"/>
            <line x1="9" y1="1" x2="9" y2="4"/>
            <line x1="15" y1="1" x2="15" y2="4"/>
            <line x1="9" y1="20" x2="9" y2="23"/>
            <line x1="15" y1="20" x2="15" y2="23"/>
            <line x1="20" y1="9" x2="23" y2="9"/>
            <line x1="20" y1="14" x2="23" y2="14"/>
            <line x1="1" y1="9" x2="4" y2="9"/>
            <line x1="1" y1="14" x2="4" y2="14"/>
          </svg>
          <span>{{ t('MCP', 'MCP') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'logs' }"
          @click="switchTab('logs')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
            <polyline points="10 9 9 9 8 9"/>
          </svg>
          <span>{{ t('日志', 'Logs') }}</span>
          <span class="badge">{{ t('开发中', 'Dev') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'tasks' }"
          @click="switchTab('tasks')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 16"/>
          </svg>
          <span>{{ t('定时任务', 'Tasks') }}</span>
          <span class="badge">{{ t('开发中', 'Dev') }}</span>
        </div>
        
        <div 
          class="menu-item" 
          :class="{ active: currentTab === 'system' }"
          @click="switchTab('system')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l-.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09A1.65 1.65 0 0 0 19.4 15z"/>
          </svg>
          <span>{{ t('系统', 'System') }}</span>
        </div>
      </nav>
      
      <!-- 内容区域 -->
      <div class="settings-content">
        <!-- 数据面板 -->
        <DashboardSettings v-if="currentTab === 'dashboard'" />
        
        <!-- 工作目录 -->
        <WorkspaceSettings v-else-if="currentTab === 'workspace'" />
        
        <!-- 用户设置 -->
        <UserSettings v-else-if="currentTab === 'user'" />
        
        <!-- 模型设置 -->
        <ModelsSettings v-else-if="currentTab === 'models'" />
        
        <!-- 智能体设置 -->
        <AgentsSettings v-else-if="currentTab === 'agents'" />
        
        <!-- 会话 -->
        <SessionsSettings v-else-if="currentTab === 'sessions'" />
        
        <!-- 技能 -->
        <SkillsSettings v-else-if="currentTab === 'skills'" />
        
        <!-- MCP -->
        <MCPSettings v-else-if="currentTab === 'mcp'" />
        
        <!-- 日志 -->
        <div v-else-if="currentTab === 'logs'" class="tab-content">
          <div class="content-header">
            <h3>{{ t('日志', 'Logs') }}</h3>
            <p>{{ t('功能开发中...', 'Feature under development...') }}</p>
          </div>
        </div>
        
        <!-- 定时任务 -->
        <div v-else-if="currentTab === 'tasks'" class="tab-content">
          <div class="content-header">
            <h3>{{ t('定时任务', 'Scheduled Tasks') }}</h3>
            <p>{{ t('功能开发中...', 'Feature under development...') }}</p>
          </div>
        </div>
        
        <!-- 系统设置 -->
        <SystemSettings v-else-if="currentTab === 'system'" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import DashboardSettings from '@/components/settings/DashboardSettings.vue'
import WorkspaceSettings from '@/components/settings/WorkspaceSettings.vue'
import UserSettings from '@/components/settings/UserSettings.vue'
import ModelsSettings from '@/components/settings/ModelsSettings.vue'
import AgentsSettings from '@/components/settings/AgentsSettings.vue'
import SessionsSettings from '@/components/settings/SessionsSettings.vue'
import SkillsSettings from '@/components/settings/SkillsSettings.vue'
import MCPSettings from '@/components/settings/MCPSettings.vue'
import SystemSettings from '@/components/settings/SystemSettings.vue'

const props = defineProps<{
  currentTab: string
  width?: number
}>()

const emit = defineEmits<{
  close: []
  switchTab: [tab: string]
  'update:width': [width: number]
}>()

const settingsStore = useSettingsStore()

// 拖拽相关
const isDragging = ref(false)
const startX = ref(0)
const startWidth = ref(0)
const minWidth = 500 // 最小宽度
const maxWidth = 1600 // 最大宽度

// 计算面板宽度
const panelWidth = computed({
  get: () => props.width || 900,
  set: (val) => emit('update:width', val)
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function switchTab(tab: string) {
  emit('switchTab', tab)
}

// 开始拖拽
const startDrag = (e: MouseEvent) => {
  isDragging.value = true
  startX.value = e.clientX
  startWidth.value = panelWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  // 添加事件监听
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
}

// 拖拽中
const onDrag = (e: MouseEvent) => {
  if (!isDragging.value) return
  const deltaX = startX.value - e.clientX // 向左拖拽增加宽度
  let newWidth = startWidth.value + deltaX
  newWidth = Math.max(minWidth, Math.min(maxWidth, newWidth))
  panelWidth.value = newWidth
}

// 结束拖拽
const stopDrag = () => {
  isDragging.value = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  // 移除事件监听
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
}
</script>

<style scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--card-bg);
  position: relative;
  min-width: 500px;
}

.resizer {
  position: absolute;
  left: 0;
  top: 0;
  width: 8px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
}

.resizer-indicator {
  width: 4px;
  height: 60px;
  background: var(--border-color);
  border-radius: 2px;
  transition: all 0.2s;
}

.resizer:hover .resizer-indicator {
  background: var(--primary-color, #3b82f6);
  height: 100px;
}

.resizer.dragging .resizer-indicator {
  background: var(--primary-color, #3b82f6);
  width: 4px;
  height: 100%;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
}

.panel-header h2 {
  font-size: 18px;
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
  width: 18px;
  height: 18px;
}

.panel-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.settings-menu {
  width: 160px;
  min-width: 160px;
  border-right: 1px solid var(--border-color);
  padding: 12px 0;
  overflow-y: auto;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  margin: 2px 8px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 14px;
  transition: all 0.2s;
  position: relative;
}

.menu-item:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.menu-item.active {
  background: var(--active-bg);
  color: var(--primary-color);
}

.menu-item svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.menu-item .badge {
  margin-left: auto;
  font-size: 10px;
  padding: 2px 6px;
  background: var(--border-color);
  border-radius: 4px;
  color: var(--text-muted);
}

.settings-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

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

.btn-primary {
  padding: 10px 20px;
  background: var(--primary-color);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s;
  align-self: flex-start;
}

.btn-primary:hover {
  opacity: 0.9;
}
</style>
