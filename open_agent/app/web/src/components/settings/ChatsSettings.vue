<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('对话管理', 'Chat Management') }}</h3>
      <p>{{ t('查看和管理历史对话', 'View and manage chat history') }}</p>
    </div>
    
    <div class="chats-list">
      <div 
        class="chat-item" 
        v-for="chat in chatStore.chats" 
        :key="chat.id"
      >
        <div class="chat-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <div class="chat-info">
          <h4>{{ chat.name }}</h4>
          <p>{{ formatDate(chat.updated_at) }}</p>
        </div>
        <div class="chat-actions">
          <button class="btn-icon" @click="deleteChat(chat)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3,6 5,6 21,6"/>
              <path d="M19,6v14a2,2,0,0,1-2,2H7a2,2,0,0,1-2-2V6m3,0V4a2,2,0,0,1,2-2h4a2,2,0,0,1,2,2v2"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { useChatStore } from '@/stores/chat'
import type { Chat } from '@/types'

const settingsStore = useSettingsStore()
const chatStore = useChatStore()

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function formatDate(date: string): string {
  return new Date(date).toLocaleDateString(settingsStore.settings.language === 'zh-CN' ? 'zh-CN' : 'en-US')
}

function deleteChat(chat: Chat) {
  if (confirm(t('确定要删除此对话吗？', 'Are you sure you want to delete this chat?'))) {
    chatStore.deleteChat(chat.id)
  }
}

onMounted(async () => {
  await chatStore.loadChats()
})
</script>

<style scoped>
.tab-content { display: flex; flex-direction: column; gap: 20px; }
.content-header { margin-bottom: 8px; }
.content-header h3 { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.content-header p { font-size: 13px; color: var(--text-muted); margin: 0; }
.chats-list { display: flex; flex-direction: column; gap: 8px; }
.chat-item { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 10px; }
.chat-icon { width: 40px; height: 40px; border-radius: 10px; background: var(--hover-bg); display: flex; align-items: center; justify-content: center; color: var(--text-secondary); }
.chat-icon svg { width: 20px; height: 20px; }
.chat-info { flex: 1; }
.chat-info h4 { font-size: 14px; font-weight: 500; color: var(--text-primary); margin: 0 0 2px 0; }
.chat-info p { font-size: 12px; color: var(--text-muted); margin: 0; }
.btn-icon { width: 32px; height: 32px; border-radius: 8px; border: none; background: transparent; color: var(--text-secondary); cursor: pointer; display: flex; align-items: center; justify-content: center; }
.btn-icon:hover { background: var(--hover-bg); color: #ef4444; }
.btn-icon svg { width: 16px; height: 16px; }
</style>
