<script setup lang="ts">
import { darkTheme, NConfigProvider, NDialogProvider, NMessageProvider, type GlobalThemeOverrides } from 'naive-ui'
import { useUiStore } from './stores/ui'

// 自定义背景铺在整个界面最底层（首页/编辑器都生效），面板与画布各自压一层暗色底
const ui = useUiStore()

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
        <div class="app-shell" :class="{ 'has-bg': !!ui.bgImage }">
          <!-- 背景层：纯装饰，pointer-events 关掉，不影响任何点击 -->
          <div
            v-if="ui.bgImage"
            class="app-bg"
            :style="{ backgroundImage: `url(${ui.bgImage})`, opacity: String(ui.bgOpacity) }"
          />
          <router-view />
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
