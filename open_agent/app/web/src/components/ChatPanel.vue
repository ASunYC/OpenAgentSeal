<script setup lang="ts">
import { ref, nextTick, watch } from 'vue'
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()
const inputText = ref('')
const messagesContainer = ref<HTMLElement | null>(null)

// Auto scroll to bottom
watch(() => store.messages.length, async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
})

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || store.isRunning) return
  
  inputText.value = ''
  await store.sendMessage(text)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- Header -->
    <header class="px-6 py-4 border-b border-gray-700 bg-gray-800/50">
      <h2 class="text-lg font-medium">
        {{ store.currentChat?.name || '选择或创建会话' }}
      </h2>
    </header>
    
    <!-- Messages -->
    <div 
      ref="messagesContainer"
      class="flex-1 overflow-y-auto px-6 py-4 space-y-4"
    >
      <div v-if="store.messages.length === 0" class="text-center text-gray-500 py-20">
        <div class="text-6xl mb-4">💬</div>
        <p>开始新对话</p>
      </div>
      
      <div
        v-for="(msg, idx) in store.messages"
        :key="idx"
        class="flex gap-4 fade-in"
        :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
      >
        <!-- Avatar -->
        <div 
          v-if="msg.role !== 'user'"
          class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-sm flex-shrink-0"
        >
          🤖
        </div>
        
        <!-- Message Bubble -->
        <div
          class="max-w-[70%] px-4 py-3 rounded-2xl"
          :class="msg.role === 'user' 
            ? 'bg-blue-600 text-white rounded-br-md' 
            : 'bg-gray-700 text-gray-100 rounded-bl-md'"
        >
          <div class="whitespace-pre-wrap break-words">{{ msg.content }}</div>
        </div>
        
        <!-- User Avatar -->
        <div 
          v-if="msg.role === 'user'"
          class="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center text-sm flex-shrink-0"
        >
          👤
        </div>
      </div>
      
      <!-- Thinking indicator -->
      <div v-if="store.isRunning" class="flex gap-4 fade-in">
        <div class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-sm">
          🤖
        </div>
        <div class="bg-gray-700 px-4 py-3 rounded-2xl rounded-bl-md">
          <div class="thinking-spinner"></div>
        </div>
      </div>
    </div>
    
    <!-- Input Area -->
    <div class="px-6 py-4 border-t border-gray-700 bg-gray-800/50">
      <div class="flex gap-3">
        <textarea
          v-model="inputText"
          class="flex-1 bg-gray-700 border border-gray-600 rounded-xl px-4 py-3 resize-none focus:outline-none focus:border-blue-500 transition"
          placeholder="输入消息... (Shift+Enter 换行)"
          rows="1"
          @keydown="handleKeydown"
          :disabled="store.isRunning || !store.currentChatId"
        ></textarea>
        <button
          class="px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-xl font-medium transition"
          @click="handleSend"
          :disabled="!inputText.trim() || store.isRunning || !store.currentChatId"
        >
          发送
        </button>
        <button
          v-if="store.isRunning"
          class="px-4 py-3 bg-red-600 hover:bg-red-500 rounded-xl font-medium transition"
          @click="store.cancel"
        >
          停止
        </button>
      </div>
    </div>
  </div>
</template>