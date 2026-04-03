/**
 * Session store following CoPaw's Pinia pattern
 * Manages chats and messages state
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Chat, Message, AgentEvent } from '@/types'
import { chatApi, runAgentStream, cancelSession } from '@/api'

export const useSessionStore = defineStore('session', () => {
  // State
  const chats = ref<Chat[]>([])
  const currentChatId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isRunning = ref(false)
  const currentEvents = ref<AgentEvent[]>([])
  const error = ref<string | null>(null)

  // Getters
  const currentChat = computed(() => 
    chats.value.find(c => c.id === currentChatId.value)
  )

  const currentSessionId = computed(() => 
    currentChat.value?.session_id
  )

  // Actions
  async function loadChats() {
    try {
      chats.value = await chatApi.list()
      if (chats.value.length > 0 && !currentChatId.value) {
        await selectChat(chats.value[0].id)
      }
    } catch (e) {
      error.value = String(e)
    }
  }

  async function createChat(name = 'New Chat') {
    try {
      const chat = await chatApi.create(name)
      chats.value.unshift(chat)
      await selectChat(chat.id)
      return chat
    } catch (e) {
      error.value = String(e)
      return null
    }
  }

  async function selectChat(chatId: string) {
    currentChatId.value = chatId
    messages.value = []
    currentEvents.value = []
    
    try {
      const history = await chatApi.getHistory(chatId)
      messages.value = history.messages
    } catch (e) {
      // New chat might not have history
    }
  }

  async function deleteChat(chatId: string) {
    try {
      await chatApi.delete(chatId)
      chats.value = chats.value.filter(c => c.id !== chatId)
      if (currentChatId.value === chatId) {
        currentChatId.value = chats.value[0]?.id || null
        if (currentChatId.value) {
          await selectChat(currentChatId.value)
        }
      }
    } catch (e) {
      error.value = String(e)
    }
  }

  async function sendMessage(content: string) {
    if (!currentSessionId.value || isRunning.value) return

    // Add user message
    const userMsg: Message = { role: 'user', content }
    messages.value.push(userMsg)
    isRunning.value = true
    currentEvents.value = []

    try {
      // Stream agent response
      for await (const event of runAgentStream(currentSessionId.value, messages.value)) {
        currentEvents.value.push(event)
        
        // Handle different event types
        if (event.event === 'message' && event.content) {
          // Update or append assistant message
          const lastMsg = messages.value[messages.value.length - 1]
          if (lastMsg?.role === 'assistant') {
            lastMsg.content = event.content
          } else {
            messages.value.push({ role: 'assistant', content: event.content })
          }
        }
        
        if (event.event === 'complete' || event.status === 'idle') {
          isRunning.value = false
        }
        
        if (event.event === 'error') {
          error.value = event.error || 'Unknown error'
          isRunning.value = false
        }
      }
    } catch (e) {
      error.value = String(e)
      isRunning.value = false
    }
  }

  async function cancel() {
    if (!currentSessionId.value) return
    await cancelSession(currentSessionId.value)
    isRunning.value = false
  }

  function clearError() {
    error.value = null
  }

  return {
    // State
    chats,
    currentChatId,
    messages,
    isRunning,
    currentEvents,
    error,
    // Getters
    currentChat,
    currentSessionId,
    // Actions
    loadChats,
    createChat,
    selectChat,
    deleteChat,
    sendMessage,
    cancel,
    clearError,
  }
})