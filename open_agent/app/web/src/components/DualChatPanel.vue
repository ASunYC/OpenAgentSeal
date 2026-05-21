<script setup lang="ts">
import { ref } from 'vue'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()

const privateInputText = ref('')
const messagesContainer = ref<HTMLElement | null>(null)

async function handlePrivateSend() {
  const text = privateInputText.value.trim()
  if (!text || chatStore.isRunning) return
  
  privateInputText.value = ''
  await chatStore.sendMessage(text)
}

function handlePrivateKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handlePrivateSend()
  }
}

</script>

<template>
  <div class="h-full flex flex-col">
    <header class="px-6 py-4 border-b border-gray-700 bg-gray-800/50">
      <h2 class="text-lg font-medium">
        {{ chatStore.currentChat?.name || '选择或创建对话' }}
      </h2>
    </header>
    
    <div 
      ref="messagesContainer"
      class="flex-1 overflow-y-auto px-6 py-4 space-y-4"
    >
      <div v-if="chatStore.messages.length === 0" class="text-center text-gray-500 py-20">
        <div class="text-6xl mb-4">💬</div>
        <p>开始新对话</p>
      </div>
      
      <div
        v-for="(msg, idx) in chatStore.messages"
        :key="idx"
        class="flex gap-4 fade-in"
        :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div 
          v-if="msg.role !== 'user'"
          class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-sm flex-shrink-0"
        >
          🤖
        </div>
        
        <div
          class="max-w-[70%] px-4 py-3 rounded-2xl"
          :class="msg.role === 'user' 
            ? 'bg-blue-600 text-white rounded-br-md' 
            : 'bg-gray-700 text-gray-100 rounded-bl-md'"
        >
          <div class="whitespace-pre-wrap break-words">{{ msg.content }}</div>
        </div>
        
        <div 
          v-if="msg.role === 'user'"
          class="w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center text-sm flex-shrink-0"
        >
          👤
        </div>
      </div>
      
      <div v-if="chatStore.isRunning" class="flex gap-4 fade-in">
        <div class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-sm">
          🤖
        </div>
        <div class="bg-gray-700 px-4 py-3 rounded-2xl rounded-bl-md">
          <div class="thinking-spinner"></div>
        </div>
      </div>
    </div>
    
    <div class="px-6 py-4 border-t border-gray-700 bg-gray-800/50">
      <div class="flex gap-3">
        <textarea
          v-model="privateInputText"
          class="flex-1 bg-gray-700 border border-gray-600 rounded-xl px-4 py-3 resize-none focus:outline-none focus:border-blue-500 transition"
          placeholder="输入消息... (Shift+Enter 换行)"
          rows="1"
          @keydown="handlePrivateKeydown"
          :disabled="chatStore.isRunning || !chatStore.currentChatId"
        ></textarea>
        <button
          class="px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-xl font-medium transition"
          @click="handlePrivateSend"
          :disabled="!privateInputText.trim() || chatStore.isRunning || !chatStore.currentChatId"
        >
          发送
        </button>
        <button
          v-if="chatStore.isRunning"
          class="px-4 py-3 bg-red-600 hover:bg-red-500 rounded-xl font-medium transition"
          @click="chatStore.cancel"
        >
          停止
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.thinking-spinner {
  display: inline-block;
  width: 20px;
  height: 20px;
  border: 2px solid #4b5563;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.fade-in {
  animation: fadeIn 0.3s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
