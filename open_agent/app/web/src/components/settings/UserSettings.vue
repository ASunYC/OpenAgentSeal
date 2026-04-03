<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('用户设置', 'User Settings') }}</h3>
      <p>{{ t('管理您的个人信息', 'Manage your personal information') }}</p>
    </div>
    
    <div class="user-profile">
      <div class="avatar-section">
        <div class="user-avatar">
          <img v-if="user.avatar" :src="user.avatar" alt="Avatar" />
          <div v-else class="avatar-placeholder">
            {{ user.name?.charAt(0)?.toUpperCase() || 'U' }}
          </div>
        </div>
        <button class="btn-change-avatar" @click="changeAvatar">
          {{ t('更换头像', 'Change Avatar') }}
        </button>
      </div>
      
      <div class="form-section">
        <div class="form-group">
          <label>{{ t('用户名', 'Username') }}</label>
          <input 
            v-model="user.name" 
            type="text" 
            :placeholder="t('输入用户名', 'Enter username')"
          />
        </div>
        
        <div class="form-group">
          <label>{{ t('邮箱', 'Email') }}</label>
          <input 
            v-model="user.email" 
            type="email" 
            :placeholder="t('输入邮箱', 'Enter email')"
          />
        </div>
        
        <div class="form-actions">
          <button class="btn-primary" @click="saveUser" :disabled="saving">
            {{ saving ? t('保存中...', 'Saving...') : t('保存', 'Save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()

const user = reactive({
  name: '',
  email: '',
  avatar: ''
})

const saving = ref(false)

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function changeAvatar() {
  // TODO: 实现头像更换
  alert(t('头像更换功能开发中', 'Avatar change feature under development'))
}

async function saveUser() {
  saving.value = true
  try {
    // TODO: 调用API保存用户信息
    localStorage.setItem('open-agent-user', JSON.stringify(user))
    alert(t('保存成功', 'Saved successfully'))
  } catch (error) {
    alert(t('保存失败', 'Save failed'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  const saved = localStorage.getItem('open-agent-user')
  if (saved) {
    Object.assign(user, JSON.parse(saved))
  }
})
</script>

<style scoped>
.tab-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.content-header {
  margin-bottom: 8px;
}

.content-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.content-header p {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
}

.user-profile {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.avatar-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.user-avatar {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  overflow: hidden;
  background: var(--primary-color);
}

.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40px;
  font-weight: 600;
  color: white;
}

.btn-change-avatar {
  padding: 8px 16px;
  background: var(--hover-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-change-avatar:hover {
  background: var(--border-color);
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-group label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.form-group input {
  padding: 10px 14px;
  background: var(--input-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
}

.form-group input:focus {
  outline: none;
  border-color: var(--primary-color);
}

.form-actions {
  margin-top: 8px;
}

.btn-primary {
  padding: 10px 24px;
  background: var(--primary-color);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>