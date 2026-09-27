<script setup lang="ts">
import {
  darkTheme,
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  dateZhCN,
  zhCN,
  type GlobalThemeOverrides,
} from 'naive-ui'
import { computed } from 'vue'
import { useUiStore } from './stores/ui'

// 自定义背景铺在整个界面最底层，面板与画布各自压一层底色保证可读
const ui = useUiStore()

// 深色：界面骨架的颜色给全套（画布/面板/文字），避免 Naive 自己的深色与自定义样式打架
const darkOverrides: GlobalThemeOverrides = {
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

// 浅色：底色/文字交给 Naive 的浅色主题，这里只统一主色，免得两套调色板互相盖
const lightOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#6b5ae0',
    primaryColorHover: '#7d6df0',
    primaryColorPressed: '#5a49c8',
    primaryColorSuppl: '#7d6df0',
    bodyColor: '#f4f5f8',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    popoverColor: '#ffffff',
    textColorBase: '#1f2430',
  },
}

const overrides = computed(() => (ui.theme === 'dark' ? darkOverrides : lightOverrides))
</script>

<template>
  <!-- locale 必须是中文：否则 Naive 内置文案（确认/取消、空状态、分页等）全是英文 -->
  <n-config-provider
    :theme="ui.theme === 'dark' ? darkTheme : null"
    :theme-overrides="overrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
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
