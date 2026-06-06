<template>
  <MobileShell v-if="isMobileRoute" />
  <DesktopApp v-else />
</template>

<script setup lang="ts">
import { isNativeMobileRuntime } from '@/api'
import DesktopApp from '@/DesktopApp.vue'
import MobileShell from '@/components/MobileShell.vue'

const isMobileRoute = isNativeMobileRuntime
  || (typeof window !== 'undefined' && window.location.pathname.startsWith('/mobile'))
</script>
