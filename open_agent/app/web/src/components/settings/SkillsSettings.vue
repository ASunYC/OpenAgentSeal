<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('技能管理', 'Skills Management') }}</h3>
      <p>{{ t('管理AI技能', 'Manage AI skills') }}</p>
    </div>
    
    <div v-if="loading" class="loading-state">
      <span>{{ t('加载中...', 'Loading...') }}</span>
    </div>
    
    <div v-else-if="error" class="error-state">
      <span>{{ t('加载失败: ', 'Failed to load: ') }}{{ error }}</span>
    </div>
    
    <div v-else-if="skills.length === 0" class="empty-state">
      <span>{{ t('暂无技能', 'No skills available') }}</span>
    </div>
    
    <div v-else class="skills-grid">
      <div class="skill-card" v-for="skill in skills" :key="skill.name">
        <div class="skill-header">
          <div class="skill-icon">{{ skill.icon }}</div>
          <div class="skill-info">
            <h4>{{ skill.name }}</h4>
            <p>{{ skill.description }}</p>
          </div>
        </div>
        <div class="skill-actions">
          <button class="btn-toggle" :class="{ active: skill.enabled }" @click="toggleSkill(skill)">
            {{ skill.enabled ? t('启用', 'Enabled') : t('禁用', 'Disabled') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()

interface Skill {
  name: string
  icon: string
  description: string
  enabled: boolean
}

const skills = ref<Skill[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

async function loadSkills() {
  loading.value = true
  error.value = null
  try {
    const response = await fetch('/api/skills')
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }
    const data = await response.json()
    skills.value = data.map((skill: any) => ({
      ...skill,
      enabled: skill.enabled ?? true
    }))
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    console.error('Failed to load skills:', e)
  } finally {
    loading.value = false
  }
}

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function toggleSkill(skill: Skill) {
  skill.enabled = !skill.enabled
  // TODO: Save enabled state to backend
}

onMounted(() => {
  loadSkills()
})
</script>

<style scoped>
.tab-content { display: flex; flex-direction: column; gap: 20px; }
.content-header { margin-bottom: 8px; }
.content-header h3 { font-size: 16px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.content-header p { font-size: 13px; color: var(--text-muted); margin: 0; }

.loading-state,
.error-state,
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text-muted);
  font-size: 14px;
}

.error-state {
  color: #ef4444;
}

.skills-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.skill-card { background: var(--main-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 16px; }
.skill-header { display: flex; gap: 12px; margin-bottom: 12px; }
.skill-icon { width: 40px; height: 40px; border-radius: 10px; background: var(--hover-bg); display: flex; align-items: center; justify-content: center; font-size: 20px; }
.skill-info { flex: 1; }
.skill-info h4 { font-size: 14px; font-weight: 600; color: var(--text-primary); margin: 0 0 4px 0; }
.skill-info p { font-size: 12px; color: var(--text-muted); margin: 0; }
.skill-actions { display: flex; justify-content: flex-end; }
.btn-toggle { padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border-color); background: var(--hover-bg); color: var(--text-secondary); font-size: 12px; cursor: pointer; transition: all 0.2s; }
.btn-toggle.active { background: var(--primary-color); border-color: var(--primary-color); color: white; }
</style>
