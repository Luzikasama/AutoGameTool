<script setup lang="ts">
import { darkTheme, NConfigProvider, NDialogProvider, NMessageProvider, type GlobalThemeOverrides } from 'naive-ui'

const overrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#7c6cf0',
    primaryColorHover: '#9386f4',
    primaryColorPressed: '#6655d8',
    primaryColorSuppl: '#9386f4',
    bodyColor: '#0e1116',
    cardColor: '#1c212b',
    modalColor: '#1c212b',
    popoverColor: '#1c212b',
    borderColor: '#2a303c',
    textColorBase: '#e6e8ee',
  },
}
</script>

<template>
  <n-config-provider :theme="darkTheme" :theme-overrides="overrides">
    <n-message-provider placement="top">
      <n-dialog-provider>
        <div class="app-shell">
          <router-view />
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
