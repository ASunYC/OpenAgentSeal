<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('技能管理', 'Skills Management') }}</h3>
      <p>{{ t('管理智能体最终可用的技能能力', 'Manage skills available to the agent') }}</p>
      <span class="count-pill">{{ t('技能', 'Skills') }} {{ filteredSkills.length }}/{{ skills.length }}</span>
    </div>

    <div class="settings-search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/>
        <path d="m21 21-4.3-4.3"/>
      </svg>
      <input
        v-model="searchQuery"
        type="search"
        :placeholder="t('搜索技能名称、来源、描述或路径', 'Search skills by name, source, description, or path')"
      />
      <button v-if="searchQuery" type="button" @click="searchQuery = ''">{{ t('清除', 'Clear') }}</button>
    </div>

    <div v-if="loading" class="loading-state">
      <span>{{ t('加载中...', 'Loading...') }}</span>
    </div>

    <div v-else-if="error" class="error-state">
      <span>{{ t('加载失败：', 'Failed to load: ') }}{{ error }}</span>
    </div>

    <div v-else-if="skills.length === 0" class="empty-state">
      <span>{{ t('暂无技能', 'No skills available') }}</span>
    </div>

    <div v-else class="skills-grid">
      <div v-for="skill in filteredSkills" :key="skill.path || skill.name" class="skill-card">
        <div class="skill-header">
          <div class="skill-icon">{{ skill.icon || 'S' }}</div>
          <div class="skill-info">
            <h4>{{ skill.name }}</h4>
            <p>{{ skill.description }}</p>
            <span class="source-pill">{{ sourceLabel(skill) }}</span>
          </div>
        </div>
        <div class="skill-actions">
          <button class="btn-toggle" :class="{ active: skill.enabled }" :disabled="savingPath === skill.path" @click="toggleSkill(skill)">
            {{ skill.enabled ? t('启用', 'Enabled') : t('禁用', 'Disabled') }}
          </button>
        </div>
      </div>

      <div v-if="filteredSkills.length === 0" class="empty-state wide">
        <span>{{ t('没有匹配的技能', 'No matching skills') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { skillsApi, type SkillConfig } from '@/api'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const skills = ref<SkillConfig[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const savingPath = ref<string | null>(null)
const searchQuery = ref('')

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function sourceLabel(skill: SkillConfig) {
  if (skill.source === 'plugin') {
    return `${t('插件', 'Plugin')}: ${skill.source_label || skill.plugin_id || '-'}`
  }
  if (skill.source === 'user') {
    return t('用户技能', 'User skill')
  }
  return t('内置技能', 'Built-in')
}

const filteredSkills = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return skills.value
  return skills.value.filter((skill) => [
    skill.name,
    skill.description,
    skill.path,
    skill.source,
    skill.source_label,
    skill.plugin_id,
    sourceLabel(skill),
    skill.enabled ? 'enabled 启用' : 'disabled 禁用',
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .includes(query))
})

async function loadSkills() {
  loading.value = true
  error.value = null
  try {
    skills.value = await skillsApi.list()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    skills.value = []
  } finally {
    loading.value = false
  }
}

async function toggleSkill(skill: SkillConfig) {
  if (!skill.path) return
  const next = !skill.enabled
  savingPath.value = skill.path
  try {
    const result = await skillsApi.setEnabled(skill.path, next)
    if (!result.success) {
      throw new Error(result.error || 'Failed to update skill')
    }
    skill.enabled = next
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  } finally {
    savingPath.value = null
  }
}

onMounted(() => {
  void loadSkills()
})
</script>

<style scoped>
.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.content-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 16px;
  align-items: start;
  margin-bottom: 8px;
}

.content-header h3 {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
}

.content-header p {
  grid-column: 1;
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.count-pill {
  grid-column: 2;
  grid-row: 1 / span 2;
  padding: 5px 10px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
}

.settings-search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
}

.settings-search svg {
  width: 16px;
  height: 16px;
  color: var(--text-muted);
  flex: 0 0 auto;
}

.settings-search input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
}

.settings-search button {
  flex: 0 0 auto;
  border: 0;
  background: transparent;
  color: var(--primary-color);
  cursor: pointer;
  font-size: 12px;
}

.loading-state,
.error-state,
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
  color: var(--text-muted);
  font-size: 14px;
}

.empty-state.wide {
  grid-column: 1 / -1;
}

.error-state {
  color: #ef4444;
}

.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.skill-card {
  padding: 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--main-bg);
}

.skill-header {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.skill-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--hover-bg);
  font-size: 20px;
}

.skill-info {
  flex: 1;
  min-width: 0;
}

.skill-info h4 {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.skill-info p {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.source-pill {
  display: inline-flex;
  margin-top: 8px;
  padding: 3px 8px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.2;
}

.skill-actions {
  display: flex;
  justify-content: flex-end;
}

.btn-toggle {
  padding: 6px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--hover-bg);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s ease;
}

.btn-toggle.active {
  border-color: var(--primary-color);
  background: var(--primary-color);
  color: #fff;
}

.btn-toggle:disabled {
  opacity: 0.6;
  cursor: wait;
}
</style>
