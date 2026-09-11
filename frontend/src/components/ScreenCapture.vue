<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NModal, NSelect, NSpin, useMessage } from 'naive-ui'
import { engine } from '../api/client'
import type { WindowInfo } from '../types'

const props = defineProps<{ show: boolean; mode?: 'region' | 'point'; initialWindow?: number | null }>()
const emit = defineEmits<{
  (e: 'captured', id: string): void
  (e: 'picked', x: number, y: number): void
  (e: 'cancel'): void
}>()

const message = useMessage()
const image = ref('')
const loading = ref(false)
const windows = ref<WindowInfo[]>([])
const selectedWindow = ref<number | null>(null)
const imgEl = ref<HTMLImageElement | null>(null)
const stageEl = ref<HTMLDivElement | null>(null)

const start = ref<{ x: number; y: number } | null>(null)
const current = ref<{ x: number; y: number } | null>(null)
const dragging = ref(false)
const point = ref<{ x: number; y: number } | null>(null)
const error = ref('')

const winOptions = computed(() => [
  { label: '🖥 全屏', value: 0 },
  ...windows.value.map((w) => ({ label: w.title.slice(0, 40), value: w.hwnd })),
])

const selStyle = computed(() => {
  if (props.mode !== 'region' || !start.value || !current.value) return { display: 'none' }
  const x = Math.min(start.value.x, current.value.x)
  const y = Math.min(start.value.y, current.value.y)
  const w = Math.abs(current.value.x - start.value.x)
  const h = Math.abs(current.value.y - start.value.y)
  return { left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px' }
})

const pointStyle = computed(() => {
  if (props.mode !== 'point' || !point.value) return { display: 'none' }
  return { left: point.value.x - 6 + 'px', top: point.value.y - 6 + 'px' }
})

async function loadWindows() {
  try {
    const r = await engine.listWindows()
    windows.value = r.windows
  } catch (e: any) {
    message.error('获取窗口列表失败：' + e.message)
  }
}

async function capture() {
  loading.value = true
  error.value = ''
  start.value = null
  current.value = null
  point.value = null
  try {
    const win = selectedWindow.value || null
    const r = await engine.screenshot(win)
    image.value = r.image
  } catch (e: any) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function onWindowChange(v: number) {
  selectedWindow.value = v
  capture()
}

watch(
  () => props.show,
  async (v) => {
    if (v) {
      selectedWindow.value = props.initialWindow ?? 0
      await loadWindows()
      await capture()
    }
  },
)

function toLocal(e: PointerEvent) {
  const rect = stageEl.value!.getBoundingClientRect()
  return { x: e.clientX - rect.left, y: e.clientY - rect.top }
}
function onDown(e: PointerEvent) {
  dragging.value = true
  start.value = toLocal(e)
  current.value = start.value
}
function onMove(e: PointerEvent) {
  if (!dragging.value) return
  current.value = toLocal(e)
}
function onUp() {
  if (!dragging.value) return
  dragging.value = false
  if (props.mode === 'point' && start.value) {
    pickPoint(start.value)
  }
}

function localToScreen(localX: number, localY: number) {
  const img = imgEl.value!
  const scaleX = img.naturalWidth / img.clientWidth
  const scaleY = img.naturalHeight / img.clientHeight
  const px = Math.round(localX * scaleX)
  const py = Math.round(localY * scaleY)
  const win = windows.value.find((w) => w.hwnd === selectedWindow.value)
  if (win) {
    return { x: win.rect.left + px, y: win.rect.top + py }
  }
  return { x: px, y: py }
}

function pickPoint(local: { x: number; y: number }) {
  const { x, y } = localToScreen(local.x, local.y)
  point.value = { x: local.x, y: local.y }
  emit('picked', x, y)
  message.success(`已拾取坐标 (${x}, ${y})`)
}

async function confirmRegion() {
  if (!start.value || !current.value || !imgEl.value) return
  const sx = Math.min(start.value.x, current.value.x)
  const sy = Math.min(start.value.y, current.value.y)
  const sw = Math.abs(current.value.x - start.value.x)
  const sh = Math.abs(current.value.y - start.value.y)
  if (sw < 4 || sh < 4) {
    message.warning('选区太小，请重新框选')
    return
  }
  const scaleX = imgEl.value.naturalWidth / imgEl.value.clientWidth
  const scaleY = imgEl.value.naturalHeight / imgEl.value.clientHeight
  const nx = Math.round(sx * scaleX)
  const ny = Math.round(sy * scaleY)
  const nw = Math.round(sw * scaleX)
  const nh = Math.round(sh * scaleY)

  const canvas = document.createElement('canvas')
  canvas.width = nw
  canvas.height = nh
  const ctx = canvas.getContext('2d')!
  ctx.drawImage(imgEl.value, nx, ny, nw, nh, 0, 0, nw, nh)
  const dataUrl = canvas.toDataURL('image/png')
  try {
    const r = await engine.captureTemplate(dataUrl)
    message.success('模板已保存：' + r.id)
    emit('captured', r.id)
  } catch (e: any) {
    message.error('保存模板失败：' + e.message)
  }
}
</script>

<template>
  <n-modal
    :show="show"
    preset="card"
    :title="mode === 'point' ? '拾取屏幕坐标' : '截取识别模板'"
    style="width: min(940px, 94vw)"
    :mask-closable="false"
    @update:show="(v: boolean) => !v && emit('cancel')"
  >
    <div class="cap-body">
      <div class="cap-bar">
        <span class="cap-tip">
          {{ mode === 'point' ? '选择目标窗口后，点击截图中要拾取的点' : '选择目标窗口后，框选出要识别的区域' }}
        </span>
        <div class="win-sel">
          <n-select
            :value="selectedWindow"
            :options="winOptions"
            size="small"
            style="width: 260px"
            placeholder="选择窗口"
            @update:value="onWindowChange"
          />
          <n-button size="small" @click="loadWindows">刷新窗口</n-button>
        </div>
      </div>
      <div v-if="loading" class="cap-loading">
        <n-spin size="large" />
        <span>正在截取…</span>
      </div>
      <div v-else-if="error" class="cap-loading">
        <span class="cap-error">截图失败：{{ error }}</span>
        <n-button size="small" @click="capture">重试</n-button>
      </div>
      <div
        v-else
        ref="stageEl"
        class="cap-stage"
        :class="{ 'point-mode': mode === 'point' }"
        @pointerdown="onDown"
        @pointermove="onMove"
        @pointerup="onUp"
      >
        <img ref="imgEl" :src="image" alt="screenshot" draggable="false" />
        <div v-if="mode === 'region'" class="cap-sel" :style="selStyle" />
        <div v-if="mode === 'point'" class="cap-point" :style="pointStyle" />
      </div>
    </div>
    <template #footer>
      <div class="cap-footer">
        <n-button @click="emit('cancel')">取消</n-button>
        <n-button v-if="mode === 'region'" type="primary" @click="confirmRegion">保存模板</n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.cap-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cap-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.cap-tip {
  color: var(--text-dim);
  font-size: 13px;
}
.win-sel {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cap-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 60px 0;
  color: var(--text-dim);
}
.cap-error {
  color: var(--danger);
}
.cap-stage {
  position: relative;
  overflow: auto;
  max-height: 60vh;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #000;
  cursor: crosshair;
  user-select: none;
  touch-action: none;
}
.cap-stage img {
  display: block;
  max-width: 100%;
  height: auto;
}
.cap-sel {
  position: absolute;
  border: 2px dashed #fff;
  background: rgba(124, 108, 240, 0.25);
  box-sizing: border-box;
  pointer-events: none;
}
.cap-point {
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid #fff;
  background: #ef4444;
  pointer-events: none;
}
.cap-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
