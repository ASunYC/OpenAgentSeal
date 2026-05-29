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
        <span class="thinking-count">{{ stepProgress }}</span>
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
  --iteration-accent: var(--primary-color);
  --iteration-accent-soft: color-mix(in srgb, var(--primary-color) 12%, transparent);
  --iteration-accent-border: color-mix(in srgb, var(--primary-color) 28%, var(--border-color));
  --iteration-surface: var(--glass-bg);
  --iteration-surface-strong: var(--glass-bg-strong);
  --iteration-step-surface: color-mix(in srgb, var(--glass-bg-strong) 88%, var(--bg-secondary));
  --iteration-output-bg: color-mix(in srgb, var(--bg-tertiary) 58%, transparent);

  background: var(--iteration-surface);
  border: 1px solid var(--iteration-accent-border);
  border-radius: 14px;
  margin: 8px 0 10px;
  overflow: hidden;
  color: var(--text-primary);
  box-shadow: var(--soft-shadow), inset 0 1px 0 var(--glass-border);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--iteration-accent) 10%, transparent),
    color-mix(in srgb, var(--iteration-accent) 5%, transparent)
  );
  border-bottom: 1px solid color-mix(in srgb, var(--iteration-accent) 18%, transparent);
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease, color 0.2s ease;
}

.thinking-header:hover {
  background: color-mix(in srgb, var(--iteration-accent) 12%, transparent);
}

.thinking-icon {
  font-size: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 8px;
  background: var(--iteration-accent-soft);
}

.thinking-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--iteration-accent);
}

.query-summary {
  color: var(--iteration-accent);
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
  color: var(--text-secondary);
  font-weight: 500;
  background: color-mix(in srgb, var(--iteration-accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--iteration-accent) 16%, transparent);
  padding: 2px 7px;
  border-radius: 999px;
}

.thinking-status {
  font-size: 11px;
  color: var(--iteration-accent);
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
  color: var(--text-muted);
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
  padding: 9px 10px;
  background: var(--iteration-accent-soft);
  border-radius: 10px;
  margin-bottom: 12px;
  border: 1px solid color-mix(in srgb, var(--iteration-accent) 14%, transparent);
  border-left: 3px solid var(--iteration-accent);
}

.query-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--iteration-accent);
  flex-shrink: 0;
}

.query-text {
  font-size: 12px;
  color: var(--text-primary);
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
  color: var(--text-secondary);
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
  background: var(--iteration-step-surface);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 10px 12px;
  border-left: 3px solid var(--iteration-accent);
  box-shadow: inset 0 1px 0 var(--glass-border);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.thinking-step:hover {
  transform: translateX(2px);
  box-shadow: var(--soft-shadow), inset 0 1px 0 var(--glass-border);
}

.thinking-step.step-tool_call {
  border-left-color: var(--warning-color);
}

.thinking-step.step-tool_result {
  border-left-color: var(--success-color);
}

.thinking-step.step-observation {
  border-left-color: color-mix(in srgb, var(--primary-color) 68%, var(--text-secondary));
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
  background: var(--iteration-accent);
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.thinking-step.step-tool_call .step-number {
  background: var(--warning-color);
}

.thinking-step.step-tool_result .step-number {
  background: var(--success-color);
}

.thinking-step.step-observation .step-number {
  background: color-mix(in srgb, var(--primary-color) 68%, var(--text-secondary));
}

.step-icon {
  font-size: 12px;
}

.step-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
}

.step-tool-name {
  font-size: 11px;
  color: var(--iteration-accent);
  background: var(--iteration-accent-soft);
  border: 1px solid color-mix(in srgb, var(--iteration-accent) 14%, transparent);
  padding: 2px 7px;
  border-radius: 999px;
  margin-left: auto;
}

.step-content {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  white-space: pre-wrap;
  word-wrap: break-word;
  margin-left: 24px;
}

.step-output {
  margin-top: 8px;
  padding: 9px 10px;
  background: var(--iteration-output-bg);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  margin-left: 24px;
}

.output-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.output-content {
  font-size: 12px;
  line-height: 1.4;
  color: var(--text-secondary);
  font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* 滚动条样式 */
.thinking-content::-webkit-scrollbar {
  width: 6px;
}

.thinking-content::-webkit-scrollbar-track {
  background: transparent;
  border-radius: 3px;
}

.thinking-content::-webkit-scrollbar-thumb {
  background: color-mix(in srgb, var(--text-muted) 32%, transparent);
  border-radius: 3px;
}

.thinking-content::-webkit-scrollbar-thumb:hover {
  background: color-mix(in srgb, var(--text-muted) 48%, transparent);
}
</style>
