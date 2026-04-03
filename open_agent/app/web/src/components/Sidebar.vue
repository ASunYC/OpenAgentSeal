<script setup lang="ts">
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()
</script>

<template>
  <aside class="h-full bg-gray-800 border-r border-gray-700 flex flex-col">
    <!-- Logo -->
    <div class="p-4 border-b border-gray-700">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center text-xl">
          🤖
        </div>
        <div>
          <h1 class="text-lg font-bold">Open Agent</h1>
          <p class="text-xs text-gray-400">智能助手</p>
        </div>
      </div>
    </div>
    
    <!-- Chat List -->
    <div class="flex-1 overflow-y-auto py-2">
      <div class="px-4 py-2 text-xs text-gray-500 uppercase">会话列表</div>
      
      <div
        v-for="chat in store.chats"
        :key="chat.id"
        class="px-4 py-3 cursor-pointer hover:bg-gray-700/50 transition"
        :class="{ 'bg-blue-600/20 border-l-2 border-blue-500': chat.id === store.currentChatId }"
        @click="store.selectChat(chat.id)"
      >
        <div class="flex items-center justify-between">
          <span class="truncate">{{ chat.name }}</span>
          <button
            class="opacity-0 hover:opacity-100 text-gray-400 hover:text-red-400"
            @click.stop="store.deleteChat(chat.id)"
          >
            ✕
          </button>
        </div>
      </div>
      
      <!-- New Chat Button -->
      <button
        class="w-full px-4 py-3 text-left text-blue-400 hover:bg-gray-700/50 transition"
        @click="store.createChat()"
      >
        + 新建会话
      </button>
    </div>
    
    <!-- Status -->
    <div class="p-4 border-t border-gray-700 text-xs text-gray-500">
      <div class="flex items-center gap-2">
        <span class="w-2 h-2 rounded-full" :class="store.isRunning ? 'bg-yellow-500 animate-pulse' : 'bg-green-500'"></span>
        <span>{{ store.isRunning ? '处理中...' : '服务运行中' }}</span>
      </div>
    </div>
  </aside>
</template>