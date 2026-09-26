<script setup lang="ts">
/**
 * 设定面板：目前是「自定义背景」。
 *
 * 选图 → 截取（按当前窗口比例）→ 透明度，三步都在这里完成。
 * 图片只存本机浏览器（localStorage），不上传引擎、不写进 .agflow。
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NButton, NModal, NSlider, useMessage } from 'naive-ui'
import { useUiStore } from '../stores/ui'
import { clampPan, drawRect, outputSize } from '../lib/bgCrop'

const show = defineModel<boolean>('show', { default: false })
const ui = useUiStore()
const message = useMessage()

// ---------- 选图 ----------
const fileInput = ref<HTMLInputElement | null>(null)
// 正在裁剪的原图（data URL）；为空表示停留在"设置列表"视图
const draft = ref('')
const draftName = ref('')

function pickFile() {
  fileInput.value?.click()
}

function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    message.error('请选择图片文件（png / jpg / webp 等）')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const url = String(reader.result || '')
    // 必须先拿到图片的原始像素尺寸，覆盖缩放才能算对
    const im = new Image()
    im.onload = () => {
      imgW.value = im.naturalWidth
      imgH.value = im.naturalHeight
      draft.value = url
      draftName.value = file.name
      resetCrop()
      nextTick(() => measure())
    }
    im.onerror = () => message.error('图片解码失败')
    im.src = url
  }
  reader.onerror = () => message.error('图片读取失败')
  reader.readAsDataURL(file)
}

// ---------- 截取（按窗口比例，所见即所得） ----------
// 几何计算全在 lib/bgCrop.ts（纯函数、有断言覆盖）：界面显示与 canvas 导出
// 共用同一份 drawRect()，所以"看到的"和"存下的"严格一致。
const frameW = ref(0)
const frameH = ref(0)
const imgW = ref(0)
const imgH = ref(0)
const zoom = ref(1)
const pan = ref({ x: 0, y: 0 })
const dragging = ref(false)
let dragFrom = { x: 0, y: 0, tx: 0, ty: 0 }

/** 目标比例 = 当前窗口比例（"适配屏幕"就是适配它） */
function targetAspect() {
  const w = window.innerWidth || 1600
  const h = window.innerHeight || 900
  return w / h
}

const frame = () => ({ w: frameW.value, h: frameH.value })
const src = () => ({ w: imgW.value, h: imgH.value })

/** 量出取景框尺寸：在可用宽高内按窗口比例取最大矩形 */
function measure() {
  const el = document.getElementById('agt-crop-frame')
  if (!el || !imgW.value) return
  const availW = (el.parentElement?.clientWidth || 660) - 2
  const maxH = Math.max(160, Math.round(window.innerHeight * 0.46))
  const ar = targetAspect()
  let w = Math.max(200, availW)
  let h = w / ar
  if (h > maxH) {
    h = maxH
    w = h * ar
  }
  frameW.value = Math.round(w)
  frameH.value = Math.round(h)
  pan.value = clampPan(frame(), src(), zoom.value, pan.value)
}

/** 图片在取景框里的位置与尺寸（CSS 像素） */
function imgStyle() {
  const r = drawRect(frame(), src(), zoom.value, pan.value)
  return {
    width: `${r.w}px`,
    height: `${r.h}px`,
    left: `${r.x}px`,
    top: `${r.y}px`,
  }
}

function resetCrop() {
  zoom.value = 1
  pan.value = { x: 0, y: 0 }
}

function onZoom(v: number) {
  zoom.value = v
  pan.value = clampPan(frame(), src(), zoom.value, pan.value)
}

function onDown(e: MouseEvent) {
  dragging.value = true
  dragFrom = { x: e.clientX, y: e.clientY, tx: pan.value.x, ty: pan.value.y }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
function onMove(e: MouseEvent) {
  if (!dragging.value) return
  pan.value = clampPan(frame(), src(), zoom.value, {
    x: dragFrom.tx + (e.clientX - dragFrom.x),
    y: dragFrom.ty + (e.clientY - dragFrom.y),
  })
}
function onUp() {
  dragging.value = false
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
}

function cancelCrop() {
  draft.value = ''
  draftName.value = ''
}

/** 把「框里看到的那块」按同一组参数画到 canvas 上导出 */
async function confirmCrop() {
  if (!draft.value || !frameW.value) return
  const img = new Image()
  const okLoad = await new Promise<boolean>((res) => {
    img.onload = () => res(true)
    img.onerror = () => res(false)
    img.src = draft.value
  })
  if (!okLoad) {
    message.error('图片解码失败')
    return
  }

  // 输出分辨率跟随屏幕（含 DPR），但限制总量，免得 base64 太大塞不进 localStorage
  const out = outputSize(frame(), window.devicePixelRatio || 1)
  const outW = out.w
  const outH = out.h

  const r = drawRect(frame(), src(), zoom.value, pan.value)
  const k = outW / frameW.value

  const cv = document.createElement('canvas')
  cv.width = outW
  cv.height = outH
  const ctx = cv.getContext('2d')
  if (!ctx) {
    message.error('当前浏览器不支持画布导出')
    return
  }
  ctx.fillStyle = '#0e1116'
  ctx.fillRect(0, 0, outW, outH)
  ctx.drawImage(img, r.x * k, r.y * k, r.w * k, r.h * k)

  // 先按较高质量导出；存不下就逐步降质（localStorage 一般只有 ~5MB）
  for (const q of [0.88, 0.75, 0.6, 0.45]) {
    const url = cv.toDataURL('image/jpeg', q)
    if (ui.applyImage(url)) {
      message.success(`背景已应用（${outW}×${outH}）`)
      cancelCrop()
      return
    }
  }
  // 四档都存不下：本次仍然生效（内存里可用），但明确告知无法持久化
  ui.applyImage(cv.toDataURL('image/jpeg', 0.45))
  message.warning('背景已临时应用，但本机存储空间不足，重启后会丢失')
  cancelCrop()
}

watch(show, (v) => {
  if (v) nextTick(() => measure())
  else cancelCrop()
})
window.addEventListener('resize', measure)
onBeforeUnmount(() => {
  window.removeEventListener('resize', measure)
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
})
</script>

<template>
  <n-modal
    v-model:show="show"
    preset="card"
    :title="draft ? '截取背景图（按当前窗口比例）' : '设定'"
    style="width: 720px; max-width: calc(100vw - 32px)"
  >
    <!-- ============ 截取视图 ============ -->
    <template v-if="draft">
      <p class="hint">
        拖动图片调整位置，用滑块缩放。框内看到的就是最终效果（按当前窗口比例
        {{ frameW }}×{{ frameH }}）。
      </p>
      <div
        id="agt-crop-frame"
        class="crop-frame"
        :style="{ width: frameW + 'px', height: frameH + 'px' }"
        @mousedown="onDown"
      >
        <img :src="draft" :style="imgStyle()" draggable="false" alt="待截取图片" />
        <div class="crop-grid" />
      </div>
      <div class="crop-bar">
        <span class="lbl">缩放</span>
        <n-slider :value="zoom" :min="1" :max="3" :step="0.01" style="width: 240px" @update:value="onZoom" />
        <n-button size="small" @click="resetCrop">居中适应</n-button>
        <span class="file-name">{{ draftName }}</span>
      </div>
      <div class="actions">
        <n-button @click="cancelCrop">取消</n-button>
        <n-button type="primary" @click="confirmCrop">确定并应用</n-button>
      </div>
    </template>

    <!-- ============ 设置视图 ============ -->
    <template v-else>
      <div class="sect">
        <div class="sect-title">🖼 自定义背景</div>
        <p class="hint">
          选一张本地图片，截取成屏幕比例后作为整个界面的背景。图片只保存在<b>本机浏览器</b>里，
          不会写进 <code>.agflow</code>，也不会上传到引擎。
        </p>

        <div class="row">
          <n-button type="primary" @click="pickFile">
            {{ ui.bgImage ? '更换图片' : '选择本地图片' }}
          </n-button>
          <n-button v-if="ui.bgImage" @click="ui.clearBackground()">清除背景</n-button>
          <input ref="fileInput" type="file" accept="image/*" style="display: none" @change="onFile" />
        </div>

        <div v-if="ui.bgImage" class="preview">
          <div class="preview-img" :style="{ backgroundImage: `url(${ui.bgImage})` }" />
          <div class="preview-meta">已设置背景</div>
        </div>

        <div class="row">
          <span class="lbl">透明度</span>
          <n-slider
            :value="Math.round(ui.bgOpacity * 100)"
            :min="5"
            :max="100"
            :step="1"
            style="width: 260px"
            :disabled="!ui.bgImage"
            @update:value="(v: number) => ui.setOpacity(v / 100)"
          />
          <span class="pct">{{ Math.round(ui.bgOpacity * 100) }}%</span>
        </div>
        <p class="hint">
          透明度越高背景越显眼；面板与画布始终保留一层暗色底，保证文字和连线可读。
        </p>
        <p v-if="ui.bgWarn" class="warn">{{ ui.bgWarn }}</p>
      </div>

      <div class="actions">
        <n-button type="primary" @click="show = false">完成</n-button>
      </div>
    </template>
  </n-modal>
</template>

<style scoped>
.hint {
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.7;
  margin: 0 0 10px;
}
.hint code {
  background: var(--bg-panel);
  padding: 1px 4px;
  border-radius: 4px;
}
.sect-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px 0;
}
.lbl {
  color: var(--text-dim);
  font-size: 12px;
  white-space: nowrap;
}
.pct {
  font-size: 12px;
  color: var(--text-dim);
  width: 40px;
}
.preview {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 10px 0;
}
.preview-img {
  width: 160px;
  height: 90px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background-size: cover;
  background-position: center;
}
.preview-meta {
  font-size: 12px;
  color: var(--text-dim);
}
.warn {
  color: var(--warn);
  font-size: 12px;
  margin: 8px 0 0;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

/* ---- 取景框 ---- */
.crop-frame {
  position: relative;
  margin: 0 auto;
  overflow: hidden;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: #0b0e13;
  cursor: grab;
  user-select: none;
}
.crop-frame:active {
  cursor: grabbing;
}
.crop-frame img {
  position: absolute;
  max-width: none;
  pointer-events: none;
}
/* 三分线：给"截取"一点取景参考 */
.crop-grid {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(to right, transparent 33.2%, rgba(255, 255, 255, 0.14) 33.3%, transparent 33.4%),
    linear-gradient(to right, transparent 66.5%, rgba(255, 255, 255, 0.14) 66.6%, transparent 66.7%),
    linear-gradient(to bottom, transparent 33.2%, rgba(255, 255, 255, 0.14) 33.3%, transparent 33.4%),
    linear-gradient(to bottom, transparent 66.5%, rgba(255, 255, 255, 0.14) 66.6%, transparent 66.7%);
}
.crop-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}
.file-name {
  font-size: 12px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
