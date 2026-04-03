<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import type { ThinkingStep } from '@/types'

interface Props {
  thinking: {
    isThinking: boolean
    steps: ThinkingStep[]
  }
  isVisible: boolean
  maxSteps?: number
  userQuery?: string  // 用户输入的查询
  currentStep?: number  // 当前步骤
}

const props = withDefaults(defineProps<Props>(), {
  maxSteps: 100,
  userQuery: '',
  currentStep: 0
})

const isExpanded = ref(true)
const contentRef = ref<HTMLDivElement>()

watch(() => props.thinking.steps, async () => {
  await nextTick()
  if (contentRef.value) {
    contentRef.value.scrollTop = contentRef.value.scrollHeight
  }
}, { immediate: true, deep: true })

const toggleExpand = () => {
  isExpanded.value = !isExpanded.value
}

// 计算用户查询摘要（最多显示30个字符）
const querySummary = computed(() => {
  if (!props.userQuery) return ''
  const query = props.userQuery.trim()
  if (query.length <= 30) return query
  return query.substring(0, 30) + '...'
})

// 计算当前步骤进度
const stepProgress = computed(() => {
  const current = props.currentStep || props.thinking.steps.length
  return `${current}/${props.maxSteps}`
})

const getStepIcon = (type: ThinkingStep['type']) => {
  switch (type) {
    case 'thinking': return '📌'
    case 'tool_call': return '🔧'
    case 'tool_result': return '✅'
    case 'observation': return '👁️'
    default: return '📌'
  }
}

const getStepTitle = (type: ThinkingStep['type']) => {
  switch (type) {
    case 'thinking': return '步骤'
    case 'tool_call': return '调用工具'
    case 'tool_result': return '工具结果'
    case 'observation': return '观察'
    default: return '步骤'
  }
}
</script>

<template>
  <div
    v-if="thinking.steps.length > 0 || thinking.isThinking"
    class="thinking-process iteration-process"
  >
    <div
      class="thinking-header iteration-header"
      @click="toggleExpand"
    >
      <span class="thinking-icon">🔄</span>
      <span class="thinking-title">迭代过程</span>
      <span class="thinking-progress">
        <span class="thinking-count">{{ thinking.steps.length }} / {{ maxSteps }}</span>
        <span
          v-if="thinking.isThinking"
          class="thinking-status"
        >· 执行中...</span>
      </span>
      <span class="thinking-toggle">{{ isExpanded ? '收起' : '展开' }}</span>
    </div>

    <div
      v-show="isExpanded"
      ref="contentRef"
      class="thinking-content iteration-content"
    >
      <!-- 用户查询摘要 -->
      <div v-if="querySummary" class="query-info">
        <span class="query-label">任务:</span>
        <span class="query-text">{{ querySummary }}</span>
      </div>
      <div
        v-if="thinking.steps.length === 0 && thinking.isThinking"
        class="thinking-text"
      >
        正在执行...
      </div>
      <div
        v-else-if="thinking.steps.length > 0"
        class="thinking-steps iteration-steps"
      >
        <div
          v-for="(step, index) in thinking.steps"
          :key="step.id"
          class="thinking-step iteration-step"
          :class="`step-${step.type}`"
        >
          <div class="step-header">
            <span class="step-number">{{ index + 1 }}</span>
            <span class="step-icon">{{ getStepIcon(step.type) }}</span>
            <span class="step-title">{{ getStepTitle(step.type) }}</span>
            <span
              v-if="step.toolName"
              class="step-tool-name"
            >{{ step.toolName }}</span>
          </div>
          <div class="step-content">
            {{ step.content }}
          </div>
          <div
            v-if="step.toolOutput"
            class="step-output"
          >
            <div class="output-label">
              输出:
            </div>
            <div class="output-content">
              {{ step.toolOutput }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.thinking-process {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 8px;
  margin: 8px 0;
  overflow: hidden;
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(59, 130, 246, 0.2);
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}

.thinking-header:hover {
  background: rgba(59, 130, 246, 0.3);
}

.thinking-icon {
  font-size: 14px;
}

.thinking-title {
  font-size: 12px;
  font-weight: 600;
  color: #60a5fa;
}

.query-summary {
  color: #1e40af;
  font-weight: 500;
}

.thinking-progress {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 8px;
}

.thinking-count {
  font-size: 11px;
  color: #9ca3af;
  font-weight: 500;
  background: rgba(0, 0, 0, 0.2);
  padding: 2px 6px;
  border-radius: 4px;
}

.thinking-status {
  font-size: 11px;
  color: #60a5fa;
  animation: pulse 1.5s infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.thinking-toggle {
  font-size: 11px;
  color: #9ca3af;
  margin-left: auto;
}

.thinking-content {
  max-height: 300px;
  overflow-y: auto;
  padding: 12px;
  animation: slideDown 0.3s ease;
}

/* 用户查询信息 */
.query-info {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  background: rgba(59, 130, 246, 0.15);
  border-radius: 6px;
  margin-bottom: 12px;
  border-left: 3px solid #3b82f6;
}

.query-label {
  font-size: 11px;
  font-weight: 600;
  color: #60a5fa;
  flex-shrink: 0;
}

.query-text {
  font-size: 12px;
  color: #e5e7eb;
  line-height: 1.5;
  word-break: break-word;
}

@keyframes slideDown {
  from {
    max-height: 0;
    opacity: 0;
  }
  to {
    max-height: 300px;
    opacity: 1;
  }
}

.thinking-text {
  font-size: 13px;
  line-height: 1.6;
  color: #d1d5db;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* 思考步骤列表 */
.thinking-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.thinking-step {
  background: rgba(31, 41, 55, 0.8);
  border-radius: 6px;
  padding: 10px 12px;
  border-left: 3px solid #3b82f6;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.thinking-step:hover {
  transform: translateX(2px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}

.thinking-step.step-tool_call {
  border-left-color: #f59e0b;
}

.thinking-step.step-tool_result {
  border-left-color: #10b981;
}

.thinking-step.step-observation {
  border-left-color: #8b5cf6;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.step-number {
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  background: #3b82f6;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.thinking-step.step-tool_call .step-number {
  background: #f59e0b;
}

.thinking-step.step-tool_result .step-number {
  background: #10b981;
}

.thinking-step.step-observation .step-number {
  background: #8b5cf6;
}

.step-icon {
  font-size: 12px;
}

.step-title {
  font-size: 11px;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
}

.step-tool-name {
  font-size: 11px;
  color: #60a5fa;
  background: rgba(59, 130, 246, 0.2);
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: auto;
}

.step-content {
  font-size: 13px;
  line-height: 1.5;
  color: #e5e7eb;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  white-space: pre-wrap;
  word-wrap: break-word;
  margin-left: 24px;
}

.step-output {
  margin-top: 8px;
  padding: 8px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 4px;
  margin-left: 24px;
}

.output-label {
  font-size: 11px;
  color: #9ca3af;
  margin-bottom: 4px;
}

.output-content {
  font-size: 12px;
  line-height: 1.4;
  color: #d1d5db;
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* 滚动条样式 */
.thinking-content::-webkit-scrollbar {
  width: 6px;
}

.thinking-content::-webkit-scrollbar-track {
  background: rgba(31, 41, 55, 0.5);
  border-radius: 3px;
}

.thinking-content::-webkit-scrollbar-thumb {
  background: #4b5563;
  border-radius: 3px;
}

.thinking-content::-webkit-scrollbar-thumb:hover {
  background: #6b7280;
}
</style>