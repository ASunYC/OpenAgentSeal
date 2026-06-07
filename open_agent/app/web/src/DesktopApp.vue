<template>
  <div class="app-container" :class="settingsStore.settings.theme">
    <!-- 主聊天面板-->
    <main class="main-chat">
      <!-- 顶部标题栏-->
      <header class="chat-header">
        <div class="header-left">
          <div class="logo">
            <img class="logo-icon" :src="appIconUrl" alt="" aria-hidden="true" />
            <span class="logo-text">OpenAgentSeal</span>
          </div>
        </div>
        
        <div class="header-center">
          <div class="agent-dock-wrap header-agent-dock">
            <div ref="agentDockRef" class="agent-dock-notch" :aria-label="t('智能体会话切换', 'Agent session switcher')">
              <button
                v-for="agent in dockAgents"
                :key="agent.id"
                type="button"
                class="agent-dock-card"
                :class="{ active: agent.id === selectedAgentId, running: isAgentRunning(agent.id) }"
                :data-agent-id="agent.id"
                @click="switchAgentFromDock(agent.id)"
                :title="agent.name"
              >
                <span class="agent-dock-name">{{ agent.name }}</span>
                <span v-if="isAgentRunning(agent.id)" class="agent-dock-equalizer" aria-hidden="true">
                  <span></span>
                  <span></span>
                  <span></span>
                  <span></span>
                </span>
                <span v-else class="agent-dock-idle" aria-hidden="true"></span>
              </button>
            </div>
          </div>
          
          <!-- 模型选择器-->
          <div class="selector model-selector">
            <select v-model="selectedModelId" @change="onModelChange">
              <option v-for="model in availableModels" :key="model.id" :value="model.id">
                {{ model.display_name || model.name }}
              </option>
            </select>
          </div>
        </div>
        
        <div class="header-right">
          <button
            class="btn-settings"
            :class="{ active: isSourceWorkspaceOpen }"
            @click="toggleSourceWorkspace"
            :title="t('资料库', 'Library')"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
              <path d="M12 11v5"/>
              <path d="M9.5 13.5h5"/>
            </svg>
          </button>
          <button
            class="btn-settings"
            :class="{ active: activeWorkspacePanel === 'browser' }"
            @click="openBrowserHome"
            title="Browser"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <path d="M2 12h20"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
          </button>
          <button
            class="btn-settings"
            :class="{ active: activeWorkspacePanel === 'runtime' }"
            @click="openRuntimePanel"
            :title="t('对话与运行', 'Chats & runtime')"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M8 15.5 4 19v-4.4A6.6 6.6 0 0 1 10.6 4H13a6.6 6.6 0 0 1 6.4 5"/>
              <path d="M10 14a5 5 0 0 0 5 5h3.2L21 21.5V19a5 5 0 0 0-3-9h-3a5 5 0 0 0-5 5Z"/>
            </svg>
          </button>
          <button
            class="btn-settings"
            :class="{ active: activeWorkspacePanel === 'sandbox' }"
            @click="openSandboxPanel"
            :title="t('沙盒', 'Sandbox')"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 17 10 11 4 5"/>
              <path d="M12 19h8"/>
              <path d="M20 5H12"/>
            </svg>
          </button>
          <button class="btn-settings" @click="openSettings" :title="t('设置', 'Settings')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
            </svg>
          </button>
        </div>
      </header>
      
      <!-- 中间聊天区域 -->
      <div
        class="chat-body"
        :class="{
          'dual-panel': isWorkspaceOpen,
          'source-open': isSourceWorkspaceOpen,
          'workspace-fullscreen': isWorkspacePanelFullscreen,
        }"
        :style="workspaceLayoutStyle"
      >
        <aside v-if="isSourceWorkspaceOpen" ref="sourceWorkspaceRef" class="source-workspace-panel">
          <header class="source-workspace-header">
            <div class="workspace-panel-title source-workspace-title">
              <svg class="workspace-panel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                <path d="M12 11v5"/>
                <path d="M9.5 13.5h5"/>
              </svg>
              <div class="workspace-panel-copy">
                <h3>{{ t('资料库', 'Library') }}</h3>
                <p>{{ t('添加文件、目录作为当前任务资料来源', 'Add files and folders as task reference sources') }}</p>
              </div>
            </div>
            <div class="workspace-panel-actions">
              <button class="workspace-header-button workspace-close" @click="isSourceWorkspaceOpen = false" :title="t('关闭', 'Close')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 6 6 18"/>
                  <path d="m6 6 12 12"/>
                </svg>
              </button>
            </div>
          </header>

          <section
            class="source-drop-zone"
            :class="{ 'drag-over': isSourceDragging }"
            @dragenter.prevent="onSourceDragEnter"
            @dragover.prevent="onSourceDragOver"
            @dragleave.prevent="onSourceDragLeave"
            @drop.prevent="onSourceDrop"
            @click="chooseWorkspaceFiles"
          >
            <div class="source-drop-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 5v10"/>
                <path d="M8 9l4-4 4 4"/>
                <path d="M4 17v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1"/>
              </svg>
            </div>
            <strong>{{ t('拖拽文件或目录到这里', 'Drop files or folders here') }}</strong>
            <span>{{ t('点击选择文件，也可以选择整个目录挂载到资料库', 'Click to pick files, or mount a local folder to the library') }}</span>
            <div class="source-drop-actions" @click.stop>
              <button @click="chooseWorkspaceFiles">{{ t('选择文件', 'Files') }}</button>
              <button @click="chooseWorkspaceDirectory">{{ t('选择目录', 'Folder') }}</button>
              <button @click="openWebSourceInput">{{ t('添加 Web 地址', 'Add web URL') }}</button>
            </div>
            <form v-if="showWebSourceInput" class="source-web-form" @click.stop @submit.prevent="addWebSource">
              <input
                ref="webSourceInputRef"
                v-model="webSourceUrl"
                type="url"
                :placeholder="t('输入 Web 地址后回车', 'Enter a web URL')"
                @keydown.esc.prevent="showWebSourceInput = false"
              />
              <button type="submit">{{ t('添加', 'Add') }}</button>
            </form>
          </section>

          <section class="source-list">
            <div class="source-list-head">
              <span>{{ t('来源', 'Sources') }}</span>
              <button v-if="workspaceSources.length" @click="clearWorkspaceSources">{{ t('清空', 'Clear') }}</button>
            </div>
            <div class="source-list-scroll">
              <div v-if="!workspaceSources.length" class="source-empty">{{ t('还没有添加来源', 'No sources added yet') }}</div>
              <WorkspaceSourceTree
                v-else
                :sources="workspaceSources"
                :selected-paths="selectedWorkspacePaths"
                :expanded-paths="expandedWorkspacePaths"
                @toggle-select="toggleWorkspaceSourceSelection"
                @toggle-expanded="toggleWorkspaceSourceExpanded"
                @remove-source="removeWorkspaceSource"
                @open-location="openWorkspaceSourceLocation"
              />
            </div>
          </section>
        </aside>

        <button
          v-if="isSourceWorkspaceOpen"
          class="source-resizer"
          :class="{ active: isResizingSourceWorkspace }"
          type="button"
          :title="t('拖动调整资料库宽度，双击重置', 'Drag to resize library, double-click to reset')"
          :aria-label="t('调整资料库宽度', 'Resize library')"
          @pointerdown="startSourceWorkspaceResize"
          @dblclick="resetSourceWorkspaceWidth"
        >
          <span></span>
        </button>

        <!-- 私人对话区-->
        <div class="private-chat-panel" :class="{ 'agent-switching': isAgentSwitching }">
          <div class="chat-messages" ref="messagesContainer" @click="handleChatClick">
            <div
              v-for="(msg, index) in messages"
              :key="index"
              :class="['message', msg.role]"
            >
              <div class="message-avatar">
                <div v-if="msg.role === 'user'" class="avatar user-avatar">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                    <circle cx="12" cy="7" r="4"/>
                  </svg>
                </div>
                <img v-else class="avatar agent-avatar agent-avatar-image" :src="assistantAvatarUrl" :alt="getAgentName()" />
              </div>
              <div class="message-content">
                <div class="message-header">
                  <span class="sender">{{ msg.role === 'user' ? t('你', 'You') : getAgentName() }}</span>
                  <span class="time">{{ formatTime(msg.timestamp) }}</span>
                </div>
                <!-- 思考过程显示 - 跟随每个 assistant 消息 -->
                <ThinkingProcess
                  v-if="msg.role === 'assistant' && settingsStore.settings.useCoT && msg.thinking && (msg.thinking.steps.length > 0 || msg.thinking.isThinking)"
                  :thinking="msg.thinking"
                  :is-visible="true"
                  :user-query="msg.userQuery || ''"
                  :current-step="msg.thinking.steps.length"
                />
                <!-- 正在输入指示器 - 当消息内容为空且正在加载时显示-->
                <div v-if="msg.role === 'assistant' && !msg.content && msg.isLoading" class="typing-indicator" :aria-label="t('小海豹正在思考', 'Seal is thinking')">
                  <img class="typing-agent-icon" :src="appIconUrl" alt="" aria-hidden="true" />
                  <span class="typing-text">{{ t('正在努力思考', 'Thinking hard') }}</span>
                  <span class="typing-dots" aria-hidden="true">
                    <span></span>
                    <span></span>
                    <span></span>
                  </span>
                </div>
                <!-- 消息内容 -->
                <div v-if="msg.content" class="message-text" v-html="renderMarkdown(msg.content)"></div>
                <div v-if="msg.attachments?.length" class="message-attachments">
                  <template v-for="attachment in msg.attachments" :key="attachment.id">
                    <img
                      v-if="isImageAttachment(attachment)"
                      :src="attachmentPreview(attachment)"
                      :alt="attachment.name"
                    />
                    <div v-else class="message-file-attachment">
                      <span class="attachment-file-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                          <path d="M14 2v6h6"/>
                        </svg>
                      </span>
                      <span>{{ attachment.name }}</span>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>
          <footer v-if="isChatConstrained" class="chat-footer panel-chat-footer">
            <div
              class="input-area composer-shell"
              :class="{ 'drag-over': isComposerDragging }"
              @dragenter.prevent="onComposerDragEnter"
              @dragover.prevent="onComposerDragOver"
              @dragleave.prevent="onComposerDragLeave"
              @drop.prevent="onComposerDrop"
            >
              <textarea
                v-model="inputMessage"
                class="composer-textarea"
                :placeholder="t('输入消息...', 'Type a message...')"
                @focus="onComposerFocus"
                @blur="closeAgentMention"
                @input="onComposerInput"
                @keydown="onComposerKeydown"
                @paste="onComposerPaste"
                rows="3"
              ></textarea>
              <div v-if="mentionOpen && mentionAgents.length" class="agent-mention-menu" @mousedown.stop>
                <button
                  v-for="(agent, index) in mentionAgents"
                  :key="agent.id"
                  type="button"
                  class="agent-mention-item"
                  :class="{ active: index === mentionActiveIndex }"
                  @mousedown.prevent="selectMentionAgent(agent)"
                >
                  <img
                    v-if="isAgentAvatarImage(agent.avatar)"
                    class="agent-mention-avatar"
                    :src="agent.avatar"
                    :alt="agent.name"
                  />
                  <span v-else class="agent-mention-avatar agent-mention-avatar-fallback">
                    {{ getAgentAvatarText(agent) }}
                  </span>
                  <span class="agent-mention-main">
                    <strong>{{ agent.name }}</strong>
                    <small>{{ agent.description || t('子智能体', 'Sub-agent') }}</small>
                  </span>
                </button>
              </div>
              <div v-if="pendingAttachments.length" class="pending-attachments">
                <div v-for="attachment in pendingAttachments" :key="attachment.id" class="attachment-chip">
                  <img v-if="isImageAttachment(attachment)" :src="attachmentPreview(attachment)" :alt="attachment.name" />
                  <span v-else class="attachment-file-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                      <path d="M14 2v6h6"/>
                    </svg>
                  </span>
                  <span>{{ attachment.name }}</span>
                  <button @click="removeAttachment(attachment.id)" :title="t('移除', 'Remove')">x</button>
                </div>
              </div>
              <div class="composer-toolbar">
                <div class="composer-left">
                  <div class="composer-menu-wrap" @click.stop>
                    <button class="composer-plus" @click="toggleComposerMenu" :title="t('更多操作', 'More actions')">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                        <path d="M12 5v14"/>
                        <path d="M5 12h14"/>
                      </svg>
                    </button>
                    <div v-if="composerMenuOpen" class="composer-menu">
                      <button @click="runComposerAction('image')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                        </svg>
                        <span>{{ t('添加图片和文件', 'Attach images and files') }}</span>
                      </button>
                      <div class="composer-menu-divider"></div>
                      <button @click="runComposerAction('new')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                          <path d="M12 7v6"/>
                          <path d="M9 10h6"/>
                        </svg>
                        <span>{{ t('新开会话', 'New chat') }}</span>
                      </button>
                      <button @click="runComposerAction('fork')" :disabled="loading || isForking || !runnerSessionId">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <rect x="9" y="9" width="10" height="10" rx="2"/>
                          <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                        </svg>
                        <span>{{ t('复制为新会话', 'Copy to new chat') }}</span>
                      </button>
                      <button type="button" @click="runComposerAction('clear')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <polyline points="3,6 5,6 21,6"/>
                          <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
                        </svg>
                        <span>{{ t('清空会话', 'Clear chat') }}</span>
                      </button>
                      <div class="composer-menu-divider"></div>
                      <button
                        class="composer-toggle-row"
                        :class="{ active: settingsStore.settings.useCoT }"
                        :aria-pressed="settingsStore.settings.useCoT"
                        @click="runComposerAction('cot')"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M21 12a9 9 0 0 1-15.31 6.36"/>
                          <path d="M3 12A9 9 0 0 1 18.31 5.64"/>
                          <path d="M6 18H3v3"/>
                          <path d="M18 6h3V3"/>
                        </svg>
                        <span class="composer-toggle-label">{{ t('迭代模式', 'Iteration mode') }}</span>
                        <span class="composer-toggle-switch" aria-hidden="true">
                          <span></span>
                        </span>
                      </button>
                      <button :class="{ active: skillsEnabled }" @click="runComposerAction('skills')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                        </svg>
                        <span>{{ skillsEnabled ? t('关闭技能', 'Disable skills') : t('开启技能', 'Enable skills') }}</span>
                      </button>
                    </div>
                  </div>
                  <label
                    class="tool-access-mode"
                    :class="{ 'full-access': toolAccessMode === 'full' }"
                    :title="toolAccessModeTitle"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M12 3 5 6v5c0 4.5 2.9 8.4 7 10 4.1-1.6 7-5.5 7-10V6l-7-3z"/>
                      <path d="M9 12l2 2 4-4"/>
                    </svg>
                    <select
                      v-model="toolAccessMode"
                      @change="persistToolAccessMode"
                      :aria-label="t('访问权限', 'Access mode')"
                    >
                      <option value="default">{{ t('默认权限', 'Default') }}</option>
                      <option value="full">{{ t('完全访问', 'Full access') }}</option>
                    </select>
                  </label>
                  <span
                    class="context-compaction-status"
                    :class="{ disabled: !contextStatus.enabled }"
                    :title="contextStatusTitle"
                  >
                    <span
                      class="context-usage-ring"
                      :style="{ '--context-progress': `${contextUsageDegrees}deg` }"
                      aria-hidden="true"
                    ></span>
                    <span>{{ t('压缩', 'Compact') }}</span>
                    <span class="context-usage-label">{{ contextStatusLabel }}</span>
                  </span>
                </div>
                <button
                  class="btn-send"
                  :class="{ stopping: loading }"
                  @click="handleComposerPrimaryAction"
                  :disabled="!loading && !canSendMessage"
                  :title="loading ? t('停止', 'Stop') : t('发送', 'Send')"
                >
                  <svg v-if="loading" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                    <rect x="7" y="7" width="10" height="10" rx="2"/>
                  </svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="22" y1="2" x2="11" y2="13"/>
                    <polygon points="22,2 15,22 11,13 2,9"/>
                  </svg>
                </button>
              </div>
            </div>
          </footer>
        </div>

        <button
          v-if="isWorkspaceOpen && !isWorkspacePanelFullscreen"
          class="workspace-resizer"
          :class="{ active: isResizingWorkspace }"
          type="button"
          :title="t('拖动调整工作区宽度，双击重置', 'Drag to resize workspace, double-click to reset')"
          :aria-label="t('调整工作区宽度', 'Resize workspace')"
          @pointerdown="startWorkspaceResize"
          @dblclick="resetWorkspaceWidth"
        >
          <span></span>
        </button>

        <aside v-if="isWorkspaceOpen" class="workspace-panel" :class="{ 'workspace-fullscreen-panel': isWorkspacePanelFullscreen }">
          <header class="workspace-panel-header">
            <div class="workspace-panel-title">
              <svg v-if="activeWorkspacePanel === 'browser'" class="workspace-panel-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <path d="M2 12h20"/>
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
              </svg>
              <svg v-if="activeWorkspacePanel === 'runtime'" class="workspace-panel-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M8 15.5 4 19v-4.4A6.6 6.6 0 0 1 10.6 4H13a6.6 6.6 0 0 1 6.4 5"/>
                <path d="M10 14a5 5 0 0 0 5 5h3.2L21 21.5V19a5 5 0 0 0-3-9h-3a5 5 0 0 0-5 5Z"/>
              </svg>
              <svg v-if="activeWorkspacePanel === 'sandbox'" class="workspace-panel-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M4 17 10 11 4 5"/>
                <path d="M12 19h8"/>
                <path d="M20 5H12"/>
              </svg>
              <div class="workspace-panel-copy">
                <h3>{{ workspacePanelTitle }}</h3>
                <p>{{ workspacePanelSubtitle }}</p>
              </div>
            </div>
            <div class="workspace-panel-actions">
              <button
                v-if="activeWorkspacePanel === 'browser' || activeWorkspacePanel === 'sandbox'"
                class="workspace-header-button"
                @click="toggleWorkspaceFullscreen"
                :title="isWorkspacePanelFullscreen ? t('退出全屏', 'Exit fullscreen') : t('最大化面板', 'Maximize panel')"
              >
                <svg v-if="!isWorkspacePanelFullscreen" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M8 3H5a2 2 0 0 0-2 2v3"/>
                  <path d="M16 3h3a2 2 0 0 1 2 2v3"/>
                  <path d="M21 16v3a2 2 0 0 1-2 2h-3"/>
                  <path d="M8 21H5a2 2 0 0 1-2-2v-3"/>
                </svg>
                <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M8 3v3a2 2 0 0 1-2 2H3"/>
                  <path d="M16 3v3a2 2 0 0 0 2 2h3"/>
                  <path d="M21 16h-3a2 2 0 0 0-2 2v3"/>
                  <path d="M3 16h3a2 2 0 0 1 2 2v3"/>
                </svg>
              </button>
              <button class="workspace-header-button workspace-close" @click="closeWorkspacePanel" :title="t('关闭工作区', 'Close workspace')">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 6 6 18"/>
                  <path d="m6 6 12 12"/>
                </svg>
              </button>
            </div>
          </header>

          <section v-if="activeWorkspacePanel === 'browser'" class="browser-workspace">
            <div class="browser-tabs">
              <button
                v-for="tab in browserTabs"
                :key="tab.id"
                class="browser-tab"
                :class="{ active: tab.id === activeBrowserTabId }"
                @click="switchBrowserTab(tab.id)"
                :title="tab.url"
              >
                <span class="browser-tab-title">{{ tab.title }}</span>
                <span v-if="tab.loadState === 'loading'" class="browser-tab-state"></span>
                <span class="browser-tab-close" @click.stop="closeBrowserTab(tab.id)">x</span>
              </button>
              <button class="browser-new-tab" @click="createBrowserTab()" title="New tab">+</button>
            </div>

            <div class="browser-toolbar">
              <button class="browser-icon-btn" @click="browserBack" :disabled="!canBrowserBack" title="Back">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M19 12H5"/>
                  <path d="M12 19l-7-7 7-7"/>
                </svg>
              </button>
              <button class="browser-icon-btn" @click="browserForward" :disabled="!canBrowserForward" title="Forward">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M5 12h14"/>
                  <path d="M12 5l7 7-7 7"/>
                </svg>
              </button>
              <button class="browser-icon-btn" @click="reloadBrowserTab" :disabled="!activeBrowserTab" title="Reload">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
                  <path d="M21 3v6h-6"/>
                </svg>
              </button>
              <input
                class="browser-address"
                v-model="browserAddress"
                @keydown.enter.prevent="goBrowserAddress"
                placeholder="https://example.com"
              />
              <button class="browser-go" @click="goBrowserAddress">Go</button>
            </div>

            <div class="browser-frame-area" v-if="activeBrowserTab">
              <iframe
                class="browser-frame"
                :key="`${activeBrowserTab.id}-${activeBrowserTab.renderKey}`"
                :src="activeBrowserTab.url"
                @load="onBrowserFrameLoad"
                referrerpolicy="no-referrer"
              ></iframe>
            </div>
            <div class="browser-empty" v-else>
              <button class="browser-go" @click="createBrowserTab()">Open browser tab</button>
            </div>
          </section>

          <section v-if="activeWorkspacePanel === 'runtime'" class="runtime-workspace">
            <div class="workspace-tabs">
              <button
                class="workspace-tab"
                :class="{ active: runtimePanelTab === 'chats' }"
                @click="switchRuntimePanelTab('chats')"
              >
                {{ t('对话管理', 'Chat management') }}
              </button>
              <button
                class="workspace-tab"
                :class="{ active: runtimePanelTab === 'runtime' }"
                @click="switchRuntimePanelTab('runtime')"
              >
                {{ t('运行事件', 'Runtime events') }}
              </button>
            </div>

            <div v-if="runtimePanelTab === 'chats'" class="workspace-chats">
              <div class="runtime-toolbar">
                <div class="runtime-summary">
                  <span class="runtime-summary-value">{{ chatStore.chats.length }}</span>
                  <span>{{ t('对话', 'Chats') }}</span>
                </div>
                <div class="runtime-toolbar-actions">
                  <button type="button" class="runtime-refresh runtime-danger" :disabled="!chatStore.chats.length" @click.stop="openClearAllChatsConfirm" :title="t('清空全部对话', 'Clear all chats')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3,6 5,6 21,6"/>
                      <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
                    </svg>
                  </button>
                  <button type="button" class="runtime-refresh" @click="chatStore.loadChats()" :title="t('刷新', 'Refresh')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
                      <path d="M21 3v6h-6"/>
                    </svg>
                  </button>
                </div>
              </div>

              <div v-if="!chatStore.chats.length" class="runtime-empty">
                {{ t('暂无对话记录', 'No chat history yet') }}
              </div>
              <div v-else class="workspace-chat-list">
                <article
                  v-for="chat in chatStore.chats"
                  :key="chat.id"
                  class="workspace-chat-item"
                  :class="{ active: chat.session_id === runnerSessionId }"
                  @click="openManagedChat(chat)"
                >
                  <div class="workspace-chat-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                    </svg>
                  </div>
                  <div class="workspace-chat-info">
                    <h4>{{ chat.name || t('未命名对话', 'Untitled chat') }}</h4>
                    <p>{{ formatChatDate(chat.updated_at) }}</p>
                    <span>{{ chat.session_id }}</span>
                  </div>
                  <button
                    class="workspace-chat-delete"
                    @click.stop="deleteManagedChat(chat)"
                    :title="t('删除对话', 'Delete chat')"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3,6 5,6 21,6"/>
                      <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
                    </svg>
                  </button>
                </article>
              </div>
            </div>

            <template v-else>
              <div class="runtime-toolbar">
                <div class="runtime-summary">
                  <span class="runtime-summary-value">{{ runtimeEvents.length }}</span>
                  <span>{{ t('事件', 'Events') }}</span>
                </div>
                <button class="runtime-refresh" @click="loadRuntimeReplay" :disabled="runtimeLoading" :title="t('刷新', 'Refresh')">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
                    <path d="M21 3v6h-6"/>
                  </svg>
                </button>
              </div>

              <div class="runtime-meta" v-if="runtimeThread">
                <div>
                  <span>{{ t('线程', 'Thread') }}</span>
                  <strong>{{ runtimeThread.thread_id }}</strong>
                </div>
                <div>
                  <span>{{ t('状态', 'Status') }}</span>
                  <strong>{{ runtimeThread.status }}</strong>
                </div>
                <div>
                  <span>{{ t('序号', 'Seq') }}</span>
                  <strong>{{ runtimeThread.latest_event_seq }}</strong>
                </div>
              </div>

              <div v-if="runtimeError" class="runtime-empty">{{ runtimeError }}</div>
              <div v-else-if="runtimeLoading" class="runtime-empty">{{ t('加载中...', 'Loading...') }}</div>
              <div v-else-if="!runtimeThread" class="runtime-empty">{{ t('当前会话还没有运行事件', 'No runtime events for this session') }}</div>

              <div v-else class="runtime-content">
                <div class="runtime-turns" v-if="runtimeTurns.length">
                  <div
                    v-for="turn in runtimeTurns"
                    :key="turn.turn_id"
                    class="runtime-turn"
                  >
                    <span class="runtime-turn-status">{{ turn.status }}</span>
                    <span class="runtime-turn-input">{{ turn.user_input }}</span>
                  </div>
                </div>

                <div class="runtime-events">
                  <article
                    v-for="event in runtimeEvents"
                    :key="event.event_id"
                    class="runtime-event"
                  >
                    <div class="runtime-event-head">
                      <span class="runtime-seq">#{{ event.seq }}</span>
                      <span class="runtime-event-type">{{ event.event_type }}</span>
                      <time>{{ formatTime(event.created_at) }}</time>
                    </div>
                    <p class="runtime-event-summary">{{ formatRuntimeEventSummary(event) }}</p>
                    <pre v-if="formatRuntimeEventDetail(event)" class="runtime-event-detail">{{ formatRuntimeEventDetail(event) }}</pre>
                  </article>
                </div>
              </div>
            </template>
          </section>

          <SandboxPanel v-if="activeWorkspacePanel === 'sandbox'" />
        </aside>
      </div>
      
      <!-- 底部工具栏-->
      <footer v-if="!isChatConstrained" class="chat-footer">
        <div
          class="input-area composer-shell"
          :class="{ 'drag-over': isComposerDragging }"
          @dragenter.prevent="onComposerDragEnter"
          @dragover.prevent="onComposerDragOver"
          @dragleave.prevent="onComposerDragLeave"
          @drop.prevent="onComposerDrop"
        >
          <textarea
            v-model="inputMessage"
            class="composer-textarea"
            :placeholder="t('输入消息...', 'Type a message...')"
            @focus="onComposerFocus"
            @blur="closeAgentMention"
            @input="onComposerInput"
            @keydown="onComposerKeydown"
            @paste="onComposerPaste"
            rows="3"
          ></textarea>
          <div v-if="mentionOpen && mentionAgents.length" class="agent-mention-menu" @mousedown.stop>
            <button
              v-for="(agent, index) in mentionAgents"
              :key="agent.id"
              type="button"
              class="agent-mention-item"
              :class="{ active: index === mentionActiveIndex }"
              @mousedown.prevent="selectMentionAgent(agent)"
            >
              <img
                v-if="isAgentAvatarImage(agent.avatar)"
                class="agent-mention-avatar"
                :src="agent.avatar"
                :alt="agent.name"
              />
              <span v-else class="agent-mention-avatar agent-mention-avatar-fallback">
                {{ getAgentAvatarText(agent) }}
              </span>
              <span class="agent-mention-main">
                <strong>{{ agent.name }}</strong>
                <small>{{ agent.description || t('子智能体', 'Sub-agent') }}</small>
              </span>
            </button>
          </div>
          <div v-if="pendingAttachments.length" class="pending-attachments">
            <div v-for="attachment in pendingAttachments" :key="attachment.id" class="attachment-chip">
              <img v-if="isImageAttachment(attachment)" :src="attachmentPreview(attachment)" :alt="attachment.name" />
              <span v-else class="attachment-file-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <path d="M14 2v6h6"/>
                </svg>
              </span>
              <span>{{ attachment.name }}</span>
              <button @click="removeAttachment(attachment.id)" :title="t('移除', 'Remove')">x</button>
            </div>
          </div>
          <div class="composer-toolbar">
            <div class="composer-left">
              <div class="composer-menu-wrap" @click.stop>
                <button class="composer-plus" @click="toggleComposerMenu" :title="t('更多操作', 'More actions')">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                    <path d="M12 5v14"/>
                    <path d="M5 12h14"/>
                  </svg>
                </button>
                <div v-if="composerMenuOpen" class="composer-menu">
                  <button @click="runComposerAction('image')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
                    </svg>
                    <span>{{ t('添加图片和文件', 'Attach images and files') }}</span>
                  </button>
                  <div class="composer-menu-divider"></div>
                  <button @click="runComposerAction('new')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                      <path d="M12 7v6"/>
                      <path d="M9 10h6"/>
                    </svg>
                    <span>{{ t('新开会话', 'New chat') }}</span>
                  </button>
                  <button @click="runComposerAction('fork')" :disabled="loading || isForking || !runnerSessionId">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="9" y="9" width="10" height="10" rx="2"/>
                      <path d="M5 15V5a2 2 0 0 1 2-2h10"/>
                    </svg>
                    <span>{{ t('复制为新会话', 'Copy to new chat') }}</span>
                  </button>
                  <button type="button" @click="runComposerAction('clear')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3,6 5,6 21,6"/>
                      <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
                    </svg>
                    <span>{{ t('清空会话', 'Clear chat') }}</span>
                  </button>
                  <div class="composer-menu-divider"></div>
                  <button
                    class="composer-toggle-row"
                    :class="{ active: settingsStore.settings.useCoT }"
                    :aria-pressed="settingsStore.settings.useCoT"
                    @click="runComposerAction('cot')"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 12a9 9 0 0 1-15.31 6.36"/>
                      <path d="M3 12A9 9 0 0 1 18.31 5.64"/>
                      <path d="M6 18H3v3"/>
                      <path d="M18 6h3V3"/>
                    </svg>
                    <span class="composer-toggle-label">{{ t('迭代模式', 'Iteration mode') }}</span>
                    <span class="composer-toggle-switch" aria-hidden="true">
                      <span></span>
                    </span>
                  </button>
                  <button :class="{ active: skillsEnabled }" @click="runComposerAction('skills')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
                    </svg>
                    <span>{{ skillsEnabled ? t('关闭技能', 'Disable skills') : t('开启技能', 'Enable skills') }}</span>
                  </button>
                </div>
              </div>
              <label
                class="tool-access-mode"
                :class="{ 'full-access': toolAccessMode === 'full' }"
                :title="toolAccessModeTitle"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 3 5 6v5c0 4.5 2.9 8.4 7 10 4.1-1.6 7-5.5 7-10V6l-7-3z"/>
                  <path d="M9 12l2 2 4-4"/>
                </svg>
                <select
                  v-model="toolAccessMode"
                  @change="persistToolAccessMode"
                  :aria-label="t('访问权限', 'Access mode')"
                >
                  <option value="default">{{ t('默认权限', 'Default') }}</option>
                  <option value="full">{{ t('完全访问', 'Full access') }}</option>
                </select>
              </label>
              <span
                class="context-compaction-status"
                :class="{ disabled: !contextStatus.enabled }"
                :title="contextStatusTitle"
              >
                <span
                  class="context-usage-ring"
                  :style="{ '--context-progress': `${contextUsageDegrees}deg` }"
                  aria-hidden="true"
                ></span>
                <span>{{ t('压缩', 'Compact') }}</span>
                <span class="context-usage-label">{{ contextStatusLabel }}</span>
              </span>
            </div>
            <button
              class="btn-send"
              :class="{ stopping: loading }"
              @click="handleComposerPrimaryAction"
              :disabled="!loading && !canSendMessage"
              :title="loading ? t('停止', 'Stop') : t('发送', 'Send')"
            >
              <svg v-if="loading" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                <rect x="7" y="7" width="10" height="10" rx="2"/>
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22,2 15,22 11,13 2,9"/>
              </svg>
            </button>
          </div>
        </div>
      </footer>
      <footer class="app-footer" aria-label="Application footer">
        <button class="app-footer-user" type="button" :title="t('用户信息', 'User info')">
          <span class="app-footer-avatar">
            <img :src="appIconUrl" alt="" aria-hidden="true" />
          </span>
          <span class="app-footer-user-name">{{ footerUserName }}</span>
        </button>
        <p class="app-footer-note">{{ t('内容由 AI 生成，请核实重要信息。', 'AI-generated content. Please verify important information.') }}</p>
        <div class="app-footer-status">
          <span>{{ getAgentName() }}</span>
        </div>
      </footer>
    </main>


    <!-- 设置闈㈡澘 -->
    <aside 
      class="settings-sidebar" 
      :class="{ open: showSettings }"
      :style="{ width: settingsWidth + 'px', right: showSettings ? '0' : '-' + settingsWidth + 'px' }"
    >
      <SettingsPanel
        :current-tab="settingsTab"
        :width="settingsWidth"
        @close="closeSettings"
        @switch-tab="switchSettingsTab"
        @update:width="onSettingsWidthChange"
      />
    </aside>
    
    <!-- 设置闈㈡澘閬僵 -->
    <div class="settings-overlay" v-if="showSettings" @click="closeSettings"></div>
    <div v-if="showClearChatConfirm" class="confirm-overlay" @click.self="closeClearChatConfirm">
      <section class="confirm-dialog" role="dialog" aria-modal="true" :aria-label="t('清空会话', 'Clear chat')">
        <div class="confirm-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 9v4"/>
            <path d="M12 17h.01"/>
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/>
          </svg>
        </div>
        <div class="confirm-copy">
          <h3>{{ t('清空当前会话？', 'Clear current chat?') }}</h3>
          <p>{{ t('将清空当前会话里的消息记录，此操作不可恢复。', 'This will clear messages in the current chat and cannot be undone.') }}</p>
        </div>
        <div class="confirm-actions">
          <button type="button" class="confirm-button ghost" @click="closeClearChatConfirm">
            {{ t('取消', 'Cancel') }}
          </button>
          <button type="button" class="confirm-button danger" :disabled="isClearingChat" @click="confirmClearChat">
            {{ isClearingChat ? t('清空中...', 'Clearing...') : t('确认清空', 'Clear') }}
          </button>
        </div>
      </section>
    </div>
    <div v-if="showClearAllChatsConfirm" class="confirm-overlay" @click.self="closeClearAllChatsConfirm">
      <section class="confirm-dialog" role="dialog" aria-modal="true" :aria-label="t('清空全部对话', 'Clear all chats')">
        <div class="confirm-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 9v4"/>
            <path d="M12 17h.01"/>
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/>
          </svg>
        </div>
        <div class="confirm-copy">
          <h3>{{ t('清空全部对话？', 'Clear all chats?') }}</h3>
          <p>{{ t('将删除对话管理中的全部对话，此操作不可恢复。', 'This will delete every chat in chat management and cannot be undone.') }}</p>
        </div>
        <div class="confirm-actions">
          <button type="button" class="confirm-button ghost" @click="closeClearAllChatsConfirm">
            {{ t('取消', 'Cancel') }}
          </button>
          <button type="button" class="confirm-button danger" :disabled="isClearingAllChats" @click="confirmClearAllManagedChats">
            {{ isClearingAllChats ? t('清空中...', 'Clearing...') : t('确认清空', 'Clear all') }}
          </button>
        </div>
      </section>
    </div>
    <input
      ref="attachmentInput"
      class="hidden-input"
      type="file"
      accept="image/*,.txt,.md,.markdown,.json,.csv,.tsv,.pdf,.docx,.xlsx,.py,.js,.jsx,.ts,.tsx,.vue,.css,.html,.xml,.yaml,.yml,.toml,.ini,.log,.sql,.java,.kt,.go,.rs,.c,.cpp,.h,.hpp,.cs,.php,.rb,.sh,.ps1"
      multiple
      @change="onFilesSelected"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, reactive } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useSettingsStore } from '@/stores/settings'
import { useChatStore } from '@/stores/chat'
import { api } from '@/api'
import SettingsPanel from '@/components/SettingsPanel.vue'
import ThinkingProcess from '@/components/ThinkingProcess.vue'
import WorkspaceSourceTree from '@/components/WorkspaceSourceTree.vue'
import SandboxPanel from '@/components/SandboxPanel.vue'
import appIconUrl from '@/assets/icon.png'
import assistantAvatarUrl from '@/assets/assistant-avatar.png'
import { marked } from 'marked'
import type { AgentConfig, AgentEvent, Chat, ChatAttachment, ContextCompactionStatus, Message, RuntimeEvent, RuntimeThread, RuntimeTurn, ThinkingStep, WorkspaceSource, WorkspaceSourceNode, WorkspaceSourceState } from '@/types'
import { typewriterReveal } from '@/utils/typewriter'

const agentStore = useAgentStore()
const settingsStore = useSettingsStore()
const chatStore = useChatStore()

// 褰撳墠瑙嗗浘
type WorkspacePanel = '' | 'browser' | 'runtime' | 'sandbox'
type RuntimePanelTab = 'chats' | 'runtime'
type ToolAccessMode = 'default' | 'full'

const activeWorkspacePanel = ref<WorkspacePanel>('')
const runtimePanelTab = ref<RuntimePanelTab>('chats')
const isWorkspaceOpen = computed(() => activeWorkspacePanel.value !== '')
const fullscreenWorkspacePanel = ref<'' | 'browser' | 'sandbox'>('')
const isWorkspacePanelFullscreen = computed(() => {
  return activeWorkspacePanel.value !== '' && activeWorkspacePanel.value === fullscreenWorkspacePanel.value
})
const showClearChatConfirm = ref(false)
const isClearingChat = ref(false)
const showClearAllChatsConfirm = ref(false)
const isClearingAllChats = ref(false)
const isSourceWorkspaceOpen = ref(false)
const isChatConstrained = computed(() => isWorkspaceOpen.value || isSourceWorkspaceOpen.value)
const sourceWorkspaceRef = ref<HTMLElement | null>(null)
const sourceDragDepth = ref(0)
const isSourceDragging = computed(() => sourceDragDepth.value > 0)
const workspaceSources = ref<WorkspaceSource[]>([])
const selectedWorkspacePaths = ref<string[]>([])
const expandedWorkspacePaths = ref<string[]>([])
const workspaceSourceStateLoaded = ref(false)
const showWebSourceInput = ref(false)
const webSourceUrl = ref('')
const webSourceInputRef = ref<HTMLInputElement | null>(null)
const sourceWorkspaceWidth = ref(426)
const isResizingSourceWorkspace = ref(false)
const workspaceWidth = ref(560)
const isResizingWorkspace = ref(false)
const SOURCE_WORKSPACE_DEFAULT_WIDTH = 426
const SOURCE_WORKSPACE_MIN_WIDTH = 320
const SOURCE_WORKSPACE_MAX_WIDTH = 700
const WORKSPACE_DEFAULT_WIDTH = 560
const WORKSPACE_MIN_WIDTH = 360
const WORKSPACE_MAX_WIDTH = 820
const WORKSPACE_MIN_CHAT_WIDTH = 480
const WORKSPACE_DUAL_MIN_CHAT_WIDTH = 300
const PANEL_RESIZER_WIDTH = 8
const SOURCE_WORKSPACE_LEFT_MARGIN = 9
const WORKSPACE_RIGHT_MARGIN = 9

const workspaceLayoutStyle = computed<Record<string, string>>(() => {
  return {
    '--workspace-width': isWorkspaceOpen.value ? `${workspaceWidth.value}px` : '0px',
    '--source-workspace-width': isSourceWorkspaceOpen.value ? `${sourceWorkspaceWidth.value}px` : '0px',
  }
})

function clampSourceWorkspaceWidth(width: number): number {
  if (typeof window === 'undefined') {
    return Math.min(Math.max(width, SOURCE_WORKSPACE_MIN_WIDTH), SOURCE_WORKSPACE_MAX_WIDTH)
  }

  const minChatWidth = isWorkspaceOpen.value ? WORKSPACE_DUAL_MIN_CHAT_WIDTH : WORKSPACE_MIN_CHAT_WIDTH
  const reservedRight = isWorkspaceOpen.value
    ? workspaceWidth.value + WORKSPACE_RIGHT_MARGIN + PANEL_RESIZER_WIDTH
    : 0
  const viewportMax = Math.max(
    SOURCE_WORKSPACE_MIN_WIDTH,
    window.innerWidth - minChatWidth - reservedRight - SOURCE_WORKSPACE_LEFT_MARGIN - PANEL_RESIZER_WIDTH,
  )
  const maxWidth = Math.min(SOURCE_WORKSPACE_MAX_WIDTH, viewportMax)
  return Math.round(Math.min(Math.max(width, SOURCE_WORKSPACE_MIN_WIDTH), maxWidth))
}

function updateSourceWorkspaceWidthFromPointer(clientX: number): void {
  sourceWorkspaceWidth.value = clampSourceWorkspaceWidth(clientX - SOURCE_WORKSPACE_LEFT_MARGIN)
}

function startSourceWorkspaceResize(event: PointerEvent): void {
  if (!isSourceWorkspaceOpen.value) return

  event.preventDefault()
  const target = event.currentTarget as HTMLElement | null
  target?.setPointerCapture?.(event.pointerId)
  isResizingSourceWorkspace.value = true
  document.body.classList.add('source-workspace-resizing')
  updateSourceWorkspaceWidthFromPointer(event.clientX)
  window.addEventListener('pointermove', onSourceWorkspaceResize)
  window.addEventListener('pointerup', stopSourceWorkspaceResize, { once: true })
  window.addEventListener('pointercancel', stopSourceWorkspaceResize, { once: true })
}

function onSourceWorkspaceResize(event: PointerEvent): void {
  updateSourceWorkspaceWidthFromPointer(event.clientX)
}

function stopSourceWorkspaceResize(): void {
  if (!isResizingSourceWorkspace.value) return

  isResizingSourceWorkspace.value = false
  document.body.classList.remove('source-workspace-resizing')
  window.removeEventListener('pointermove', onSourceWorkspaceResize)
  window.removeEventListener('pointerup', stopSourceWorkspaceResize)
  window.removeEventListener('pointercancel', stopSourceWorkspaceResize)
}

function resetSourceWorkspaceWidth(): void {
  sourceWorkspaceWidth.value = clampSourceWorkspaceWidth(SOURCE_WORKSPACE_DEFAULT_WIDTH)
}

const workspacePanelTitle = computed(() => {
  if (activeWorkspacePanel.value === 'browser') return t('浏览器', 'Browser')
  if (activeWorkspacePanel.value === 'runtime') return t('对话与运行', 'Chats & runtime')
  if (activeWorkspacePanel.value === 'sandbox') return t('沙盒', 'Sandbox')
  return t('工作区', 'Workspace')
})

const workspacePanelSubtitle = computed(() => {
  if (activeWorkspacePanel.value === 'browser') return t('网页浏览与检索辅助', 'Web browsing and research')
  if (activeWorkspacePanel.value === 'runtime') return t('对话管理与运行事件', 'Chat management and runtime events')
  if (activeWorkspacePanel.value === 'sandbox') return t('使用 agent-switch 启动 CLI 终端', 'Launch CLI terminals through agent-switch')
  return t('当前工作区', 'Current workspace')
})

function clampWorkspaceWidth(width: number): number {
  if (typeof window === 'undefined') {
    return Math.min(Math.max(width, WORKSPACE_MIN_WIDTH), WORKSPACE_MAX_WIDTH)
  }

  const minChatWidth = isSourceWorkspaceOpen.value ? WORKSPACE_DUAL_MIN_CHAT_WIDTH : WORKSPACE_MIN_CHAT_WIDTH
  const reservedLeft = isSourceWorkspaceOpen.value
    ? sourceWorkspaceWidth.value + SOURCE_WORKSPACE_LEFT_MARGIN + PANEL_RESIZER_WIDTH
    : 0
  const viewportMax = Math.max(
    WORKSPACE_MIN_WIDTH,
    window.innerWidth - reservedLeft - minChatWidth - WORKSPACE_RIGHT_MARGIN - PANEL_RESIZER_WIDTH,
  )
  const maxWidth = Math.min(WORKSPACE_MAX_WIDTH, viewportMax)
  return Math.round(Math.min(Math.max(width, WORKSPACE_MIN_WIDTH), maxWidth))
}

function updateWorkspaceWidthFromPointer(clientX: number): void {
  if (typeof window === 'undefined') return
  workspaceWidth.value = clampWorkspaceWidth(window.innerWidth - clientX - WORKSPACE_RIGHT_MARGIN)
}

function startWorkspaceResize(event: PointerEvent): void {
  if (!isWorkspaceOpen.value) return

  event.preventDefault()
  const target = event.currentTarget as HTMLElement | null
  target?.setPointerCapture?.(event.pointerId)
  isResizingWorkspace.value = true
  document.body.classList.add('workspace-resizing')
  updateWorkspaceWidthFromPointer(event.clientX)
  window.addEventListener('pointermove', onWorkspaceResize)
  window.addEventListener('pointerup', stopWorkspaceResize, { once: true })
  window.addEventListener('pointercancel', stopWorkspaceResize, { once: true })
}

function onWorkspaceResize(event: PointerEvent): void {
  updateWorkspaceWidthFromPointer(event.clientX)
}

function stopWorkspaceResize(): void {
  if (!isResizingWorkspace.value) return

  isResizingWorkspace.value = false
  document.body.classList.remove('workspace-resizing')
  window.removeEventListener('pointermove', onWorkspaceResize)
  window.removeEventListener('pointerup', stopWorkspaceResize)
  window.removeEventListener('pointercancel', stopWorkspaceResize)
}

function resetWorkspaceWidth(): void {
  workspaceWidth.value = clampWorkspaceWidth(WORKSPACE_DEFAULT_WIDTH)
}

function syncPanelWidths(): void {
  if (isWorkspaceOpen.value) {
    workspaceWidth.value = clampWorkspaceWidth(workspaceWidth.value)
  }
  if (isSourceWorkspaceOpen.value) {
    sourceWorkspaceWidth.value = clampSourceWorkspaceWidth(sourceWorkspaceWidth.value)
  }
}

function handlePanelViewportResize(): void {
  syncPanelWidths()
}

type BrowserLoadState = 'idle' | 'loading' | 'loaded'

interface BrowserTab {
  id: string
  url: string
  title: string
  history: string[]
  historyIndex: number
  renderKey: number
  loadState: BrowserLoadState
}

const BROWSER_HOME = 'about:blank'
const browserTabs = ref<BrowserTab[]>([])
const activeBrowserTabId = ref('')
const browserAddress = ref('')

const activeBrowserTab = computed(() => {
  return browserTabs.value.find(tab => tab.id === activeBrowserTabId.value) || null
})

const canBrowserBack = computed(() => {
  return !!activeBrowserTab.value && activeBrowserTab.value.historyIndex > 0
})

const canBrowserForward = computed(() => {
  return !!activeBrowserTab.value && activeBrowserTab.value.historyIndex < activeBrowserTab.value.history.length - 1
})

// 设置闈㈡澘鐘舵€?
const showSettings = ref(false)
const settingsTab = ref('dashboard') // 榛樿閫変腑鏁版嵁闈㈡澘
const settingsWidth = ref(900) // 榛樿瀹藉害 900px

// 澶勭悊设置闈㈡澘瀹藉害鍙樺寲
const onSettingsWidthChange = (width: number) => {
  settingsWidth.value = width
}

// 鑱婂ぉ鐘舵€?
const selectedAgentId = ref('')
const selectedModelId = ref('')
const runnerSessionId = ref('')
const messages = ref<Message[]>([])
const contextStatus = ref<ContextCompactionStatus>({
  session_id: '',
  enabled: true,
  used_tokens: 0,
  token_limit: 60000,
  context_window: 60000,
  context_window_source: 'fallback',
  usage_percent: 0,
  compacted: false,
  compaction_count: 0,
  updated_at: null,
})
const inputMessage = ref('')
const attachmentInput = ref<HTMLInputElement | null>(null)
const pendingAttachments = ref<ChatAttachment[]>([])
const canSendMessage = computed(() => !!inputMessage.value.trim() || pendingAttachments.value.length > 0)
const composerMenuOpen = ref(false)
const mentionOpen = ref(false)
const mentionQuery = ref('')
const mentionStart = ref(0)
const mentionActiveIndex = ref(0)
const mentionTarget = ref<{ agentId: string; token: string } | null>(null)
let activeComposerTextarea: HTMLTextAreaElement | null = null
const TOOL_ACCESS_MODE_STORAGE_KEY = 'tool_access_mode'
const toolAccessMode = ref<ToolAccessMode>('default')
const toolAccessModeTitle = computed(() => {
  return toolAccessMode.value === 'full'
    ? t('完全访问权限：写入和命令类工具将自动通过审批', 'Full access: write and command tools are auto-approved')
    : t('默认权限：写入和命令类工具需要审批', 'Default access: write and command tools require approval')
})
const composerDragDepth = ref(0)
const isComposerDragging = computed(() => composerDragDepth.value > 0)
const loading = ref(false)
const isCancellingRun = ref(false)
const isForking = ref(false)
const isAgentSwitching = ref(false)
const activeRunAgentId = ref('')
const activeRunSessionId = ref('')
const skillsEnabled = ref(true)  // 技能开关状态
const messagesContainer = ref<HTMLElement | null>(null)
const agentDockRef = ref<HTMLElement | null>(null)
const runtimeThread = ref<RuntimeThread | null>(null)
const runtimeTurns = ref<RuntimeTurn[]>([])
const runtimeEvents = ref<RuntimeEvent[]>([])
const runtimeLoading = ref(false)
const runtimeError = ref('')
let unlistenDesktopFileDrops: (() => void) | null = null

// 缈昏瘧鍑芥暟
function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function normalizeToolAccessMode(value: unknown): ToolAccessMode {
  return value === 'full' ? 'full' : 'default'
}

function persistToolAccessMode() {
  toolAccessMode.value = normalizeToolAccessMode(toolAccessMode.value)
  localStorage.setItem(TOOL_ACCESS_MODE_STORAGE_KEY, toolAccessMode.value)
}

function loadToolAccessMode() {
  toolAccessMode.value = normalizeToolAccessMode(localStorage.getItem(TOOL_ACCESS_MODE_STORAGE_KEY))
}

function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

async function loadStartupAgentData() {
  for (let attempt = 1; attempt <= 45; attempt += 1) {
    await agentStore.loadAgents()
    await agentStore.loadModelConfigs()
    if (agentStore.agents.length > 0) {
      return
    }
    await sleep(1000)
  }
}

// 鍙敤妯″瀷
const availableModels = computed(() => {
  return agentStore.modelConfigs
})

const childAgents = computed(() => {
  return agentStore.agents.filter(agent => agent.id !== 'main' && agent.enabled !== false)
})

const mentionAgents = computed(() => {
  const query = mentionQuery.value.trim().toLowerCase()
  const candidates = childAgents.value
  const filtered = query
    ? candidates.filter(agent => {
        const haystack = `${agent.name} ${agent.id} ${agent.description || ''}`.toLowerCase()
        return haystack.includes(query)
      })
    : candidates
  return filtered.slice(0, 8)
})

const dockAgents = computed(() => {
  const main = agentStore.agents.find(agent => agent.id === 'main')
  const rest = agentStore.agents.filter(agent => agent.id !== 'main' && agent.enabled !== false)
  return main ? [main, ...rest] : rest
})

const footerUserName = computed(() => {
  return localStorage.getItem('openagentseal_user_name') || 'admin'
})

const contextUsageDegrees = computed(() => {
  return Math.min(100, Math.max(0, contextStatus.value.usage_percent)) * 3.6
})

const contextStatusLabel = computed(() => {
  if (!contextStatus.value.enabled) {
    return t('自动压缩已关闭', 'Auto compaction off')
  }
  return t(
    `上下文已使用 ${contextStatus.value.usage_percent}%`,
    `${contextStatus.value.usage_percent}% context used`,
  )
})

const contextStatusTitle = computed(() => {
  if (!contextStatus.value.enabled) {
    return t(
      '自动压缩上下文已关闭，可在系统设置中开启',
      'Automatic context compaction is off. Enable it in System settings.',
    )
  }
  const compacted = contextStatus.value.compaction_count > 0
    ? t(`，已压缩 ${contextStatus.value.compaction_count} 次`, `, compacted ${contextStatus.value.compaction_count} time(s)`)
    : ''
  return t(
    `当前模型 ${contextStatus.value.model_name || ''} 的上下文已使用 ${contextStatus.value.usage_percent}%（${contextStatus.value.used_tokens}/${contextStatus.value.context_window} Token），约在 ${contextStatus.value.token_limit} Token 时自动压缩${compacted}`,
    `${contextStatus.value.usage_percent}% of ${contextStatus.value.model_name || 'the current model'} context is used (${contextStatus.value.used_tokens}/${contextStatus.value.context_window} tokens); auto compaction starts near ${contextStatus.value.token_limit} tokens${compacted}`,
  )
})

// 鑾峰彇鏅鸿兘浣撳悕绉?
function getAgentName(): string {
  const agent = agentStore.agents.find(a => a.id === selectedAgentId.value)
  return agent?.name || 'Agent'
}

// 鏍煎紡鍖栨椂闂?
function formatTime(timestamp?: string): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString(settingsStore.settings.language === 'zh-CN' ? 'zh-CN' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatChatDate(timestamp?: string): string {
  if (!timestamp) return ''
  return new Date(timestamp).toLocaleString(settingsStore.settings.language === 'zh-CN' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// 娓叉煋 Markdown
function renderMarkdown(content: string): string {
  try {
    const html = marked(content) as string
    return normalizeRenderedLinks(html)
  } catch {
    return content
  }
}

function normalizeRenderedLinks(html: string): string {
  if (typeof DOMParser === 'undefined') return html

  const parser = new DOMParser()
  const doc = parser.parseFromString(`<div>${html}</div>`, 'text/html')

  doc.querySelectorAll('a[href]').forEach((anchor) => {
    const rawText = anchor.textContent || anchor.getAttribute('href') || ''
    const parts = splitUrlDecoration(rawText)
    const cleanedHref = sanitizeBrowserUrlCandidate(parts.core || rawText)
    const link = anchor.cloneNode(true) as HTMLAnchorElement

    link.setAttribute('href', cleanedHref)
    link.setAttribute('target', '_blank')
    link.setAttribute('rel', 'noopener noreferrer')
    link.textContent = cleanedHref

    if (parts.leading || parts.trailing) {
      const wrapper = doc.createElement('span')
      if (parts.leading) wrapper.appendChild(doc.createTextNode(parts.leading))
      wrapper.appendChild(link)
      if (parts.trailing) wrapper.appendChild(doc.createTextNode(parts.trailing))
      anchor.replaceWith(wrapper)
    } else {
      anchor.replaceWith(link)
    }
  })

  return doc.body.firstElementChild?.innerHTML || html
}

function splitUrlDecoration(value: string): { leading: string; core: string; trailing: string } {
  let text = value.trim()
  const leadingMatch = text.match(/^[<(\'"\\s]+/)
  const leading = leadingMatch?.[0] || ''
  if (leading) text = text.slice(leading.length)

  const trailingMatch = text.match(/[>)\'"\\s.,;:!?]+$/)
  const trailing = trailingMatch?.[0] || ''
  if (trailing) text = text.slice(0, -trailing.length)

  return {
    leading,
    core: text,
    trailing,
  }
}

async function switchAgentFromDock(agentId: string) {
  await switchAgentSession(agentId)
}

async function switchAgentSession(agentId: string) {
  if (!agentId) return
  const previousAgentId = selectedAgentId.value
  selectedAgentId.value = agentId
  localStorage.setItem('selected_agent_id', agentId)
  if (previousAgentId !== agentId) {
    isAgentSwitching.value = true
  }

  messages.value = []
  const agent = agentStore.agents.find(a => a.id === agentId)
  if (agent) {
    selectedModelId.value = agent.model_id || ''
    // 鍒涘缓鎴栨仮澶?runner 瀵硅瘽閫氶亾
    await createOrGetSession()
  }
  await loadChatHistory()
  resetRuntimeReplay()
  if (activeWorkspacePanel.value === 'runtime' && runtimePanelTab.value === 'runtime') {
    await loadRuntimeReplay()
  }
  await nextTick()
  scrollSelectedAgentIntoView()
  window.setTimeout(() => {
    if (selectedAgentId.value === agentId) {
      isAgentSwitching.value = false
    }
  }, 260)
}

function scrollSelectedAgentIntoView() {
  nextTick(() => {
    const dock = agentDockRef.value
    if (!dock || !selectedAgentId.value) return
    const selected = Array
      .from(dock.querySelectorAll<HTMLElement>('.agent-dock-card'))
      .find(item => item.dataset.agentId === selectedAgentId.value)
    selected?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
  })
}

// 鍒涘缓鎴栬幏鍙?runner 瀵硅瘽閫氶亾
async function createOrGetSession() {
  if (!selectedAgentId.value) return
  
  try {
    const savedRunnerSessionId = localStorage.getItem(`session_${selectedAgentId.value}`)
    if (savedRunnerSessionId) {
      runnerSessionId.value = savedRunnerSessionId
      console.log('Restored runner chat channel:', runnerSessionId.value)
      return
    }
    
    runnerSessionId.value = selectedAgentId.value === 'main'
      ? `session_main_${Date.now()}`
      : `session_${selectedAgentId.value}_${Date.now()}`
    localStorage.setItem(`session_${selectedAgentId.value}`, runnerSessionId.value)
    console.log('Created runner chat channel:', runnerSessionId.value)
  } catch (error) {
    console.error('Failed to create runner chat channel:', error)
  }
}

// 妯″瀷鍒囨崲
function onModelChange() {
  // 鏇存柊褰撳墠鏅鸿兘浣撶殑妯″瀷
  if (selectedAgentId.value && selectedModelId.value) {
    const agent = agentStore.agents.find(a => a.id === selectedAgentId.value)
    if (agent) {
      agent.model_id = selectedModelId.value
      agentStore.saveAgent(agent)
    }
  }
}

// 鍔犺浇鑱婂ぉ鍘嗗彶
async function loadChatHistory() {
  if (!runnerSessionId.value) return
  
  try {
    const profileId = selectedAgentId.value || 'main'
    const chat = await api.getChatByRunnerSession(runnerSessionId.value, profileId)
    const history = await api.getChatHistory(chat.id, profileId)
    messages.value = history.messages || []
    scrollToBottom()
  } catch (error) {
    console.error('Failed to load chat history:', error)
    const savedMessages = localStorage.getItem(`messages_${runnerSessionId.value}`)
    if (savedMessages) {
      messages.value = JSON.parse(savedMessages)
      try {
        await api.persistChatMessages(runnerSessionId.value, messages.value, selectedAgentId.value || 'main')
        localStorage.removeItem(`messages_${runnerSessionId.value}`)
      } catch (persistError) {
        console.warn('Failed to migrate local chat messages:', persistError)
      }
    } else {
      messages.value = []
    }
  } finally {
    await refreshContextStatus()
  }
}

async function refreshContextStatus() {
  const sessionId = runnerSessionId.value
  if (!sessionId) {
    contextStatus.value = {
      ...contextStatus.value,
      session_id: '',
      used_tokens: 0,
      usage_percent: 0,
      compacted: false,
      compaction_count: 0,
      updated_at: null,
    }
    return
  }

  try {
    const status = await api.getChatContextStatus(
      sessionId,
      selectedAgentId.value || 'main',
    )
    if (runnerSessionId.value === sessionId) {
      contextStatus.value = status
    }
  } catch (error) {
    console.debug('Failed to load context compaction status:', error)
  }
}

function saveMessages() {
  // Messages are now persisted by the backend under ~/.open-agent/data/sessions.
}

function resetRuntimeReplay() {
  runtimeThread.value = null
  runtimeTurns.value = []
  runtimeEvents.value = []
  runtimeError.value = ''
}

async function openRuntimePanel() {
  if (activeWorkspacePanel.value === 'runtime') {
    closeWorkspacePanel()
    return
  }

  fullscreenWorkspacePanel.value = ''
  activeWorkspacePanel.value = 'runtime'
  syncPanelWidths()
  runtimePanelTab.value = 'chats'
  await chatStore.loadChats()
}

function openSandboxPanel() {
  if (activeWorkspacePanel.value === 'sandbox') {
    closeWorkspacePanel()
    return
  }

  fullscreenWorkspacePanel.value = ''
  activeWorkspacePanel.value = 'sandbox'
  syncPanelWidths()
}

async function switchRuntimePanelTab(tab: RuntimePanelTab) {
  runtimePanelTab.value = tab
  if (tab === 'chats') {
    await chatStore.loadChats()
    return
  }
  await loadRuntimeReplay()
}

async function openManagedChat(chat: Chat) {
  if (loading.value) return
  if (runnerSessionId.value && messages.value.length > 0) {
    saveMessages()
  }

  runnerSessionId.value = chat.session_id
  if (selectedAgentId.value) {
    localStorage.setItem(`session_${selectedAgentId.value}`, chat.session_id)
  }
  pendingAttachments.value = []
  inputMessage.value = ''
  resetRuntimeReplay()

  await chatStore.selectChat(chat.id)
  await loadChatHistory()
  if (runtimePanelTab.value === 'runtime') {
    await loadRuntimeReplay()
  }
}

async function deleteManagedChat(chat: Chat) {
  if (!confirm(t('确定要删除此对话吗？', 'Are you sure you want to delete this chat?'))) return

  await chatStore.deleteChat(chat.id)
  localStorage.removeItem(`messages_${chat.session_id}`)

  if (runnerSessionId.value === chat.session_id) {
    messages.value = []
    pendingAttachments.value = []
    resetRuntimeReplay()
    if (selectedAgentId.value) {
      localStorage.removeItem(`session_${selectedAgentId.value}`)
      await createOrGetSession()
      await loadChatHistory()
    }
  }
}

function openClearAllChatsConfirm() {
  if (!chatStore.chats.length || isClearingAllChats.value) return
  showClearAllChatsConfirm.value = true
}

function closeClearAllChatsConfirm() {
  if (isClearingAllChats.value) return
  showClearAllChatsConfirm.value = false
}

async function confirmClearAllManagedChats() {
  if (isClearingAllChats.value) return
  isClearingAllChats.value = true
  try {
    await clearAllManagedChats()
    showClearAllChatsConfirm.value = false
  } finally {
    isClearingAllChats.value = false
  }
}

async function clearAllManagedChats() {
  const chats = [...chatStore.chats]
  if (!chats.length) return

  const deletingCurrent = chats.some(chat => chat.session_id === runnerSessionId.value)
  await chatStore.deleteChats(chats.map(chat => chat.id))
  for (const chat of chats) {
    localStorage.removeItem(`messages_${chat.session_id}`)
  }

  if (deletingCurrent) {
    messages.value = []
    pendingAttachments.value = []
    resetRuntimeReplay()
    if (selectedAgentId.value) {
      localStorage.removeItem(`session_${selectedAgentId.value}`)
      await createOrGetSession()
      await loadChatHistory()
    }
  }

  await chatStore.loadChats()
}

async function loadRuntimeReplay() {
  if (!runnerSessionId.value) {
    resetRuntimeReplay()
    return
  }

  runtimeLoading.value = true
  runtimeError.value = ''
  try {
    const thread = await api.getRuntimeThreadBySession(runnerSessionId.value)
    runtimeThread.value = thread
    const [turns, events] = await Promise.all([
      api.getRuntimeTurns(thread.thread_id),
      api.getRuntimeEvents(thread.thread_id, 0),
    ])
    runtimeTurns.value = turns
    runtimeEvents.value = events
  } catch (error) {
    resetRuntimeReplay()
    const message = error instanceof Error ? error.message : String(error)
    if (!message.includes('404')) {
      runtimeError.value = message
    }
  } finally {
    runtimeLoading.value = false
  }
}

function syncRuntimeEventFromStream(event: AgentEvent) {
  if (!event.thread_id || !event.seq) return

  if (!runtimeThread.value || runtimeThread.value.thread_id !== event.thread_id) {
    runtimeThread.value = {
      thread_id: event.thread_id,
      session_id: event.session_id || runnerSessionId.value,
      user_id: 'default',
      title: '',
      status: event.status === 'idle' ? 'active' : (event.status || 'active'),
      latest_event_seq: event.seq,
      created_at: event.created_at || new Date().toISOString(),
      updated_at: event.created_at || new Date().toISOString(),
      metadata: {},
    }
    runtimeTurns.value = []
    runtimeEvents.value = []
  } else {
    runtimeThread.value.latest_event_seq = Math.max(runtimeThread.value.latest_event_seq, event.seq)
    runtimeThread.value.updated_at = event.created_at || new Date().toISOString()
  }

  const runtimeEvent: RuntimeEvent = {
    event_id: `live_${event.thread_id}_${event.seq}`,
    thread_id: event.thread_id,
    turn_id: event.turn_id,
    session_id: event.session_id || runnerSessionId.value,
    seq: event.seq,
    event_type: event.event,
    payload: event,
    created_at: event.created_at || new Date().toISOString(),
    metadata: { source: 'stream' },
  }

  const existingIndex = runtimeEvents.value.findIndex(item => item.seq === runtimeEvent.seq)
  if (existingIndex >= 0) {
    runtimeEvents.value.splice(existingIndex, 1, runtimeEvent)
  } else {
    runtimeEvents.value.push(runtimeEvent)
    runtimeEvents.value.sort((a, b) => a.seq - b.seq)
  }
}

function formatRuntimeEventSummary(event: RuntimeEvent): string {
  const payload = event.payload as AgentEvent
  if (payload.error) return payload.error
  if (payload.tool_name) return payload.tool_name
  if (payload.content) return payload.content
  if (payload.status) return payload.status
  return event.event_type
}

function formatRuntimeEventDetail(event: RuntimeEvent): string {
  const payload = event.payload as AgentEvent
  const detail = payload.arguments ?? payload.result
  if (detail === undefined || detail === null || detail === '') return ''
  if (typeof detail === 'string') return detail
  try {
    return JSON.stringify(detail, null, 2)
  } catch {
    return String(detail)
  }
}

async function forkCurrentTask() {
  if (!runnerSessionId.value || isForking.value || !selectedAgentId.value) return

  isForking.value = true
  try {
    const forked = await api.forkChat(runnerSessionId.value, `${getAgentName()} Task`, selectedAgentId.value)
    const nextRunnerSessionId = forked.chat.session_id

    runnerSessionId.value = nextRunnerSessionId
    localStorage.setItem(`session_${selectedAgentId.value}`, nextRunnerSessionId)
    await loadChatHistory()
    resetRuntimeReplay()
    if (activeWorkspacePanel.value === 'runtime' && runtimePanelTab.value === 'chats') {
      await chatStore.loadChats()
    }

    console.log('[Task Fork] Created new task runner channel:', nextRunnerSessionId, 'copied messages:', forked.copied_message_count)
  } catch (error) {
    console.error('Failed to fork current task:', error)
  } finally {
    isForking.value = false
  }
}

async function toggleSkills() {
  skillsEnabled.value = !skillsEnabled.value
  try {
    await api.saveSettings({ enable_skills: skillsEnabled.value })
  } catch (error) {
    skillsEnabled.value = !skillsEnabled.value
    console.error('Failed to toggle skills:', error)
  }
}

async function syncSkillsSetting() {
  try {
    const settings = await api.getSettings()
    skillsEnabled.value = settings.enable_skills ?? true
  } catch (error) {
    console.warn('Failed to sync skills setting:', error)
  }
}

// 生成唯一ID
function generateId(): string {
  return `step_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

function openAttachmentPicker() {
  attachmentInput.value?.click()
}

function toggleComposerMenu() {
  composerMenuOpen.value = !composerMenuOpen.value
}

function closeComposerMenu() {
  composerMenuOpen.value = false
}

function onComposerFocus(event: FocusEvent) {
  activeComposerTextarea = event.target as HTMLTextAreaElement
}

function onComposerInput(event: Event) {
  activeComposerTextarea = event.target as HTMLTextAreaElement
  if (mentionTarget.value && !inputMessage.value.includes(mentionTarget.value.token)) {
    mentionTarget.value = null
  }
  updateAgentMention(activeComposerTextarea)
}

function onComposerKeydown(event: KeyboardEvent) {
  if (mentionOpen.value && mentionAgents.value.length > 0) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      mentionActiveIndex.value = (mentionActiveIndex.value + 1) % mentionAgents.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      mentionActiveIndex.value = (mentionActiveIndex.value - 1 + mentionAgents.value.length) % mentionAgents.value.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      selectMentionAgent(mentionAgents.value[mentionActiveIndex.value])
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      closeAgentMention()
      return
    }
  }

  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void sendMessage()
  }
}

function updateAgentMention(textarea: HTMLTextAreaElement | null) {
  if (!textarea) return
  const cursor = textarea.selectionStart ?? inputMessage.value.length
  const beforeCursor = inputMessage.value.slice(0, cursor)
  const match = beforeCursor.match(/(^|\s)@([^\s@]*)$/u)
  if (!match) {
    closeAgentMention()
    return
  }

  mentionStart.value = beforeCursor.length - match[2].length - 1
  mentionQuery.value = match[2]
  mentionOpen.value = childAgents.value.length > 0
  mentionActiveIndex.value = 0
}

function closeAgentMention() {
  mentionOpen.value = false
  mentionQuery.value = ''
  mentionActiveIndex.value = 0
}

function isAgentAvatarImage(avatar?: string): boolean {
  const value = (avatar || '').trim()
  if (!value) return false
  return /^(https?:|data:image\/|blob:|\/)/i.test(value)
    || /\.(png|jpe?g|gif|webp|svg)(\?.*)?$/i.test(value)
}

function getAgentAvatarText(agent: AgentConfig): string {
  const name = (agent.name || '').trim()
  return name ? name.slice(0, 1).toUpperCase() : 'A'
}

function focusActiveComposer() {
  nextTick(() => {
    activeComposerTextarea?.focus()
  })
}

function isAgentRunning(agentId: string): boolean {
  return loading.value && activeRunAgentId.value === agentId
}

function selectMentionAgent(agent?: AgentConfig) {
  if (!agent) return
  const textarea = activeComposerTextarea
  const cursor = textarea?.selectionStart ?? inputMessage.value.length
  const beforeMention = inputMessage.value.slice(0, mentionStart.value)
  const afterMention = inputMessage.value.slice(cursor).replace(/^\s+/, '')
  inputMessage.value = `${beforeMention}${afterMention}`.trimStart()
  mentionTarget.value = null
  closeAgentMention()
  void switchAgentSession(agent.id)

  nextTick(() => {
    const nextCursor = Math.max(0, beforeMention.length)
    textarea?.focus()
    textarea?.setSelectionRange(nextCursor, nextCursor)
  })
}

function resolveMentionRoute(rawMessage: string): { agentId: string | null; message: string } {
  const raw = rawMessage.trim()
  if (!raw) {
    return { agentId: null, message: '' }
  }

  if (mentionTarget.value && hasMentionBoundary(raw, mentionTarget.value.token)) {
    return {
      agentId: mentionTarget.value.agentId,
      message: removeMentionToken(raw, mentionTarget.value.token),
    }
  }

  const tokens = childAgents.value
    .flatMap(agent => [
      { agentId: agent.id, token: `@${agent.name}` },
      { agentId: agent.id, token: `@${agent.id}` },
    ])
    .filter(item => item.token.length > 1)
    .sort((a, b) => b.token.length - a.token.length)

  for (const item of tokens) {
    if (hasMentionBoundary(raw, item.token)) {
      return {
        agentId: item.agentId,
        message: removeMentionToken(raw, item.token),
      }
    }
  }

  return { agentId: null, message: raw }
}

function hasMentionBoundary(value: string, token: string): boolean {
  return value === token || value.startsWith(`${token} `)
}

function removeMentionToken(value: string, token: string): string {
  if (value === token) return ''
  return value.startsWith(`${token} `)
    ? value.slice(token.length).trim()
    : value.replace(token, '').trim()
}

async function switchToMentionAgent(agentId: string) {
  await switchAgentSession(agentId)
}

async function runComposerAction(action: 'image' | 'clear' | 'new' | 'fork' | 'cot' | 'skills') {
  closeComposerMenu()
  if (action === 'image') {
    openAttachmentPicker()
    return
  }
  if (action === 'clear') {
    openClearChatConfirm()
    return
  }
  if (action === 'new') {
    await startNewChat()
    return
  }
  if (action === 'fork') {
    await forkCurrentTask()
    return
  }
  if (action === 'skills') {
    await toggleSkills()
    return
  }
  settingsStore.toggleCoT()
}

async function startNewChat() {
  if (!selectedAgentId.value) return
  if (runnerSessionId.value && messages.value.length > 0) {
    saveMessages()
  }
  runnerSessionId.value = selectedAgentId.value === 'main'
    ? `session_main_${Date.now()}`
    : `session_${selectedAgentId.value}_${Date.now()}`
  localStorage.setItem(`session_${selectedAgentId.value}`, runnerSessionId.value)
  messages.value = []
  contextStatus.value = {
    ...contextStatus.value,
    session_id: runnerSessionId.value,
    used_tokens: 0,
    usage_percent: 0,
    compacted: false,
    compaction_count: 0,
    updated_at: null,
  }
  pendingAttachments.value = []
  inputMessage.value = ''
  resetRuntimeReplay()
  if (activeWorkspacePanel.value === 'runtime' && runtimePanelTab.value === 'runtime') {
    await loadRuntimeReplay()
  } else if (activeWorkspacePanel.value === 'runtime' && runtimePanelTab.value === 'chats') {
    await chatStore.loadChats()
  }
  scrollToBottom()
}

async function onFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  await addFiles(Array.from(input.files || []))
  input.value = ''
}

async function onComposerPaste(event: ClipboardEvent) {
  const imageFiles = Array.from(event.clipboardData?.files || []).filter((file) => file.type.startsWith('image/'))
  if (!imageFiles.length) return
  event.preventDefault()
  await addFiles(imageFiles)
}

function hasDraggedFiles(event: DragEvent) {
  return Array.from(event.dataTransfer?.types || []).includes('Files')
}

function onComposerDragEnter(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  composerDragDepth.value += 1
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onComposerDragOver(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onComposerDragLeave(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  composerDragDepth.value = Math.max(0, composerDragDepth.value - 1)
}

async function onComposerDrop(event: DragEvent) {
  composerDragDepth.value = 0
  const files = Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  await addFiles(files)
}

async function addDroppedFilePaths(paths: string[]) {
  if (!paths.length) return
  try {
    const result = await api.createLocalAttachments(paths)
    pendingAttachments.value.push(...(result.attachments || []))
    if (result.rejected?.length) {
      const first = result.rejected[0]
      alert(t(`部分文件未添加：${first.reason}`, `Some files were not added: ${first.reason}`))
    }
  } catch (error) {
    console.error('Failed to add dropped files:', error)
    alert(t('拖拽文件添加失败，请重试。', 'Failed to add dropped files. Please try again.'))
  }
}

function workspaceSourceState(): WorkspaceSourceState {
  return {
    sources: workspaceSources.value,
    selected_paths: selectedWorkspacePaths.value,
    expanded_paths: expandedWorkspacePaths.value,
  }
}

async function loadWorkspaceSourceState() {
  try {
    const state = await api.getWorkspaceSourcesState()
    workspaceSources.value = state.sources || []
    const availablePaths = new Set<string>()
    const collect = (source: WorkspaceSourceNode) => {
      availablePaths.add(source.path)
      for (const child of source.children || []) collect(child)
    }
    for (const source of workspaceSources.value) collect(source)
    selectedWorkspacePaths.value = normalizeWorkspaceSourceSelection(
      (state.selected_paths || []).filter(path => availablePaths.has(path)),
    )
    expandedWorkspacePaths.value = Array.from(new Set(state.expanded_paths || []))
  } catch (error) {
    console.error('Failed to load library sources:', error)
  } finally {
    workspaceSourceStateLoaded.value = true
  }
}

function saveWorkspaceSourceState() {
  if (!workspaceSourceStateLoaded.value) return
  void api.saveWorkspaceSourcesState(workspaceSourceState()).catch(error => {
    console.error('Failed to save library sources:', error)
  })
}

function toggleSourceWorkspace() {
  isSourceWorkspaceOpen.value = !isSourceWorkspaceOpen.value
  if (!isSourceWorkspaceOpen.value) {
    stopSourceWorkspaceResize()
    return
  }

  syncPanelWidths()
}

async function addWorkspaceSourcePaths(paths: string[]) {
  if (!paths.length) return
  try {
    const result = await api.createWorkspaceSources(paths)
    const existing = new Set(workspaceSources.value.map(source => source.path))
    const incoming = (result.sources || []).filter(source => !existing.has(source.path))
    workspaceSources.value.push(...incoming)
    const incomingDirectories = incoming.filter(source => source.type === 'directory').map(source => source.path)
    if (incomingDirectories.length) {
      expandedWorkspacePaths.value = Array.from(new Set([...expandedWorkspacePaths.value, ...incomingDirectories]))
    }
    if (incoming.length) {
      saveWorkspaceSourceState()
    }
    if (result.rejected?.length) {
      const first = result.rejected[0]
      alert(t(`部分来源未添加：${first.reason}`, `Some sources were not added: ${first.reason}`))
    }
  } catch (error) {
    console.error('Failed to add workspace sources:', error)
    alert(t('添加资料库来源失败，请重试。', 'Failed to add library sources. Please try again.'))
  }
}

async function chooseWorkspaceFiles() {
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({ multiple: true, directory: false, title: t('选择文件', 'Select files') })
    const paths = Array.isArray(selected) ? selected : selected ? [selected] : []
    await addWorkspaceSourcePaths(paths.map(String))
  } catch (error) {
    console.error('Tauri file dialog is not available:', error)
    alert(t('当前环境不支持系统文件选择窗口。', 'System file dialog is not available in this environment.'))
  }
}

async function chooseWorkspaceDirectory() {
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({ multiple: true, directory: true, title: t('选择目录', 'Select folders') })
    const paths = Array.isArray(selected) ? selected : selected ? [selected] : []
    await addWorkspaceSourcePaths(paths.map(String))
  } catch (error) {
    console.error('Tauri directory dialog is not available:', error)
    alert(t('当前环境不支持目录选择窗口。', 'Folder picker is not available in this environment.'))
  }
}

function collectWorkspaceSourcePaths(source: WorkspaceSourceNode): string[] {
  const childPaths = (source.children || []).flatMap(collectWorkspaceSourcePaths)
  return [source.path, ...childPaths]
}

function findWorkspaceSourceNode(path: string, sources: WorkspaceSourceNode[] = workspaceSources.value): WorkspaceSourceNode | null {
  for (const source of sources) {
    if (source.path === path) return source
    const match = findWorkspaceSourceNode(path, source.children || [])
    if (match) return match
  }
  return null
}

function normalizeWorkspaceSourceSelection(paths: Iterable<string>): string[] {
  const selected = new Set(paths)
  const available = new Set<string>()

  const visit = (source: WorkspaceSourceNode): boolean => {
    available.add(source.path)
    const children = source.children || []
    if (!children.length) {
      return selected.has(source.path)
    }

    const allChildrenSelected = children.map(visit).every(Boolean)
    if (allChildrenSelected) {
      selected.add(source.path)
      return true
    }

    selected.delete(source.path)
    return false
  }

  workspaceSources.value.forEach(visit)
  return Array.from(selected).filter(path => available.has(path))
}

function compactSelectedWorkspacePaths(): string[] {
  const selected = new Set(selectedWorkspacePaths.value)
  const compacted: string[] = []

  const visit = (source: WorkspaceSourceNode, ancestorSelected = false) => {
    const isSelected = selected.has(source.path)
    if (isSelected && !ancestorSelected) {
      compacted.push(source.path)
    }
    for (const child of source.children || []) {
      visit(child, ancestorSelected || isSelected)
    }
  }

  workspaceSources.value.forEach(source => visit(source))
  return compacted
}

function clearWorkspaceSources() {
  workspaceSources.value = []
  selectedWorkspacePaths.value = []
  expandedWorkspacePaths.value = []
  saveWorkspaceSourceState()
}

function openWebSourceInput() {
  showWebSourceInput.value = true
  void nextTick(() => webSourceInputRef.value?.focus())
}

function addWebSource() {
  const url = normalizeWebSourceUrl(webSourceUrl.value)
  if (!url) {
    alert(t('请输入有效的 Web 地址。', 'Please enter a valid web URL.'))
    return
  }

  if (workspaceSources.value.some(source => source.path === url)) {
    webSourceUrl.value = ''
    showWebSourceInput.value = false
    return
  }

  workspaceSources.value.push({
    id: `src_web_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    name: webSourceName(url),
    path: url,
    type: 'web',
    mime_type: 'text/html',
    size: null,
    modified_at: Date.now() / 1000,
    children: [],
    children_count: 0,
  })
  webSourceUrl.value = ''
  showWebSourceInput.value = false
  saveWorkspaceSourceState()
}

function normalizeWebSourceUrl(rawUrl: string): string {
  const trimmed = rawUrl.trim()
  if (!trimmed) return ''
  const candidate = /^[a-zA-Z][a-zA-Z\d+.-]*:/.test(trimmed) ? trimmed : `https://${trimmed}`
  try {
    const url = new URL(candidate)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    return url.toString()
  } catch {
    return ''
  }
}

function webSourceName(url: string): string {
  try {
    const parsed = new URL(url)
    return parsed.hostname || url
  } catch {
    return url
  }
}

function toggleWorkspaceSourceSelection(path: string) {
  const source = findWorkspaceSourceNode(path)
  const paths = source ? collectWorkspaceSourcePaths(source) : [path]
  const selected = new Set(selectedWorkspacePaths.value)
  const isFullySelected = paths.every(item => selected.has(item))

  if (isFullySelected) {
    paths.forEach(item => selected.delete(item))
  } else {
    paths.forEach(item => selected.add(item))
  }

  selectedWorkspacePaths.value = normalizeWorkspaceSourceSelection(selected)
  saveWorkspaceSourceState()
}

function toggleWorkspaceSourceExpanded(path: string) {
  const expanded = new Set(expandedWorkspacePaths.value)
  if (expanded.has(path)) {
    expanded.delete(path)
  } else {
    expanded.add(path)
  }
  expandedWorkspacePaths.value = Array.from(expanded)
  saveWorkspaceSourceState()
}

function removeWorkspaceSource(sourceIdOrPath: string) {
  const removed = workspaceSources.value.find(source => source.id === sourceIdOrPath || source.path === sourceIdOrPath)
  const removedPaths = new Set(removed ? collectWorkspaceSourcePaths(removed) : [sourceIdOrPath])
  workspaceSources.value = workspaceSources.value.filter(source => source.id !== sourceIdOrPath && source.path !== sourceIdOrPath)
  selectedWorkspacePaths.value = selectedWorkspacePaths.value.filter(path => !removedPaths.has(path))
  expandedWorkspacePaths.value = expandedWorkspacePaths.value.filter(path => !removedPaths.has(path))
  saveWorkspaceSourceState()
}

async function openWorkspaceSourceLocation(source: WorkspaceSourceNode) {
  const path = source.path || ''
  if (!path) return

  const target = source.type === 'file' ? parentDirectory(path) : path
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_path', { target })
  } catch (error) {
    console.warn('Failed to open library source location:', error)
    alert(t('当前环境无法打开该位置。', 'This environment cannot open this location.'))
  }
}

function parentDirectory(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  const index = normalized.lastIndexOf('/')
  if (index <= 0) return path
  const parent = path.slice(0, index)
  return parent || path
}

function onSourceDragEnter(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  sourceDragDepth.value += 1
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onSourceDragOver(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onSourceDragLeave(event: DragEvent) {
  if (!hasDraggedFiles(event)) return
  sourceDragDepth.value = Math.max(0, sourceDragDepth.value - 1)
}

async function onSourceDrop(event: DragEvent) {
  sourceDragDepth.value = 0
  const files = Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  const sources: WorkspaceSource[] = files.map(file => ({
    id: `src_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    name: file.name,
    path: file.name,
    type: 'file',
    mime_type: file.type || 'application/octet-stream',
    size: file.size,
    children: [],
    children_count: 0,
  }))
  const existing = new Set(workspaceSources.value.map(source => `${source.name}:${source.size || 0}`))
  const incoming = sources.filter(source => !existing.has(`${source.name}:${source.size || 0}`))
  workspaceSources.value.push(...incoming)
  if (incoming.length) {
    saveWorkspaceSourceState()
  }
}

async function addFiles(files: File[]) {
  const maxFileSize = 10 * 1024 * 1024
  const acceptedFiles = files.filter((file) => {
    if (file.size <= maxFileSize) return true
    alert(t(`文件 ${file.name} 超过 10MB，暂不支持添加。`, `File ${file.name} is larger than 10MB.`))
    return false
  })
  const attachments = await Promise.all(acceptedFiles.map(fileToAttachment))
  pendingAttachments.value.push(...attachments)
}

function fileToAttachment(file: File): Promise<ChatAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = String(reader.result || '')
      const data = dataUrl.includes(',') ? dataUrl.split(',')[1] : dataUrl
      resolve({
        id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        name: file.name,
        mime_type: file.type || 'image/png',
        data,
        size: file.size,
      })
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function removeAttachment(id: string) {
  pendingAttachments.value = pendingAttachments.value.filter((attachment) => attachment.id !== id)
}

function isImageAttachment(attachment: ChatAttachment) {
  return attachment.mime_type.startsWith('image/')
}

function attachmentPreview(attachment: ChatAttachment) {
  if (attachment.data.startsWith('data:')) return attachment.data
  return `data:${attachment.mime_type};base64,${attachment.data}`
}

function handleComposerPrimaryAction() {
  if (loading.value) {
    void stopCurrentRun()
    return
  }
  void sendMessage()
}

async function stopCurrentRun() {
  const sessionToCancel = activeRunSessionId.value || runnerSessionId.value
  if (!loading.value || !sessionToCancel || isCancellingRun.value) return
  isCancellingRun.value = true
  try {
    await api.cancelRunnerChat(sessionToCancel)
  } catch (error) {
    console.error('Failed to stop current run:', error)
  }
}

function handleGlobalKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !loading.value) return
  event.preventDefault()
  void stopCurrentRun()
}

// 鍙戦€佹秷鎭?
async function sendMessage() {
  if (!canSendMessage.value || loading.value || !selectedAgentId.value) return

  const route = resolveMentionRoute(inputMessage.value)
  const attachments = [...pendingAttachments.value]

  if (route.agentId && !route.message && attachments.length === 0) {
    await switchToMentionAgent(route.agentId)
    inputMessage.value = ''
    mentionTarget.value = null
    closeAgentMention()
    focusActiveComposer()
    return
  }

  if (route.agentId) {
    await switchToMentionAgent(route.agentId)
  }
  
  // Ensure the runner channel exists before sending.
  if (!runnerSessionId.value) {
    await createOrGetSession()
  }
  
  const userMessage = route.message
  const workspacePayload = workspaceSources.value
  const selectedWorkspacePayload = compactSelectedWorkspacePaths()
  inputMessage.value = ''
  pendingAttachments.value = []
  mentionTarget.value = null
  closeAgentMention()

  if (!userMessage && attachments.length === 0) {
    return
  }
  
  messages.value.push({
    role: 'user',
    content: userMessage || t('[图片]', '[image]'),
    attachments,
    timestamp: new Date().toISOString()
  })
  
  scrollToBottom()
  loading.value = true
  const sendSessionId = runnerSessionId.value
  const sendAgentId = selectedAgentId.value || 'main'
  activeRunSessionId.value = sendSessionId
  activeRunAgentId.value = sendAgentId
  
  // 鍒涘缓涓€涓?assistant 娑堟伅鍗犱綅绗︼紝鐢ㄤ簬瀛樺偍鎬濊€冭繃绋嬪拰鏈€缁堝洖澶?
  // 浣跨敤 reactive 纭繚娣卞眰鍝嶅簲寮?
  const assistantMessage: Message = reactive({
    role: 'assistant' as const,
    content: '',
    userQuery: userMessage,  // 用户输入的查询
    isLoading: true,
    timestamp: new Date().toISOString(),
    thinking: settingsStore.settings.useCoT ? {
      isThinking: true,
      steps: [] as ThinkingStep[]
    } : undefined
  })
  messages.value.push(assistantMessage)
  
  try {
    let assistantContent = ''
    let runCancelled = false
    
    // 浣跨敤 runner 閫氶亾 ID锛岃€屼笉鏄?agentId
    // 鐩戝惉鍚庣鍙戦€佺殑浜嬩欢锛歵hinking, tool_call, tool_result, complete, error
    await api.chat(sendSessionId, userMessage, (event) => {
      console.log('[Iteration Debug] Received event:', event)
      syncRuntimeEventFromStream(event)

      if (event.event === 'message' && event.content) {
        assistantContent = event.content
        assistantMessage.isLoading = false
        assistantMessage.content = event.content
        scrollToBottom()
      }
      
      // 浠呭湪寮€鍚凯浠ｆā寮忔椂澶勭悊步骤
      if (settingsStore.settings.useCoT && assistantMessage.thinking) {
        // 鐩戝惉 step_start 浜嬩欢
        if (event.event === 'step_start') {
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'thinking',
            content: `开始步骤${event.step}/${event.max_steps}`,
            timestamp: new Date().toISOString()
          })
        }
        
        // 鐩戝惉 thinking 浜嬩欢锛圠LM 鎬濊€冨唴瀹癸級
        if (event.event === 'thinking' && event.content) {
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'thinking',
            content: event.content,
            timestamp: new Date().toISOString()
          })
          scrollToBottom()
        }
        
        // 鐩戝惉宸ュ叿璋冪敤
        if (event.event === 'tool_call') {
          const toolName = event.tool_name || 'unknown'
          const args = event.arguments ? JSON.stringify(event.arguments, null, 2) : ''
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'tool_call',
            content: `调用工具: ${toolName}`,
            toolName: toolName,
            toolOutput: args,
            timestamp: new Date().toISOString()
          })
          scrollToBottom()
        }
        
        // 鐩戝惉宸ュ叿缁撴灉
        if (event.event === 'tool_result') {
          const resultContent = event.result || event.error || ''
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'tool_result',
            content: event.success ? '工具执行成功' : '工具执行失败',
            toolOutput: typeof resultContent === 'string' ? resultContent : JSON.stringify(resultContent, null, 2),
            timestamp: new Date().toISOString()
          })
          scrollToBottom()
        }
        
        // 鐩戝惉 step_end 浜嬩欢
        if (event.event === 'step_end') {
          const stepInfo = `步骤 ${event.step} 完成，耗时 ${event.elapsed?.toFixed(2) || 0}s`
          // 鏇存柊鏈€鍚庝竴涓楠ゆ垨娣诲姞鏂版楠?
          const lastStep = assistantMessage.thinking.steps[assistantMessage.thinking.steps.length - 1]
          if (lastStep && lastStep.type === 'thinking') {
            lastStep.content += `\n${stepInfo}`
          }
        }
      }
      
      // 鐩戝惉瀹屾垚浜嬩欢 - 杩欐槸鑾峰彇鏈€缁堝洖澶嶇殑鍏抽敭
      if (event.event === 'complete' && event.content) {
        assistantContent = event.content
        assistantMessage.isLoading = false
        // 完成时停止迭代状态
        if (settingsStore.settings.useCoT && assistantMessage.thinking) {
          assistantMessage.thinking.isThinking = false
        }
      }

      if (event.event === 'cancelled') {
        runCancelled = true
        assistantContent = t('已停止。', 'Stopped.')
        assistantMessage.isLoading = false
        if (settingsStore.settings.useCoT && assistantMessage.thinking) {
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'observation',
            content: t('用户已停止当前运行。', 'The user stopped the current run.'),
            timestamp: new Date().toISOString()
          })
          assistantMessage.thinking.isThinking = false
        }
      }
      
      // 鐩戝惉閿欒浜嬩欢
      if (event.event === 'error' && event.error) {
        console.error('Agent error:', event.error)
        assistantMessage.isLoading = false
        if (settingsStore.settings.useCoT && assistantMessage.thinking) {
          assistantMessage.thinking.steps.push({
            id: generateId(),
            type: 'observation',
            content: `错误: ${event.error}`,
            timestamp: new Date().toISOString()
          })
          assistantMessage.thinking.isThinking = false
        }
      }
    }, attachments, workspacePayload, selectedWorkspacePayload, toolAccessMode.value, sendAgentId)

    if (activeWorkspacePanel.value === 'runtime' && runtimePanelTab.value === 'runtime') {
      await loadRuntimeReplay()
    }
    
    assistantMessage.isLoading = false
    // 更新 assistant 消息内容，加入本地打字机动画
    if (runCancelled) {
      assistantMessage.content = assistantContent
    } else {
      await typewriterReveal(
        assistantMessage,
        assistantContent || t('抱歉，没有收到回复。', 'Sorry, no response received.'),
        {
          onUpdate: scrollToBottom
        }
      )
    }

    scrollToBottom()
  } catch (error) {
    console.error('Failed to send message:', error)
    assistantMessage.isLoading = false
    if (settingsStore.settings.useCoT && assistantMessage.thinking) {
      assistantMessage.thinking.isThinking = false
    }
    assistantMessage.content = t('抱歉，发生了错误。请重试。', 'Sorry, an error occurred. Please try again.')
  } finally {
    loading.value = false
    isCancellingRun.value = false
    if (activeRunSessionId.value === sendSessionId) {
      activeRunSessionId.value = ''
      activeRunAgentId.value = ''
    }
    // 淇濆瓨娑堟伅鍒?localStorage
    saveMessages()
    if (activeWorkspacePanel.value === 'runtime' && runtimePanelTab.value === 'chats') {
      await chatStore.loadChats()
    }
    await refreshContextStatus()
  }
}

// 娓呯┖鑱婂ぉ
function openClearChatConfirm() {
  if (isClearingChat.value) return
  showClearChatConfirm.value = true
}

function closeClearChatConfirm() {
  if (isClearingChat.value) return
  showClearChatConfirm.value = false
}

async function confirmClearChat() {
  if (isClearingChat.value) return
  isClearingChat.value = true
  try {
    await clearChat()
    showClearChatConfirm.value = false
  } finally {
    isClearingChat.value = false
  }
}

async function clearChat() {
  messages.value = []
  if (runnerSessionId.value) {
    localStorage.removeItem(`messages_${runnerSessionId.value}`)
    try {
      await api.clearChatMessages(runnerSessionId.value, selectedAgentId.value || 'main')
    } catch (error) {
      console.error('Failed to clear persisted chat messages:', error)
    }
  }
  await refreshContextStatus()
}

// 婊氬姩鍒板簳閮?
function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

// 鎵撳紑设置
function openSettings() {
  showSettings.value = true
}

// 鍏抽棴设置
function closeSettings() {
  showSettings.value = false
}

// 鍒囨崲设置鏍囩
function switchSettingsTab(tab: string) {
  settingsTab.value = tab
}

function normalizeBrowserUrl(rawUrl: string): string {
  const trimmed = sanitizeBrowserUrlCandidate(rawUrl)
  if (!trimmed) return BROWSER_HOME
  if (trimmed === 'about:blank') return BROWSER_HOME

  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)
    ? trimmed
    : `https://${trimmed}`

  try {
    const parsed = new URL(withScheme)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return BROWSER_HOME
    }
    return parsed.toString()
  } catch {
    return BROWSER_HOME
  }
}

function sanitizeBrowserUrlCandidate(rawUrl: string): string {
  let value = rawUrl.trim()
  value = value.replace(/^[<(\'"\\s]+/, '')
  value = value.replace(/[>)\'"\\s.,;:!?]+$/g, '')

  try {
    const parsed = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(value) ? value : `https://${value}`)
    parsed.hash = ''
    return parsed.toString()
  } catch {
    return value
  }
}

function titleFromUrl(url: string): string {
  if (!url || url === 'about:blank') {
    return 'New Tab'
  }

  try {
    return new URL(url).host || url
  } catch {
    return url
  }
}

function createBrowserTab(rawUrl: string = BROWSER_HOME) {
  const url = normalizeBrowserUrl(rawUrl)
  const tab: BrowserTab = {
    id: `browser_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    url,
    title: titleFromUrl(url),
    history: [url],
    historyIndex: 0,
    renderKey: 0,
    loadState: 'loading'
  }

  browserTabs.value.push(tab)
  activeBrowserTabId.value = tab.id
  browserAddress.value = url
  activeWorkspacePanel.value = 'browser'
  syncPanelWidths()
}

function openBrowserHome() {
  if (activeWorkspacePanel.value === 'browser') {
    closeWorkspacePanel()
    return
  }

  if (!activeBrowserTab.value) {
    createBrowserTab()
    return
  }

  browserAddress.value = activeBrowserTab.value.url
  activeWorkspacePanel.value = 'browser'
  syncPanelWidths()
}

function openBrowserTab(rawUrl: string) {
  createBrowserTab(rawUrl)
}

function navigateActiveBrowserTab(rawUrl: string, replace = false) {
  const tab = activeBrowserTab.value
  if (!tab) {
    createBrowserTab(rawUrl)
    return
  }

  const url = normalizeBrowserUrl(rawUrl)
  tab.url = url
  tab.title = titleFromUrl(url)
  tab.loadState = 'loading'
  tab.renderKey += 1

  if (replace) {
    tab.history[tab.historyIndex] = url
  } else {
    tab.history = tab.history.slice(0, tab.historyIndex + 1)
    tab.history.push(url)
    tab.historyIndex = tab.history.length - 1
  }

  browserAddress.value = url
  activeWorkspacePanel.value = 'browser'
  syncPanelWidths()
}

function goBrowserAddress() {
  navigateActiveBrowserTab(browserAddress.value)
}

function switchBrowserTab(tabId: string) {
  const tab = browserTabs.value.find(item => item.id === tabId)
  if (!tab) return

  activeBrowserTabId.value = tab.id
  browserAddress.value = tab.url
  activeWorkspacePanel.value = 'browser'
  syncPanelWidths()
}

function closeBrowserTab(tabId: string) {
  const index = browserTabs.value.findIndex(tab => tab.id === tabId)
  if (index === -1) return

  browserTabs.value.splice(index, 1)

  if (activeBrowserTabId.value === tabId) {
    const nextTab = browserTabs.value[index] || browserTabs.value[index - 1] || null
    activeBrowserTabId.value = nextTab?.id || ''
    browserAddress.value = nextTab?.url || ''
    if (!nextTab) {
      fullscreenWorkspacePanel.value = ''
      activeWorkspacePanel.value = ''
    }
  }
}

function closeWorkspacePanel() {
  stopWorkspaceResize()
  fullscreenWorkspacePanel.value = ''
  activeWorkspacePanel.value = ''
}

function toggleWorkspaceFullscreen(): void {
  if (activeWorkspacePanel.value !== 'browser' && activeWorkspacePanel.value !== 'sandbox') return

  stopSourceWorkspaceResize()
  stopWorkspaceResize()
  fullscreenWorkspacePanel.value = isWorkspacePanelFullscreen.value ? '' : activeWorkspacePanel.value
}

function browserBack() {
  const tab = activeBrowserTab.value
  if (!tab || tab.historyIndex <= 0) return

  tab.historyIndex -= 1
  tab.url = tab.history[tab.historyIndex]
  tab.title = titleFromUrl(tab.url)
  tab.loadState = 'loading'
  tab.renderKey += 1
  browserAddress.value = tab.url
}

function browserForward() {
  const tab = activeBrowserTab.value
  if (!tab || tab.historyIndex >= tab.history.length - 1) return

  tab.historyIndex += 1
  tab.url = tab.history[tab.historyIndex]
  tab.title = titleFromUrl(tab.url)
  tab.loadState = 'loading'
  tab.renderKey += 1
  browserAddress.value = tab.url
}

function reloadBrowserTab() {
  const tab = activeBrowserTab.value
  if (!tab) return

  tab.loadState = 'loading'
  tab.renderKey += 1
}

function onBrowserFrameLoad() {
  const tab = activeBrowserTab.value
  if (tab) tab.loadState = 'loaded'
}

function handleChatClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const anchor = target?.closest?.('a[href]') as HTMLAnchorElement | null
  if (!anchor) return

  const href = anchor.getAttribute('href') || ''
  if (!/^https?:\/\//i.test(href)) return

  event.preventDefault()
  openBrowserTab(href)
}

async function listenForDesktopNavigation() {
  try {
    const tauriEvent = await import('@tauri-apps/api/event')
    await tauriEvent.listen<string>('external-navigation-requested', event => {
      if (event.payload) openBrowserTab(sanitizeBrowserUrlCandidate(event.payload))
    })
  } catch (error) {
    console.debug('Tauri navigation bridge is not available in web mode:', error)
  }
}

async function listenForDesktopFileDrops() {
  try {
    const tauriWebview = await import('@tauri-apps/api/webview')
    const webview = tauriWebview.getCurrentWebview()
    unlistenDesktopFileDrops = await webview.onDragDropEvent((event: any) => {
      const overSourceWorkspace = isDesktopDropOverSourceWorkspace(event.payload?.position)
      if (event.payload?.type === 'over') {
        sourceDragDepth.value = overSourceWorkspace ? 1 : 0
        composerDragDepth.value = overSourceWorkspace ? 0 : 1
        return
      }
      if (event.payload?.type === 'drop') {
        composerDragDepth.value = 0
        sourceDragDepth.value = 0
        if (overSourceWorkspace) {
          void addWorkspaceSourcePaths(event.payload.paths || [])
        } else {
          void addDroppedFilePaths(event.payload.paths || [])
        }
        return
      }
      composerDragDepth.value = 0
      sourceDragDepth.value = 0
    })
  } catch (error) {
    console.debug('Tauri file drop bridge is not available in web mode:', error)
  }
}

function isDesktopDropOverSourceWorkspace(position: { x?: number; y?: number } | undefined) {
  if (!isSourceWorkspaceOpen.value || !position || !sourceWorkspaceRef.value) return false
  const rect = sourceWorkspaceRef.value.getBoundingClientRect()
  const x = Number(position.x)
  const y = Number(position.y)
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom
}

// 鍒濆鍖?
onMounted(async () => {
  window.addEventListener('click', closeComposerMenu)
  window.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('resize', handlePanelViewportResize)
  loadToolAccessMode()
  await listenForDesktopNavigation()
  await listenForDesktopFileDrops()

  await loadStartupAgentData()
  await chatStore.loadChats()
  await syncSkillsSetting()
  await loadWorkspaceSourceState()
  
  // 灏濊瘯鎭㈠涔嬪墠閫変腑鐨勬櫤鑳戒綋
  const savedAgentId = localStorage.getItem('selected_agent_id')
  let agentToSelect = null
  
  if (savedAgentId) {
    // 楠岃瘉淇濆瓨鐨?agent ID 鏄惁浠嶇劧鏈夋晥
    agentToSelect = agentStore.agents.find(a => a.id === savedAgentId)
  }
  
  // 濡傛灉娌℃湁淇濆瓨鐨?agent 鎴栦繚瀛樼殑 agent 涓嶅瓨鍦紝閫夋嫨绗竴涓?
  if (!agentToSelect && agentStore.agents.length > 0) {
    agentToSelect = agentStore.agents[0]
  }
  
  if (agentToSelect) {
    selectedAgentId.value = agentToSelect.id
    if (agentToSelect.model_id) {
      selectedModelId.value = agentToSelect.model_id
    }
    // 淇濆瓨閫変腑鐨?agent ID
    localStorage.setItem('selected_agent_id', agentToSelect.id)
    // 鍒涘缓鎴栨仮澶?runner 瀵硅瘽閫氶亾
    await createOrGetSession()
    await loadChatHistory()
    scrollSelectedAgentIntoView()
    
    // 涓嶅啀鑷姩鍙戦€侀棶鍊欐秷鎭紙閬垮厤涓?CLI 閲嶅锛?
    // 鐢ㄦ埛鍙互涓诲姩杈撳叆娑堟伅寮€濮嬪璇?
  }
})

onUnmounted(() => {
  window.removeEventListener('click', closeComposerMenu)
  window.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('resize', handlePanelViewportResize)
  unlistenDesktopFileDrops?.()
  unlistenDesktopFileDrops = null
  stopSourceWorkspaceResize()
  stopWorkspaceResize()
})
</script>

<style scoped>
.app-container {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  position: relative;
  isolation: isolate;
  background:
    radial-gradient(circle at 18% 12%, var(--mesh-one), transparent 34%),
    radial-gradient(circle at 82% 18%, var(--mesh-two), transparent 30%),
    radial-gradient(circle at 50% 90%, rgba(47, 110, 244, 0.08), transparent 34%),
    linear-gradient(135deg, var(--mesh-three), var(--bg-secondary));
}

.app-container::before {
  content: '';
  position: absolute;
  inset: -18%;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 22% 24%, rgba(47, 110, 244, 0.16), transparent 24%),
    radial-gradient(circle at 76% 18%, rgba(181, 213, 255, 0.32), transparent 24%),
    radial-gradient(circle at 62% 78%, rgba(255, 255, 255, 0.55), transparent 28%);
  filter: blur(26px);
  opacity: 0.72;
  animation: mesh-drift 18s ease-in-out infinite alternate;
  transform: translate3d(0, 0, 0);
}

.app-container::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image: radial-gradient(circle at center, var(--dot-color) 1px, transparent 1px);
  background-size: 18px 18px;
  mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.9), rgba(0, 0, 0, 0.78));
  opacity: 0.38;
}

.app-container.dark::before {
  background:
    radial-gradient(circle at 22% 24%, rgba(47, 110, 244, 0.12), transparent 24%),
    radial-gradient(circle at 76% 18%, rgba(70, 95, 130, 0.22), transparent 24%),
    radial-gradient(circle at 62% 78%, rgba(24, 25, 27, 0.5), transparent 28%);
  opacity: 0.62;
}

@keyframes mesh-drift {
  from {
    transform: translate3d(-1.5%, -1%, 0) scale(1);
  }
  to {
    transform: translate3d(1.5%, 1%, 0) scale(1.04);
  }
}

/* 涓昏亰澶╁尯鍩?*/
.main-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: transparent;
  position: relative;
  z-index: 1;
  min-height: 0;
}

.app-footer {
  flex: 0 0 40px;
  height: 40px;
  display: grid;
  grid-template-columns: minmax(180px, 292px) minmax(0, 1fr) minmax(120px, 292px);
  align-items: center;
  gap: 12px;
  padding: 0 10px 0 8px;
  border-top: 1px solid var(--border-color);
  background: color-mix(in srgb, var(--glass-bg-strong) 94%, var(--bg-secondary));
  box-shadow: inset 0 1px 0 var(--glass-border);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  color: var(--text-secondary);
  position: relative;
  z-index: 3;
}

.app-footer-user {
  min-width: 0;
  height: 32px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 0 8px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  box-shadow: none;
}

.app-footer-avatar {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: color-mix(in srgb, var(--primary-color) 12%, var(--glass-bg-strong));
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.1), inset 0 1px 0 var(--glass-border);
  overflow: hidden;
}

.app-footer-avatar img {
  width: 24px;
  height: 24px;
  object-fit: contain;
  display: block;
}

.app-footer-user-name {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 650;
}

.app-footer-note {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

.app-footer-status {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-width: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.app-footer-status span {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.main-browser {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: transparent;
  min-width: 0;
  position: relative;
  z-index: 1;
}

.browser-workspace {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.browser-app-header {
  flex-shrink: 0;
}

.browser-header-center {
  justify-content: center;
  flex: 1;
}

.browser-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px 0;
  background: var(--glass-bg);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  border-bottom: 1px solid var(--border-color);
  overflow-x: auto;
  flex-shrink: 0;
}

.browser-tab,
.browser-new-tab,
.browser-command,
.browser-icon-btn,
.browser-go {
  border: 1px solid var(--border-color);
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
  transition: transform 0.18s ease, background 0.2s, border-color 0.2s, opacity 0.2s;
}

.browser-tab {
  height: 34px;
  max-width: 220px;
  min-width: 120px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 8px 0 12px;
  border-radius: 10px 10px 0 0;
  border-bottom-color: transparent;
}

.browser-tab.active {
  background: var(--glass-bg-strong);
  border-color: var(--primary-color);
  border-bottom-color: transparent;
  box-shadow: 0 10px 24px rgba(47, 110, 244, 0.08);
}

.browser-tab-title {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.browser-tab-close {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.browser-tab-close:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.browser-tab-state {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 2px solid var(--primary-color);
  border-top-color: transparent;
  animation: browser-spin 0.8s linear infinite;
  flex-shrink: 0;
}

.browser-new-tab {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  font-size: 20px;
  line-height: 1;
  flex-shrink: 0;
}

.browser-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px 12px;
  background: var(--glass-bg);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.browser-icon-btn,
.browser-command {
  height: 36px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.browser-icon-btn {
  width: 36px;
  padding: 0;
}

.browser-command {
  gap: 6px;
  padding: 0 12px;
}

.browser-icon-btn svg,
.browser-command svg {
  width: 16px;
  height: 16px;
}

.browser-icon-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.browser-tab:hover,
.browser-new-tab:hover,
.browser-command:hover,
.browser-icon-btn:hover:not(:disabled),
.browser-go:hover {
  background: var(--hover-bg);
  transform: translateY(-1px);
}

.browser-address {
  flex: 1;
  min-width: 160px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  font-size: 14px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
}

.browser-address:focus {
  outline: none;
  border-color: var(--primary-color);
}

.browser-go {
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  font-weight: 600;
}

.browser-frame-area {
  flex: 1;
  min-height: 0;
  margin: 16px 18px 18px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  background: var(--glass-bg-strong);
  box-shadow: var(--soft-shadow);
}

.browser-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: white;
  display: block;
}

.browser-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

@keyframes browser-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 顶部标题栏*/
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 12px 24px;
  background: var(--glass-bg);
  backdrop-filter: blur(20px) saturate(170%);
  -webkit-backdrop-filter: blur(20px) saturate(170%);
  border-bottom: 1px solid var(--border-color);
  box-shadow: inset 0 1px 0 var(--glass-border);
  height: 64px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 14px;
}

.logo-icon {
  width: 30px;
  height: 30px;
  display: block;
  object-fit: contain;
  filter: drop-shadow(0 8px 16px rgba(47, 110, 244, 0.18));
}

.logo-text {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.header-center {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  flex: 1 1 auto;
  min-width: 0;
}

.model-selector {
  flex: 0 0 auto;
}

.model-selector select {
  min-width: 268px;
}

.selector select {
  height: 36px;
  padding: 8px 34px 8px 13px;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 560;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23737373' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  min-width: 150px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65), 0 8px 20px rgba(17, 24, 39, 0.04);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.18s ease;
}

.selector select:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(47, 110, 244, 0.12);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}

.btn-settings {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.18s ease, background 0.2s, border-color 0.2s, color 0.2s;
}

.btn-settings:hover {
  background: var(--glass-bg-strong);
  border-color: var(--border-color);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.btn-settings.active {
  background: var(--glass-bg-strong);
  border-color: var(--primary-color);
  color: var(--text-primary);
  box-shadow: 0 10px 24px rgba(47, 110, 244, 0.1);
}

.btn-settings svg {
  width: 20px;
  height: 20px;
}

/* 聊天消息区域 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 30px 32px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-width: 0;
}

.message {
  display: flex;
  gap: 12px;
  width: fit-content;
  max-width: min(78%, 860px);
  min-width: 0;
  animation: message-rise 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.message.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

@keyframes message-rise {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-avatar {
  flex-shrink: 0;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35), 0 10px 22px rgba(17, 24, 39, 0.08);
}

.user-avatar {
  background: var(--primary-color);
  color: white;
}

.user-avatar svg {
  width: 20px;
  height: 20px;
}

.agent-avatar {
  color: white;
  font-weight: 700;
  font-size: 14px;
}

.agent-avatar-image {
  display: block;
  object-fit: contain;
  background: transparent;
}

.seal-avatar {
  position: relative;
  overflow: visible;
  background: linear-gradient(145deg, #dff3ff 0%, #9cc4df 100%) !important;
}

.logo-seal {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.58), 0 8px 16px rgba(47, 110, 244, 0.18);
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

.message-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  max-width: 100%;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  letter-spacing: 0.01em;
}

.message.user .message-header {
  flex-direction: row-reverse;
}

.sender {
  font-weight: 650;
  color: var(--text-primary);
}

.time {
  color: var(--text-muted);
}

.message-text {
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  padding: 12px 15px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.6;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  box-shadow: 0 12px 28px rgba(17, 24, 39, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.68);
  backdrop-filter: blur(14px) saturate(150%);
  -webkit-backdrop-filter: blur(14px) saturate(150%);
  overflow-wrap: anywhere;
  word-break: break-word;
}

.message.user .message-text {
  background: var(--primary-color);
  color: white;
  border-color: var(--primary-color);
  box-shadow: 0 14px 30px rgba(47, 110, 244, 0.18);
}

.message-text :deep(p) {
  margin: 0 0 8px 0;
  max-width: 100%;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.message-text :deep(p:last-child) {
  margin: 0;
}

.message-text :deep(code) {
  max-width: 100%;
  background: rgba(23, 23, 23, 0.08);
  padding: 2px 6px;
  border-radius: 6px;
  font-family: monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.message-text :deep(pre) {
  max-width: 100%;
  background: rgba(23, 23, 23, 0.07);
  padding: 12px;
  border-radius: 12px;
  overflow-x: auto;
  overflow-y: hidden;
  margin: 8px 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-text :deep(pre code) {
  display: block;
  min-width: 0;
  padding: 0;
  background: transparent;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.message-text :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
}

.message-text :deep(a) {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.typing-indicator {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  width: fit-content;
  padding: 10px 14px 10px 12px;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 999px;
  box-shadow: var(--soft-shadow);
  overflow: hidden;
}

.typing-agent-icon {
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  display: block;
  object-fit: contain;
  image-rendering: auto;
  filter: drop-shadow(0 6px 12px rgba(47, 110, 244, 0.14));
}

.seal-swimmer {
  position: relative;
  width: 52px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  animation: seal-swim 2.2s ease-in-out infinite;
  flex-shrink: 0;
}

.seal-body {
  position: relative;
  width: 36px;
  height: 22px;
  border-radius: 60% 58% 52% 54%;
  background: linear-gradient(145deg, #eef7ff 0%, #c8d9e8 62%, #9fb4c7 100%);
  box-shadow: inset 0 2px 4px rgba(255, 255, 255, 0.85), 0 6px 14px rgba(82, 116, 146, 0.18);
  z-index: 2;
}

.seal-face {
  position: absolute;
  inset: 5px 7px auto auto;
  width: 17px;
  height: 12px;
}

.seal-eye {
  position: absolute;
  top: 1px;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: #263746;
  animation: seal-blink 3.8s infinite;
}

.seal-eye.left {
  left: 2px;
}

.seal-eye.right {
  right: 2px;
}

.seal-nose {
  position: absolute;
  left: 7px;
  top: 6px;
  width: 4px;
  height: 3px;
  border-radius: 50%;
  background: #38495a;
}

.seal-flipper {
  position: absolute;
  bottom: -3px;
  width: 12px;
  height: 7px;
  border-radius: 999px;
  background: #9fb4c7;
  transform-origin: center;
}

.seal-flipper.left {
  left: 3px;
  transform: rotate(-22deg);
  animation: flipper-left 1.2s ease-in-out infinite;
}

.seal-flipper.right {
  right: 3px;
  transform: rotate(22deg);
  animation: flipper-right 1.2s ease-in-out infinite;
}

.seal-ripple {
  position: absolute;
  left: 3px;
  bottom: 1px;
  width: 44px;
  height: 8px;
  border-radius: 50%;
  background: radial-gradient(ellipse at center, rgba(47, 110, 244, 0.18), transparent 68%);
  animation: ripple-pulse 1.6s ease-in-out infinite;
}

.typing-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
}

.typing-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.typing-dots span {
  width: 6px;
  height: 6px;
  background: var(--primary-color);
  border-radius: 50%;
  animation: typing-dot 1.2s infinite ease-in-out;
}

.typing-dots span:nth-child(2) {
  animation-delay: 0.16s;
}

.typing-dots span:nth-child(3) {
  animation-delay: 0.32s;
}

@keyframes seal-swim {
  0%, 100% {
    transform: translateX(-4px) translateY(1px) rotate(-2deg);
  }
  50% {
    transform: translateX(5px) translateY(-2px) rotate(2deg);
  }
}

@keyframes seal-blink {
  0%, 92%, 100% {
    transform: scaleY(1);
  }
  95% {
    transform: scaleY(0.18);
  }
}

@keyframes flipper-left {
  0%, 100% {
    transform: rotate(-20deg) translateY(0);
  }
  50% {
    transform: rotate(-38deg) translateY(1px);
  }
}

@keyframes flipper-right {
  0%, 100% {
    transform: rotate(20deg) translateY(0);
  }
  50% {
    transform: rotate(38deg) translateY(1px);
  }
}

@keyframes ripple-pulse {
  0%, 100% {
    opacity: 0.48;
    transform: scaleX(0.8);
  }
  50% {
    opacity: 0.9;
    transform: scaleX(1.08);
  }
}

@keyframes typing-dot {
  0%, 70%, 100% {
    opacity: 0.35;
    transform: translateY(0) scale(0.92);
  }
  35% {
    opacity: 1;
    transform: translateY(-4px) scale(1.08);
  }
}

/* 搴曢儴杈撳叆鍖哄煙 */
.chat-footer {
  padding: 14px 24px 12px;
  background: var(--footer-bg);
  border-top: 1px solid var(--border-color);
  backdrop-filter: blur(22px) saturate(170%);
  -webkit-backdrop-filter: blur(22px) saturate(170%);
  box-shadow: inset 0 1px 0 var(--glass-border);
}

.composer-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
  position: relative;
  max-width: 1280px;
  margin: 0 auto;
}

.composer-shell.drag-over .composer-textarea {
  border-color: rgba(47, 110, 244, 0.58);
  background: color-mix(in srgb, var(--glass-bg-strong) 88%, rgba(47, 110, 244, 0.16));
  box-shadow: 0 18px 55px rgba(47, 110, 244, 0.16), 0 0 0 3px rgba(47, 110, 244, 0.14);
}

.hidden-input {
  display: none;
}

.composer-textarea {
  width: 100%;
  height: 92px;
  min-height: 92px;
  padding: 16px 18px;
  background: var(--glass-bg-strong);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  box-sizing: border-box;
  box-shadow: 0 18px 55px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.composer-textarea:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 18px 55px rgba(15, 23, 42, 0.09), 0 0 0 3px rgba(47, 110, 244, 0.12);
}

.composer-textarea::placeholder {
  color: var(--text-muted);
}

.agent-mention-menu {
  position: absolute;
  left: 14px;
  bottom: 54px;
  z-index: 35;
  width: min(340px, calc(100% - 28px));
  max-height: 260px;
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--glass-bg-strong);
  box-shadow: 0 20px 55px rgba(15, 23, 42, 0.16), inset 0 1px 0 var(--glass-border);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
}

.agent-mention-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 48px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  transition: background 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
}

.agent-mention-item:hover,
.agent-mention-item.active {
  border-color: rgba(47, 110, 244, 0.22);
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
}

.agent-mention-item:active {
  transform: translateY(1px);
}

.agent-mention-avatar {
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  object-fit: cover;
  background: rgba(47, 110, 244, 0.1);
}

.agent-mention-avatar-fallback {
  border: 1px solid rgba(47, 110, 244, 0.16);
  color: var(--primary-color);
  font-size: 14px;
  font-weight: 700;
  box-shadow: inset 0 1px 0 var(--glass-border);
}

.agent-mention-main {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.agent-mention-main strong,
.agent-mention-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-mention-main strong {
  font-size: 13px;
  font-weight: 700;
}

.agent-mention-main small {
  color: var(--text-muted);
  font-size: 11px;
}

.mention-target-status {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  max-width: 160px;
  padding: 0 10px;
  border: 1px solid rgba(47, 110, 244, 0.22);
  border-radius: 999px;
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
  color: var(--primary-color);
  font-size: 12px;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pending-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.attachment-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 220px;
  padding: 6px 8px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--glass-bg-strong);
}

.attachment-chip img {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  object-fit: cover;
}

.attachment-file-icon {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(47, 110, 244, 0.1);
  color: var(--primary-color);
}

.attachment-file-icon svg {
  width: 17px;
  height: 17px;
}

.attachment-chip span {
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-chip button {
  border: 0;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.message-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.message-attachments img {
  max-width: min(280px, 100%);
  max-height: 220px;
  border-radius: 8px;
  object-fit: cover;
}

.message-file-attachment {
  max-width: min(320px, 100%);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--glass-bg-strong);
  color: var(--text-secondary);
  font-size: 13px;
}

.message-file-attachment span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 44px;
}

.composer-left {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 12px;
}

.composer-menu-wrap {
  position: relative;
  flex: 0 0 auto;
}

.composer-plus {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--glass-bg-strong);
  color: var(--text-secondary);
  cursor: pointer;
  box-shadow: var(--soft-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.62);
  transition: transform 0.18s ease, background 0.2s ease, color 0.2s ease;
}

.composer-plus:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.composer-plus svg,
.composer-menu svg,
.tool-access-mode svg,
.btn-send svg {
  width: 18px;
  height: 18px;
}

.tool-access-mode {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 38px;
  max-width: 150px;
  padding: 0 8px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--glass-bg-strong);
  color: var(--text-secondary);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.58);
  transition: border-color 0.18s ease, color 0.18s ease, background 0.18s ease;
}

.tool-access-mode:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.tool-access-mode.full-access {
  border-color: rgba(47, 110, 244, 0.42);
  color: var(--primary-color);
  background: rgba(47, 110, 244, 0.08);
}

.tool-access-mode select {
  min-width: 0;
  max-width: 108px;
  border: 0;
  outline: none;
  background: transparent;
  color: currentColor;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.tool-access-mode select option {
  color: #111827;
  background: #ffffff;
}

.composer-menu {
  position: absolute;
  left: 0;
  bottom: calc(100% + 10px);
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 190px;
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--glass-bg-strong);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(18px) saturate(170%);
  -webkit-backdrop-filter: blur(18px) saturate(170%);
}

.composer-menu button {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  text-align: left;
  transition: background 0.18s ease, color 0.18s ease;
}

.composer-menu button:hover,
.composer-menu button.active {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.composer-menu button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.composer-menu button:disabled:hover {
  background: transparent;
  color: var(--text-secondary);
}

.composer-menu-divider {
  height: 1px;
  margin: 4px 6px;
  background: var(--border-color);
}

.composer-menu button.composer-toggle-row {
  gap: 10px;
}

.composer-menu button.composer-toggle-row.active {
  color: var(--text-primary);
}

.composer-toggle-label {
  min-width: 0;
  flex: 1;
}

.composer-toggle-switch {
  position: relative;
  width: 30px;
  height: 18px;
  flex: 0 0 30px;
  border: 1px solid color-mix(in srgb, var(--text-secondary) 20%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--text-secondary) 25%, transparent);
  transition: border-color 0.18s ease, background 0.18s ease;
}

.composer-toggle-switch > span {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.28);
  transition: transform 0.2s ease;
}

.composer-toggle-row.active .composer-toggle-switch {
  border-color: var(--primary-color);
  background: var(--primary-color);
}

.composer-toggle-row.active .composer-toggle-switch > span {
  transform: translateX(12px);
}

.context-compaction-status {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1;
  white-space: nowrap;
}

.context-compaction-status.disabled {
  opacity: 0.65;
}

.context-usage-ring {
  --context-progress: 0deg;
  position: relative;
  width: 15px;
  height: 15px;
  flex: 0 0 15px;
  border-radius: 50%;
  background: conic-gradient(
    var(--primary-color) var(--context-progress),
    color-mix(in srgb, var(--text-secondary) 24%, transparent) 0
  );
}

.context-usage-ring::after {
  content: '';
  position: absolute;
  inset: 3px;
  border-radius: 50%;
  background: var(--glass-bg-strong);
}

.context-compaction-status.disabled .context-usage-ring {
  background: color-mix(in srgb, var(--text-secondary) 34%, transparent);
}

.context-usage-label {
  overflow: hidden;
  max-width: 150px;
  color: color-mix(in srgb, var(--text-secondary) 82%, transparent);
  text-overflow: ellipsis;
}

.btn-send {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 44px;
  height: 44px;
  padding: 0;
  background: var(--primary-color);
  border: none;
  border-radius: 16px;
  color: white;
  font-size: 14px;
  cursor: pointer;
  box-shadow: 0 14px 30px rgba(47, 110, 244, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.22);
  transition: transform 0.18s ease, opacity 0.2s;
}

.btn-send:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
}

.btn-send.stopping {
  background: #ef4444;
  box-shadow: 0 14px 30px rgba(239, 68, 68, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

.btn-send.stopping:hover:not(:disabled) {
  opacity: 0.94;
}

.btn-send:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-send svg {
  width: 18px;
  height: 18px;
}

/* 设置渚ц竟鏍?*/
.settings-sidebar {
  position: fixed;
  top: 0;
  right: -900px;
  width: 900px;
  height: 100vh;
  background: var(--glass-bg-strong);
  backdrop-filter: blur(24px) saturate(175%);
  -webkit-backdrop-filter: blur(24px) saturate(175%);
  border-left: 1px solid var(--border-color);
  box-shadow: -24px 0 60px rgba(17, 24, 39, 0.16), inset 1px 0 0 rgba(255, 255, 255, 0.45);
  z-index: 1000;
  transition: right 0.32s cubic-bezier(0.22, 1, 0.36, 1);
  overflow: hidden;
}

.settings-sidebar.open {
  right: 0;
}

/* 设置閬僵 */
.settings-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(23, 23, 23, 0.22);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  z-index: 999;
}

.confirm-overlay {
  position: fixed;
  inset: 0;
  z-index: 2200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.22);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.confirm-dialog {
  width: min(420px, calc(100vw - 48px));
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 14px;
  padding: 18px;
  border: 1px solid var(--border-color);
  border-radius: 18px;
  background: var(--glass-bg-strong);
  box-shadow: 0 24px 70px rgba(15, 23, 42, 0.22);
}

.confirm-icon {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.confirm-icon svg {
  width: 21px;
  height: 21px;
}

.confirm-copy {
  min-width: 0;
}

.confirm-copy h3 {
  margin: 0 0 6px;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 760;
}

.confirm-copy p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.confirm-actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 6px;
}

.confirm-button {
  height: 36px;
  padding: 0 14px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.12s ease, background 0.16s ease, border-color 0.16s ease;
}

.confirm-button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--glass-bg-strong) 82%, rgba(47, 110, 244, 0.12));
  border-color: rgba(47, 110, 244, 0.32);
}

.confirm-button:active:not(:disabled) {
  transform: scale(0.96);
}

.confirm-button.danger {
  border-color: rgba(239, 68, 68, 0.35);
  background: #ef4444;
  color: #fff;
}

.confirm-button.danger:hover:not(:disabled) {
  border-color: rgba(239, 68, 68, 0.5);
  background: #dc2626;
}

.confirm-button:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

/* 鍙岄潰鏉垮竷灞€ */
.chat-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.chat-body.dual-panel {
  flex-direction: row;
  align-items: stretch;
  gap: 0;
  min-height: 0;
}

.chat-body.source-open {
  flex-direction: row;
  align-items: stretch;
}

.source-workspace-panel {
  flex: 0 0 var(--source-workspace-width, 320px);
  min-width: 320px;
  max-width: 700px;
  height: calc(100% - 16px);
  max-height: calc(100% - 16px);
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-self: stretch;
  margin: 8px 0 8px 9px;
  border: 1px solid var(--border-color);
  border-radius: 22px;
  background: var(--glass-bg-strong);
  box-shadow: var(--glass-shadow);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  overflow: hidden;
}

.source-resizer {
  flex: 0 0 8px;
  width: 8px;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 10;
}

.source-resizer span {
  width: 4px;
  height: 60px;
  border-radius: 999px;
  background: rgba(115, 115, 115, 0.32);
  transition: all 0.2s;
}

.source-resizer:hover span {
  height: 100px;
  background: var(--primary-color, #3b82f6);
}

.source-resizer.active span {
  width: 4px;
  height: 100%;
  background: var(--primary-color, #3b82f6);
}

.source-resizer:hover,
.source-resizer.active {
  background: transparent;
}

.source-workspace-header {
  min-height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
  background: transparent;
  flex-shrink: 0;
}

.source-drop-zone {
  flex: 0 0 auto;
  margin: 14px;
  min-height: 174px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 9px;
  padding: 18px;
  border: 1px dashed rgba(47, 110, 244, 0.36);
  border-radius: 16px;
  background: color-mix(in srgb, var(--glass-bg-strong) 86%, rgba(47, 110, 244, 0.08));
  color: var(--text-secondary);
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.source-drop-zone:hover,
.source-drop-zone.drag-over {
  border-color: rgba(47, 110, 244, 0.68);
  background: color-mix(in srgb, var(--glass-bg-strong) 78%, rgba(47, 110, 244, 0.18));
  box-shadow: 0 14px 34px rgba(47, 110, 244, 0.12);
}

.source-drop-icon {
  width: 44px;
  height: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: rgba(47, 110, 244, 0.12);
  color: var(--primary-color);
}

.source-drop-icon svg {
  width: 22px;
  height: 22px;
}

.source-drop-zone strong {
  color: var(--text-primary);
  font-size: 14px;
}

.source-drop-zone span {
  max-width: 230px;
  font-size: 12px;
  line-height: 1.45;
}

.source-drop-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 4px;
}

.source-drop-actions button,
.source-list-head button {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
}

.source-web-form {
  width: 100%;
  max-width: 310px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  margin-top: 6px;
}

.source-web-form input {
  min-width: 0;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  font-size: 12px;
}

.source-web-form input:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(47, 110, 244, 0.12);
}

.source-web-form button {
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--primary-color);
  border-radius: 9px;
  background: var(--primary-color);
  color: white;
  font-size: 12px;
  cursor: pointer;
}

.source-list {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0 14px 14px;
  overflow: hidden;
}

.source-list-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.source-list-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  overflow-anchor: none;
  padding-right: 2px;
  scrollbar-gutter: stable;
}

.source-empty {
  padding: 18px;
  border: 1px dashed var(--border-color);
  border-radius: 12px;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: center;
}

.source-item {
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--glass-bg-strong);
  overflow: hidden;
}

.source-item-main {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) 26px;
  align-items: center;
  gap: 9px;
  padding: 10px;
}

.source-type-icon {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(47, 110, 244, 0.1);
  color: var(--primary-color);
}

.source-type-icon svg {
  width: 17px;
  height: 17px;
}

.source-item h4 {
  margin: 0 0 3px;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-item p {
  margin: 0;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-remove {
  border: 0;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
}

.source-children {
  padding: 0 10px 10px 53px;
  color: var(--text-secondary);
  font-size: 12px;
}

.source-children ul {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.source-children li {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.private-chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  position: relative;
}

.chat-body.dual-panel .private-chat-panel {
  flex: 1 1 54%;
  min-width: 420px;
}

.chat-body.source-open.dual-panel .private-chat-panel {
  flex-basis: 0;
  min-width: 300px;
}

.agent-dock-wrap {
  position: relative;
  z-index: 20;
  flex: 1 1 720px;
  width: min(760px, 100%);
  min-width: 260px;
  pointer-events: none;
}

.header-agent-dock {
  max-width: min(760px, 58vw);
}

.agent-dock-notch {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: 100%;
  min-height: 46px;
  margin: 0 auto;
  padding: 6px 8px;
  overflow-x: auto;
  border: 1px solid rgba(47, 110, 244, 0.16);
  border-radius: 18px;
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--glass-bg-strong) 92%, rgba(47, 110, 244, 0.14)), var(--glass-bg)),
    radial-gradient(circle at 50% 0%, rgba(47, 110, 244, 0.2), transparent 64%);
  box-shadow: 0 20px 55px rgba(15, 23, 42, 0.13), inset 0 1px 0 rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(22px) saturate(170%);
  -webkit-backdrop-filter: blur(22px) saturate(170%);
  pointer-events: auto;
  scrollbar-width: none;
}

.agent-dock-notch::-webkit-scrollbar {
  display: none;
}

.agent-dock-card {
  position: relative;
  flex: 0 0 auto;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 4px;
  width: 112px;
  min-height: 38px;
  padding: 6px 10px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background:
    linear-gradient(145deg, color-mix(in srgb, var(--glass-bg-strong) 94%, rgba(255, 255, 255, 0.18)), color-mix(in srgb, var(--glass-bg) 86%, rgba(47, 110, 244, 0.08)));
  color: var(--text-secondary);
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.62), 0 8px 20px rgba(15, 23, 42, 0.06);
  transition: transform 0.18s ease, border-color 0.2s ease, box-shadow 0.2s ease, color 0.2s ease;
}

.agent-dock-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(110deg, transparent 0%, rgba(255, 255, 255, 0.26) 42%, transparent 68%);
  opacity: 0;
  transform: translateX(-80%);
  transition: opacity 0.2s ease, transform 0.45s ease;
}

.agent-dock-card:hover {
  border-color: rgba(47, 110, 244, 0.32);
  color: var(--text-primary);
  transform: translateY(-2px);
}

.agent-dock-card:hover::before {
  opacity: 1;
  transform: translateX(80%);
}

.agent-dock-card.active {
  border-color: rgba(47, 110, 244, 0.64);
  color: var(--primary-color);
  background:
    linear-gradient(145deg, color-mix(in srgb, var(--primary-color) 14%, var(--glass-bg-strong)), color-mix(in srgb, var(--primary-color) 8%, var(--glass-bg)));
  box-shadow: 0 14px 34px rgba(47, 110, 244, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.agent-dock-card.running {
  border-color: rgba(47, 110, 244, 0.74);
}

.agent-dock-name {
  position: relative;
  z-index: 1;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 760;
  letter-spacing: 0;
}

.agent-dock-idle {
  position: relative;
  z-index: 1;
  width: 18px;
  height: 3px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--text-muted) 42%, transparent);
}

.agent-dock-equalizer {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: flex-end;
  justify-content: center;
  gap: 3px;
  height: 12px;
}

.agent-dock-equalizer span {
  width: 3px;
  height: 5px;
  border-radius: 999px;
  background: var(--primary-color);
  box-shadow: 0 0 10px rgba(47, 110, 244, 0.42);
  animation: agent-eq 0.86s ease-in-out infinite;
}

.agent-dock-equalizer span:nth-child(2) {
  animation-delay: 0.12s;
}

.agent-dock-equalizer span:nth-child(3) {
  animation-delay: 0.24s;
}

.agent-dock-equalizer span:nth-child(4) {
  animation-delay: 0.36s;
}

@keyframes agent-eq {
  0%, 100% {
    height: 4px;
    opacity: 0.55;
  }
  45% {
    height: 12px;
    opacity: 1;
  }
}

.private-chat-panel.agent-switching .chat-messages {
  animation: agent-session-switch 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes agent-session-switch {
  0% {
    opacity: 0.2;
    transform: translateY(12px) scale(0.992);
    filter: blur(4px);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: blur(0);
  }
}

.chat-body.dual-panel .chat-messages {
  padding-right: 24px;
}

.chat-body.dual-panel .message {
  max-width: min(92%, 760px);
}

.panel-chat-footer {
  flex-shrink: 0;
}

.workspace-panel {
  flex: 0 0 var(--workspace-width, clamp(420px, 42vw, 700px));
  display: flex;
  flex-direction: column;
  min-width: 360px;
  min-height: 0;
  align-self: stretch;
  position: relative;
  overflow: hidden;
  margin: 8px 9px 8px 0;
  border: 1px solid var(--border-color);
  border-radius: 22px;
  background: var(--glass-bg-strong);
  box-shadow: var(--glass-shadow);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
}

.chat-body.workspace-fullscreen {
  position: relative;
  flex-direction: column;
  align-items: stretch;
}

.chat-body.workspace-fullscreen .source-workspace-panel,
.chat-body.workspace-fullscreen .source-resizer,
.chat-body.workspace-fullscreen .private-chat-panel,
.chat-body.workspace-fullscreen .workspace-resizer {
  display: none;
}

.chat-body.workspace-fullscreen .workspace-panel.workspace-fullscreen-panel {
  flex: 1 1 auto;
  width: auto;
  min-width: 0;
  max-width: none;
  margin: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  align-self: stretch;
  background: var(--glass-bg-strong);
}

.chat-body.workspace-fullscreen .workspace-panel-header {
  padding: 12px 16px;
}

.chat-body.workspace-fullscreen .browser-frame-area {
  margin: 10px;
  border-radius: 14px;
}

.workspace-resizer {
  flex: 0 0 8px;
  width: 8px;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  touch-action: none;
  z-index: 10;
}

.workspace-resizer span {
  width: 4px;
  height: 60px;
  border-radius: 999px;
  background: rgba(115, 115, 115, 0.32);
  transition: all 0.2s;
}

.workspace-resizer:hover span {
  height: 100px;
  background: var(--primary-color, #3b82f6);
}

.workspace-resizer.active span {
  width: 4px;
  height: 100%;
  background: var(--primary-color, #3b82f6);
}

.workspace-resizer:hover,
.workspace-resizer.active {
  background: transparent;
}

.workspace-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 68px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
  background: transparent;
  box-shadow: none;
  flex-shrink: 0;
}

.workspace-panel-title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  color: var(--text-primary);
}

.workspace-panel-icon {
  display: block;
  width: 18px !important;
  height: 18px !important;
  flex: 0 0 18px;
  max-width: 18px !important;
  max-height: 18px !important;
  min-width: 18px;
  min-height: 18px;
  color: var(--text-primary);
}

.workspace-panel-copy {
  min-width: 0;
}

.workspace-panel-copy h3 {
  margin: 0 0 4px;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 750;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-panel-copy p {
  margin: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-header-button svg,
.workspace-close svg {
  display: block;
  width: 18px !important;
  height: 18px !important;
  flex: 0 0 18px;
  max-width: 18px !important;
  max-height: 18px !important;
  min-width: 18px;
  min-height: 18px;
}

.workspace-panel-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.workspace-header-button,
.workspace-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: transform 0.18s ease, background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.workspace-header-button:hover,
.workspace-close:hover {
  background: var(--glass-bg-strong);
  border-color: var(--border-color);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.workspace-panel .browser-workspace {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.22);
}

.workspace-panel .browser-tabs {
  height: 46px;
  min-height: 46px;
  padding: 9px 12px 0;
  background: rgba(255, 255, 255, 0.18);
  border-bottom: 1px solid var(--border-color);
  overflow-x: auto;
  overflow-y: hidden;
}

.workspace-panel .browser-toolbar {
  min-height: 52px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.18);
  border-bottom: 1px solid var(--border-color);
  overflow: hidden;
}

.workspace-panel .browser-tab {
  height: 32px;
  min-width: 96px;
  max-width: 170px;
  border-radius: 10px 10px 0 0;
  font-size: 12px;
}

.workspace-panel .browser-new-tab {
  width: 30px;
  height: 30px;
  font-size: 18px;
}

.workspace-panel .browser-icon-btn,
.workspace-panel .browser-go {
  height: 34px;
  border-radius: 10px;
}

.workspace-panel .browser-icon-btn {
  width: 34px;
}

.workspace-panel .browser-icon-btn svg {
  width: 15px;
  height: 15px;
}

.workspace-panel .browser-address {
  height: 34px;
  min-width: 0;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.72);
}

.workspace-panel .browser-frame-area {
  flex: 1;
  min-height: 0;
  margin: 12px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow: 0 18px 36px rgba(17, 24, 39, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.workspace-panel .browser-empty {
  flex: 1;
  min-height: 0;
}

.runtime-workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.22);
  overflow: hidden;
}

.workspace-tabs {
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  padding: 10px 12px;
  background: var(--glass-bg);
  border-bottom: 1px solid var(--border-color);
}

.workspace-tab {
  height: 34px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  transition: all 0.2s ease;
}

.workspace-tab:hover {
  background: var(--hover-bg);
  color: var(--text-primary);
}

.workspace-tab.active {
  border-color: rgba(47, 110, 244, 0.24);
  background: var(--glass-bg-strong);
  color: var(--primary-color);
  box-shadow: 0 8px 18px rgba(17, 24, 39, 0.06);
}

.workspace-chats {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.workspace-chat-list {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  overflow-y: auto;
}

.workspace-chat-item {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) 34px;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: var(--glass-bg-strong);
  box-shadow: 0 10px 24px rgba(17, 24, 39, 0.05);
  cursor: pointer;
  transition: all 0.2s ease;
}

.workspace-chat-item:hover,
.workspace-chat-item.active {
  border-color: rgba(47, 110, 244, 0.28);
  background: var(--glass-bg-strong);
  transform: translateY(-1px);
}

.workspace-chat-item.active {
  box-shadow: inset 3px 0 0 var(--primary-color), 0 10px 24px rgba(47, 110, 244, 0.08);
}

.workspace-chat-icon {
  width: 38px;
  height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 11px;
  background: rgba(47, 110, 244, 0.1);
  color: var(--primary-color);
}

.workspace-chat-icon svg {
  width: 18px;
  height: 18px;
}

.workspace-chat-info {
  min-width: 0;
}

.workspace-chat-info h4 {
  margin: 0 0 3px;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-chat-info p,
.workspace-chat-info span {
  display: block;
  margin: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-chat-info span {
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
}

.workspace-chat-delete {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.workspace-chat-delete:hover {
  border-color: rgba(239, 68, 68, 0.24);
  background: rgba(239, 68, 68, 0.08);
  color: #dc2626;
}

.workspace-chat-delete svg {
  width: 16px;
  height: 16px;
}

.runtime-toolbar {
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.18);
  border-bottom: 1px solid var(--border-color);
}

.runtime-summary {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}

.runtime-summary-value {
  color: var(--text-primary);
  font-size: 20px;
  font-weight: 750;
  line-height: 1;
}

.runtime-refresh {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--glass-bg-strong);
  color: var(--text-primary);
  cursor: pointer;
  transition: transform 0.12s ease, border-color 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
}

.runtime-toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.runtime-refresh:hover:not(:disabled) {
  border-color: rgba(47, 110, 244, 0.45);
  background: color-mix(in srgb, var(--glass-bg-strong) 84%, rgba(47, 110, 244, 0.14));
  box-shadow: 0 8px 18px rgba(47, 110, 244, 0.12);
}

.runtime-refresh:active:not(:disabled) {
  transform: scale(0.94);
  box-shadow: inset 0 2px 6px rgba(17, 24, 39, 0.14);
}

.runtime-refresh.runtime-danger {
  color: #ef4444;
}

.runtime-refresh.runtime-danger:hover:not(:disabled) {
  border-color: rgba(239, 68, 68, 0.45);
  background: color-mix(in srgb, var(--glass-bg-strong) 84%, rgba(239, 68, 68, 0.12));
  box-shadow: 0 8px 18px rgba(239, 68, 68, 0.1);
}

.runtime-refresh:disabled {
  opacity: 0.5;
  cursor: wait;
}

.runtime-refresh svg {
  width: 15px;
  height: 15px;
}

.runtime-meta {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-secondary);
  font-size: 12px;
}

.runtime-meta div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.runtime-meta strong {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-empty {
  margin: 16px;
  padding: 18px;
  border: 1px dashed var(--border-color);
  border-radius: 14px;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.42);
  font-size: 13px;
  text-align: center;
}

.runtime-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.runtime-turns {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color);
  overflow-x: auto;
}

.runtime-turn {
  min-width: 180px;
  max-width: 260px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.58);
}

.runtime-turn-status {
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(47, 110, 244, 0.12);
  color: #245bd2;
  font-size: 11px;
  font-weight: 700;
}

.runtime-turn-input {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-events {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  overflow-y: auto;
}

.runtime-event {
  border: 1px solid var(--border-color);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.66);
  box-shadow: 0 10px 24px rgba(17, 24, 39, 0.06);
  overflow: hidden;
}

.runtime-event-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
  color: var(--text-secondary);
  font-size: 12px;
}

.runtime-event-head time {
  margin-left: auto;
  flex: 0 0 auto;
}

.runtime-seq {
  color: #245bd2;
  font-weight: 750;
}

.runtime-event-type {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-event-summary {
  margin: 0;
  padding: 10px;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.45;
  word-break: break-word;
}

.runtime-event-detail {
  max-height: 180px;
  margin: 0 10px 10px;
  padding: 10px;
  overflow: auto;
  border-radius: 10px;
  background: rgba(17, 24, 39, 0.06);
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

:global(body.workspace-resizing) {
  user-select: none;
  cursor: col-resize;
}

:global(body.source-workspace-resizing) {
  user-select: none;
  cursor: col-resize;
}

:global(body.workspace-resizing) .browser-frame {
  pointer-events: none;
}

:global(body.source-workspace-resizing) .browser-frame {
  pointer-events: none;
}

@media (max-width: 980px) {
  .app-footer {
    grid-template-columns: minmax(120px, 1fr) minmax(0, 1.3fr);
  }

  .app-footer-status {
    display: none;
  }

  .chat-header {
    padding: 10px 14px;
    gap: 10px;
  }

  .logo-text {
    display: none;
  }

  .header-center {
    gap: 10px;
  }

  .header-agent-dock {
    max-width: none;
    min-width: 180px;
  }

  .agent-dock-card {
    width: 92px;
  }

  .model-selector select {
    min-width: 180px;
    max-width: 220px;
  }

  .chat-body.source-open,
  .chat-body.dual-panel {
    flex-direction: column;
  }

  .source-workspace-panel {
    flex: 0 0 auto;
    max-width: none;
    width: auto;
    max-height: 42%;
    margin: 8px 16px 0;
  }

  .source-resizer {
    display: none;
  }

  .chat-body.dual-panel .private-chat-panel {
    min-width: 0;
    min-height: 48%;
    border-right: none;
    border-bottom: 1px solid var(--border-color);
  }

  .workspace-panel {
    flex: 1 1 52%;
    min-width: 0;
    margin: 12px 16px 16px;
  }

  .workspace-resizer {
    display: none;
  }
}
</style>
