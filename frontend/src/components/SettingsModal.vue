<script setup lang="ts">
/**
 * 设定面板：外观（浅色 / 深色 / 跟随系统）+ 自定义背景 + 全局快捷键。
 *
 * 选图 → 截取（按当前窗口比例）→ 透明度，三步都在这里完成。
 * 图片与外观偏好只存本机浏览器（localStorage），不上传引擎、不写进 .agflow。
 * 快捷键存在引擎的 config.json（hotkeys 字段），因为全局钩子在引擎侧。
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NButton, NModal, NRadioButton, NRadioGroup, NSlider, NSwitch, useMessage } from 'naive-ui'
import { engine, type HotkeyBinding } from '../api/client'
import { useUiStore } from '../stores/ui'
import { APPEARANCE_OPTIONS, appearanceLabel } from '../lib/appearance'
import { clampPan, drawRect, outputSize } from '../lib/bgCrop'

const show = defineModel<boolean>('show', { default: false })
const ui = useUiStore()
const message = useMessage()

// ---------- 全局快捷键 ----------
// 从顶栏搬过来的：改键属于"设定一次就不动"的操作，放顶栏会挤掉常用按钮。
const bindings = ref<HotkeyBinding[]>([])
const hotkeyDefaults = ref<HotkeyBinding[]>([])
/** 正在录制按键的那条绑定 id；空串表示没在录 */
const recordingId = ref('')
const hotkeyLoaded = ref(false)

const KEY_ALIAS: Record<string, string> = {
  arrowup: 'up',
  arrowdown: 'down',
  arrowleft: 'left',
  arrowright: 'right',
  escape: 'esc',
  return: 'enter',
  del: 'delete',
  control: 'ctrl',
  meta: 'win',
}

/** 显示用的按键文本：alt + f1 */
function keysText(keys: string[]) {
  return (keys || []).join(' + ') || '（未设置）'
}

async function loadHotkeys() {
  try {
    const r = await engine.getHotkeys()
    bindings.value = r.bindings || []
    hotkeyDefaults.value = r.defaults || []
    hotkeyLoaded.value = true
  } catch {
    /* 引擎不可达时留空（下次打开面板再取） */
  }
}

async function saveHotkeys() {
  try {
    const r = await engine.setHotkeys(bindings.value)
    bindings.value = r.bindings || []
    message.success('快捷键已保存')
  } catch (e: any) {
    message.error('保存快捷键失败：' + e.message)
  }
}

function restoreHotkeyDefaults() {
  bindings.value = hotkeyDefaults.value.map((b) => ({ ...b, keys: [...b.keys] }))
  message.info('已填回默认快捷键，点「保存快捷键」后生效')
}

function startRecord(id: string) {
  if (recordingId.value === id) {
    finishRecord()
    return
  }
  recordingId.value = id
  window.addEventListener('keydown', onRecordKey)
}

/** 录制一次按键组合。
 *
 *  直接看这次事件的修饰键状态，而不是像旧实现那样「按到修饰键先攒起来、等主键再收尾」：
 *  后者在用户先松修饰键再按主键、或者一次按到位时都容易攒出错的组合。
 */
function onRecordKey(e: KeyboardEvent) {
  e.preventDefault()
  e.stopPropagation()
  const k = e.key.toLowerCase()
  const mods: string[] = []
  if (e.ctrlKey) mods.push('ctrl')
  if (e.altKey) mods.push('alt')
  if (e.shiftKey) mods.push('shift')
  if (e.metaKey) mods.push('win')
  // 只按下修饰键：等主键，不结束录制
  if (['control', 'alt', 'shift', 'meta'].includes(k)) return
  const main = k === ' ' ? 'space' : KEY_ALIAS[k] || k
  const b = bindings.value.find((x) => x.id === recordingId.value)
  if (b) {
    b.keys = [...mods, main]
    b.enabled = true
  }
  finishRecord()
}

function finishRecord() {
  recordingId.value = ''
  window.removeEventListener('keydown', onRecordKey)
}

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
      nextTick(() => {
        measure()
        observeBody()
      })
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

/** 量出取景框尺寸：在弹窗**内容盒**内按窗口比例取最大的矩形。
 *
 *  这里必须用「内容盒」而不是 `clientWidth`：`clientWidth` 是**含 padding** 的宽度，
 *  拿它当可用宽度会让取景框比弹窗里的标题/说明/按钮宽出去一圈（padding 那 ~24px），
 *  看起来就是「图片/取景框超出了选择框」——实测弹窗宽 720 时取景框做到了 718，
 *  而正文内容盒只有 ~670。
 *
 *  高度同时受两条约束：既不超过窗口的 46%，也要保证「取景框 + 标题/说明/按钮」
 *  整块能装进窗口（否则弹窗自己被截断）。
 */
function measure() {
  const el = document.getElementById('agt-crop-frame')
  if (!el || !imgW.value) return
  const body = el.parentElement
  let availW = 660
  if (body) {
    const cs = getComputedStyle(body)
    const padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0)
    availW = body.clientWidth - padX
  }
  availW = Math.max(200, availW - 2)
  const maxH = Math.max(
    140,
    Math.min(Math.round(window.innerHeight * 0.46), window.innerHeight - 300),
  )
  const ar = targetAspect()
  let w = availW
  let h = w / ar
  if (h > maxH) {
    h = maxH
    w = h * ar
  }
  frameW.value = Math.round(w)
  frameH.value = Math.round(h)
  pan.value = clampPan(frame(), src(), zoom.value, pan.value)
}

/** 监听弹窗内容盒尺寸变化（比只听 window.resize 可靠：
 *  弹窗打开动画、侧边栏折叠、面板拖拽都会改变它，而不一定触发 window resize） */
let bodyObserver: ResizeObserver | null = null

function observeBody() {
  try {
    const body = document.getElementById('agt-crop-frame')?.parentElement
    if (!body || typeof ResizeObserver === 'undefined') return
    bodyObserver?.disconnect()
    bodyObserver = new ResizeObserver(() => measure())
    bodyObserver.observe(body)
  } catch {
    /* 不支持就退回只监听 window.resize */
  }
}

function stopObserveBody() {
  try {
    bodyObserver?.disconnect()
  } catch {
    /* 忽略 */
  }
  bodyObserver = null
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
  stopObserveBody()
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
  if (v) {
    nextTick(() => measure())
    // 打开时拉一次快捷键（引擎侧是唯一事实来源；改键也在这里做）
    loadHotkeys()
  } else {
    cancelCrop()
    finishRecord()
  }
})
window.addEventListener('resize', measure)
onBeforeUnmount(() => {
  stopObserveBody()
  finishRecord()
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
        <div class="sect-title">🎨 外观</div>
        <p class="hint">
          深色是原来的外观；「跟随系统」会跟着 Windows 的浅色/深色设置走（默认）。
          这个偏好只保存在本机浏览器里，不影响脚本文件。
        </p>
        <div class="row">
          <n-radio-group :value="ui.appearance" size="small" @update:value="ui.setAppearance">
            <n-radio-button v-for="o in APPEARANCE_OPTIONS" :key="o.value" :value="o.value">
              {{ o.label }}
            </n-radio-button>
          </n-radio-group>
          <span v-if="ui.appearance === 'system'" class="lbl">
            当前：{{ appearanceLabel(ui.appearance, ui.systemDark) }}
          </span>
        </div>
      </div>

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

      <div class="sect">
        <div class="sect-title">⌨ 全局快捷键</div>
        <p class="hint">
          每条都能改键，也能单独停用（默认 alt+F1 启动 / 停止、alt+F2 键鼠录制、alt+F3 拾取坐标）。
          点中间那一栏后按下想要的组合键即可，支持 ctrl / alt / shift / win + 字母、数字、f1-f12。
        </p>
        <div v-for="b in bindings" :key="b.id" class="hk-row">
          <span class="hk-label">{{ b.label }}</span>
          <button
            class="hk-keys"
            type="button"
            :class="{ recording: recordingId === b.id, off: !b.enabled }"
            @click="startRecord(b.id)"
          >
            {{ recordingId === b.id ? '请按下组合键…' : keysText(b.keys) }}
          </button>
          <n-switch
            :value="b.enabled"
            size="small"
            @update:value="(v: boolean) => (b.enabled = v)"
          />
          <span class="hk-state">{{ b.enabled ? '启用' : '已停用' }}</span>
        </div>
        <p v-if="hotkeyLoaded && !bindings.length" class="hint">
          读不到快捷键（引擎未就绪），稍后重新打开本面板。
        </p>
        <p class="hint">
          同一组按键不能给两个功能用；保存时引擎会校验并提示冲突。
          停用的功能仍可用界面上的按钮（例如「开始录制」）。
        </p>
        <div class="row">
          <n-button size="small" quaternary @click="restoreHotkeyDefaults">恢复默认</n-button>
          <n-button size="small" type="primary" @click="saveHotkeys">保存快捷键</n-button>
        </div>
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

/* ---- 全局快捷键 ---- */
.hk-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 0;
}
.hk-label {
  width: 140px;
  flex: none;
  font-size: 13px;
}
/* 键位显示区本身就是「录制」按钮：点一下开始录，省掉一个按钮 */
.hk-keys {
  flex: 1;
  min-width: 0;
  text-align: left;
  padding: 5px 10px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--bg-panel);
  color: var(--text);
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 13px;
  cursor: pointer;
  transition: 0.15s;
}
.hk-keys:hover {
  border-color: var(--accent);
}
.hk-keys.recording {
  border-color: var(--accent);
  color: var(--accent);
}
.hk-keys.off {
  color: var(--text-dim);
  text-decoration: line-through;
}
.hk-state {
  width: 44px;
  flex: none;
  font-size: 12px;
  color: var(--text-dim);
}

/* 设置视图里各分节之间留出分隔（外观 / 背景 / …） */
.sect + .sect {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
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
