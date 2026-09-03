<template>
  <aside class="desktop-sidebar" :class="{ collapsed, 'workspace-open': workspaceOpen }" aria-label="Desktop navigation">
    <div class="sidebar-brand-row">
      <div class="sidebar-brand" :title="collapsed ? 'OpenAgentSeal' : undefined">
        <img :src="appIcon" alt="" aria-hidden="true" />
        <span>OpenAgentSeal</span>
      </div>
      <button class="sidebar-collapse" type="button" :title="label('收起侧栏', 'Collapse sidebar')" @click="emit('toggle-collapse')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M9 4v16" />
        </svg>
      </button>
    </div>

    <nav class="sidebar-primary" :aria-label="label('快捷操作', 'Quick actions')">
      <button class="sidebar-nav-item sidebar-new-chat" type="button" :disabled="busy" :title="label('新会话', 'New chat')" @click="emit('new-chat')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z" />
        </svg>
        <span>{{ label('新会话', 'New chat') }}</span>
      </button>
      <button class="sidebar-nav-item" :class="{ active: activePanel === 'runtime' }" type="button" :aria-pressed="activePanel === 'runtime'" :title="label('对话与运行', 'Chats & runtime')" @click="emit('open-runtime')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M8 15.5 4 19v-4.4A6.6 6.6 0 0 1 10.6 4H13a6.6 6.6 0 0 1 6.4 5" />
          <path d="M10 14a5 5 0 0 0 5 5h3.2L21 21.5V19a5 5 0 0 0-3-9h-3a5 5 0 0 0-5 5Z" />
        </svg>
        <span>{{ label('对话与运行', 'Chats & runtime') }}</span>
      </button>
      <button v-if="browserEnabled" class="sidebar-nav-item" :class="{ active: activePanel === 'browser' }" type="button" :aria-pressed="activePanel === 'browser'" :title="label('浏览器', 'Browser')" @click="emit('open-browser')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z" />
        </svg>
        <span>{{ label('浏览器', 'Browser') }}</span>
      </button>
      <button v-if="sandboxEnabled" class="sidebar-nav-item" :class="{ active: activePanel === 'sandbox' }" type="button" :aria-pressed="activePanel === 'sandbox'" :title="label('沙盒', 'Sandbox')" @click="emit('open-sandbox')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="m4 17 6-6-6-6M12 19h8" />
        </svg>
        <span>{{ label('沙盒', 'Sandbox') }}</span>
      </button>
      <button class="sidebar-nav-item" type="button" :title="label('设置', 'Settings')" @click="emit('open-settings')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
        <span>{{ label('设置', 'Settings') }}</span>
      </button>
    </nav>

    <div v-if="!workspaceOpen" class="sidebar-spacer"></div>

    <section class="sidebar-workspace-section" :class="{ expanded: workspaceOpen }">
      <p class="sidebar-section-label">{{ label('工作区', 'Workspace') }}</p>
      <button class="sidebar-nav-item sidebar-workspace" type="button" :class="{ active: workspaceOpen }" :aria-pressed="workspaceOpen" :title="workspacePath || workspaceName" @click="emit('open-workspace')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
        </svg>
        <span>{{ workspaceName || label('未选择工作目录', 'No workspace selected') }}</span>
        <svg class="sidebar-workspace-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path :d="workspaceOpen ? 'm6 15 6-6 6 6' : 'm6 9 6 6 6-6'" />
        </svg>
      </button>
      <div v-if="workspaceOpen" class="sidebar-workspace-content">
        <slot name="workspace" />
      </div>
    </section>
  </aside>
</template>

<script setup lang="ts">
type WorkspacePanel = '' | 'browser' | 'runtime' | 'sandbox'

const props = defineProps<{
  activePanel: WorkspacePanel
  appIcon: string
  browserEnabled: boolean
  busy: boolean
  collapsed: boolean
  language: string
  sandboxEnabled: boolean
  workspaceName: string
  workspaceOpen: boolean
  workspacePath: string
}>()

const emit = defineEmits<{
  'new-chat': []
  'open-browser': []
  'open-runtime': []
  'open-sandbox': []
  'open-settings': []
  'open-workspace': []
  'toggle-collapse': []
}>()

function label(zh: string, en: string): string {
  return props.language === 'zh-CN' ? zh : en
}
</script>

<style scoped>
.desktop-sidebar {
  box-sizing: border-box;
  width: 232px;
  height: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 14px 10px 10px;
  border-right: 1px solid var(--border-color);
  background: color-mix(in srgb, var(--bg-secondary) 94%, var(--glass-bg-strong));
  color: var(--text-primary);
  overflow: hidden;
}

.sidebar-brand-row,
.sidebar-brand,
.sidebar-nav-item {
  display: flex;
  align-items: center;
}

.sidebar-brand-row {
  min-height: 42px;
  gap: 6px;
  margin-bottom: 18px;
}

.sidebar-brand {
  flex: 1;
  min-width: 0;
  gap: 8px;
  padding: 4px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 15px;
  font-weight: 750;
  text-align: left;
}

.sidebar-brand img {
  width: 26px;
  height: 26px;
  border-radius: 50%;
}

.sidebar-brand span,
.sidebar-nav-item span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-collapse {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  flex: 0 0 30px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.sidebar-collapse:hover,
.sidebar-nav-item:hover {
  background: color-mix(in srgb, var(--text-primary) 7%, transparent);
}

.sidebar-primary {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.sidebar-nav-item {
  width: 100%;
  min-height: 42px;
  gap: 12px;
  padding: 0 11px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}

.sidebar-nav-item.active {
  background: color-mix(in srgb, var(--text-primary) 9%, transparent);
}

.sidebar-nav-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sidebar-nav-item svg,
.sidebar-collapse svg {
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
}

.sidebar-spacer {
  flex: 1;
  min-height: 24px;
}

.sidebar-section-label {
  margin: 0 10px 7px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 650;
}

.sidebar-workspace {
  min-height: 46px;
}

.sidebar-workspace-chevron {
  margin-left: auto;
  width: 16px !important;
  height: 16px !important;
  flex-basis: 16px !important;
}

.sidebar-workspace-section.expanded {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  margin: 14px -10px -10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-color);
}

.sidebar-workspace-section.expanded .sidebar-section-label,
.sidebar-workspace-section.expanded .sidebar-workspace {
  margin-inline: 10px;
}

.sidebar-workspace-content {
  flex: 1 1 auto;
  min-height: 0;
  margin-top: 8px;
  overflow: hidden;
  border-top: 1px solid var(--border-color);
}

.desktop-sidebar.workspace-open {
  width: 340px;
}

.desktop-sidebar.workspace-open .sidebar-brand-row {
  flex-direction: row;
  min-height: 42px;
}

.desktop-sidebar.workspace-open .sidebar-brand {
  flex: 1;
  padding: 4px;
}

.desktop-sidebar.workspace-open .sidebar-brand span,
.desktop-sidebar.workspace-open .sidebar-nav-item span,
.desktop-sidebar.workspace-open .sidebar-section-label {
  display: block;
}

.desktop-sidebar.workspace-open .sidebar-nav-item {
  justify-content: flex-start;
  padding-inline: 11px;
}

.desktop-sidebar.workspace-open .sidebar-collapse {
  display: grid;
}

.desktop-sidebar.collapsed:not(.workspace-open) {
  width: 68px;
  padding-inline: 9px;
}

.desktop-sidebar.collapsed:not(.workspace-open) .sidebar-brand-row {
  flex-direction: column;
  min-height: auto;
}

.desktop-sidebar.collapsed:not(.workspace-open) .sidebar-brand {
  flex: none;
  padding: 3px;
}

.desktop-sidebar.collapsed:not(.workspace-open) .sidebar-brand span,
.desktop-sidebar.collapsed:not(.workspace-open) .sidebar-nav-item span,
.desktop-sidebar.collapsed:not(.workspace-open) .sidebar-section-label {
  display: none;
}

.desktop-sidebar.collapsed:not(.workspace-open) .sidebar-nav-item {
  justify-content: center;
  padding: 0;
}

@media (max-width: 980px) {
  .desktop-sidebar:not(.workspace-open) {
    width: 68px;
    padding-inline: 9px;
  }

  .desktop-sidebar:not(.workspace-open) .sidebar-brand-row {
    flex-direction: column;
    min-height: auto;
  }

  .desktop-sidebar:not(.workspace-open) .sidebar-brand {
    flex: none;
    padding: 3px;
  }

  .desktop-sidebar:not(.workspace-open) .sidebar-brand span,
  .desktop-sidebar:not(.workspace-open) .sidebar-nav-item span,
  .desktop-sidebar:not(.workspace-open) .sidebar-section-label {
    display: none;
  }

  .desktop-sidebar:not(.workspace-open) .sidebar-nav-item {
    justify-content: center;
    padding: 0;
  }

  .desktop-sidebar:not(.workspace-open) .sidebar-collapse {
    display: none;
  }
}
</style>
