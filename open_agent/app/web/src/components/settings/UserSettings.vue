<template>
  <div class="tab-content">
    <div class="content-header">
      <h3>{{ t('用户设置', 'User Settings') }}</h3>
      <p>{{ t('管理你的个人信息', 'Manage your personal information') }}</p>
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
        <input ref="avatarInput" class="hidden-input" type="file" accept="image/*" @change="onAvatarSelected" />
      </div>

      <div class="form-section">
        <div class="form-group">
          <label>{{ t('用户名', 'Username') }}</label>
          <input v-model="user.name" type="text" :placeholder="t('输入用户名', 'Enter username')" />
        </div>

        <div class="form-group">
          <label>{{ t('邮箱', 'Email') }}</label>
          <input v-model="user.email" type="email" :placeholder="t('输入邮箱', 'Enter email')" />
        </div>

        <div class="form-actions">
          <button class="btn-primary" :disabled="saving" @click="saveUser">
            {{ saving ? t('保存中...', 'Saving...') : t('保存', 'Save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'

const settingsStore = useSettingsStore()
const avatarInput = ref<HTMLInputElement | null>(null)
const saving = ref(false)

const user = reactive({
  name: '',
  email: '',
  avatar: '',
})

function t(zh: string, en: string): string {
  return settingsStore.t(zh, en)
}

function changeAvatar() {
  avatarInput.value?.click()
}

function onAvatarSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = () => {
    user.avatar = String(reader.result || '')
  }
  reader.readAsDataURL(file)
  input.value = ''
}

async function saveUser() {
  saving.value = true
  try {
    localStorage.setItem('open-agent-user', JSON.stringify(user))
    alert(t('保存成功', 'Saved successfully'))
  } catch (error) {
    console.error('Failed to save user settings:', error)
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
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
}

.content-header p {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
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
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: #fff;
  font-size: 40px;
  font-weight: 600;
}

.hidden-input {
  display: none;
}

.btn-change-avatar {
  padding: 8px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--hover-bg);
  color: var(--text-primary);
  cursor: pointer;
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
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 500;
}

.form-group input {
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--input-bg);
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
  border: none;
  border-radius: 8px;
  background: var(--primary-color);
  color: #fff;
  cursor: pointer;
}

.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
