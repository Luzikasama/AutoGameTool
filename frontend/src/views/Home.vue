<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag } from 'naive-ui'
import { engine } from '../api/client'

const router = useRouter()
const status = ref<'checking' | 'online' | 'offline'>('checking')

const features = [
  { icon: '🎯', title: '图像识别', desc: '截图框选模板，OpenCV 精准匹配' },
  { icon: '🖱', title: '键鼠控制', desc: '鼠标点击、键盘按键、文本输入' },
  { icon: '🧩', title: '零代码编排', desc: '拖拽节点，连线即成流程' },
  { icon: '🛡', title: '异常退出', desc: '超时告警、手动急停、流程守护' },
]

onMounted(async () => {
  try {
    await engine.health()
    status.value = 'online'
  } catch {
    status.value = 'offline'
  }
})
</script>

<template>
  <div class="home">
    <div class="hero">
      <div class="logo">🎮</div>
      <h1>AutoGameTool</h1>
      <p class="slogan">轻量级游戏自动化脚本工具 · 零代码 · 可视化</p>
      <div class="status-row">
        <n-tag :type="status === 'online' ? 'success' : status === 'offline' ? 'error' : 'default'" size="small" round>
          引擎{{ status === 'online' ? '已连接' : status === 'offline' ? '未连接' : '检测中…' }}
        </n-tag>
      </div>
      <div class="cta">
        <n-button type="primary" size="large" @click="router.push('/editor')">新建脚本</n-button>
        <n-button size="large" :disabled="status !== 'online'" @click="router.push('/editor')">
          进入编辑器
        </n-button>
      </div>
    </div>

    <div class="features">
      <div v-for="f in features" :key="f.title" class="feature-card">
        <div class="feature-icon">{{ f.icon }}</div>
        <div class="feature-title">{{ f.title }}</div>
        <div class="feature-desc">{{ f.desc }}</div>
      </div>
    </div>

    <footer class="foot">AutoGameTool · Windows 优先 · 本地引擎 + Tauri 桌面壳</footer>
  </div>
</template>

<style scoped>
.home {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 40px;
  padding: 48px 24px;
}
.hero {
  text-align: center;
}
.logo {
  font-size: 64px;
  filter: drop-shadow(0 4px 20px rgba(124, 108, 240, 0.5));
}
h1 {
  margin: 12px 0 4px;
  font-size: 40px;
  font-weight: 700;
  letter-spacing: -0.5px;
  background: linear-gradient(120deg, #a5b4fc, #7c6cf0, #22d3ee);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.slogan {
  margin: 0;
  color: var(--text-dim);
  font-size: 15px;
}
.status-row {
  margin: 14px 0 22px;
  display: flex;
  justify-content: center;
}
.cta {
  display: flex;
  gap: 12px;
  justify-content: center;
}
.features {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  max-width: 900px;
  width: 100%;
}
.feature-card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  text-align: center;
}
.feature-icon {
  font-size: 30px;
}
.feature-title {
  font-weight: 600;
  margin: 8px 0 4px;
}
.feature-desc {
  color: var(--text-dim);
  font-size: 12px;
}
.foot {
  color: var(--text-dim);
  font-size: 12px;
}
@media (max-width: 760px) {
  .features {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
