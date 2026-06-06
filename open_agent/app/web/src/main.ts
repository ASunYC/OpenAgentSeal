import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './style.css'
import { isNativeMobileRuntime } from './api'

const app = createApp(App)
app.use(createPinia())
app.mount('#app')

if (
  !isNativeMobileRuntime
  && window.isSecureContext
  && 'serviceWorker' in navigator
  && window.location.pathname.startsWith('/mobile')
) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/mobile-sw.js')
  })
}
