<script setup lang="ts">
/**
 * 设定面板（0.1.2 重做）：左侧分组导航 + 右侧卡片式设置行。
 *
 * 为什么重做布局：原来所有分节（外观 / 背景 / 快捷键）竖着堆在一个滚动条里，
 * 内容一多就要一路往下翻才能找到想改的那一项；分组导航把「找设置」变成点一下。
 *
 * 分四组 + 关于：
 *   通用     —— 主题、运行状态悬浮框
 *   外观     —— 自定义背景（选图 → 截取 → 透明度，三步都在这）
 *   快捷键   —— 引擎侧全局快捷键（改键 / 单独停用）
 *   数据管理 —— 本机数据，说明什么存在本机、什么写进脚本
 *   关于     —— 版本、运行形态、连接状态、仓库与发布页
 *
 * 「关于」0.1.2 起从顶栏搬到这里：它是"看一次就够"的信息，放顶栏白占一个按钮位。
 *
 * 数据归属（改动这里时别搞混）：
 *  · 主题与背景图 → 本机浏览器 localStorage，不上传引擎、不写进 .agflow
 *    （换台机器打开同一个脚本不该跟着变样；图片是几十~几百 KB 的 base64，走 HTTP 每次都传不划算）
 *  · 全局快捷键   → 引擎的 config.json，因为全局钩子在引擎进程里
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NButton, NModal, NRadioButton, NRadioGroup, NSlider, NSwitch, useMessage } from 'naive-ui'
import { engine, type HotkeyBinding } from '../api/client'
import { useUiStore } from '../stores/ui'
import { useEngineStore } from '../stores/engine'
import { APPEARANCE_OPTIONS, appearanceLabel } from '../lib/appearance'
import { clampPan, drawRect, outputSize } from '../lib/bgCrop'

const show = defineModel<boolean>('show', { default: false })
const ui = useUiStore()
const eng = useEngineStore()
const message = useMessage()

// ---------- 左侧导航 ----------
type NavKey = 'general' | 'appearance' | 'hotkeys' | 'data' | 'about'

const NAV_GROUPS: { title?: string; items: { key: NavKey; label: string; icon: string }[] }[] = [
  {
    items: [
      { key: 'general', label: '通用', icon: '⚙' },
      { key: 'appearance', label: '外观', icon: '🎨' },
      { key: 'hotkeys', label: '快捷键', icon: '⌨' },
    ],
  },
  {
    title: '数据与安全',
    items: [{ key: 'data', label: '数据管理', icon: '🗄' }],
  },
]

/** 「关于」单列在最下面（与上面隔一条线）：它不是日常会改的设置 */
const ABOUT_ITEM: { key: NavKey; label: string; icon: string } = {
  key: 'about',
  label: '关于',
  icon: 'ⓘ',
}

const NAV_TITLES: Record<NavKey, string> = {
  general: '通用',
  appearance: '外观',
  hotkeys: '快捷键',
  data: '数据管理',
  about: '关于',
}

/** 当前设置行所在的右栏文本，标题栏显示（截图里顶部那行大字） */
const NAV_HINT: Record<NavKey, string> = {
  general: '界面主题与运行时的显示方式',
  appearance: '自定义背景图的选图与透明度',
  hotkeys: '全局快捷键在本机生效，任何时候都能用',
  data: '本机保存了什么、脚本文件里有什么',
  about: '版本信息与项目链接',
}

const nav = ref<NavKey>('general')

/** 切换分页 = 放弃正在进行的截取（否则换了页还留着半截裁剪状态） */
function selectNav(k: NavKey) {
  if (draft.value) cancelCrop()
  nav.value = k
}

// ---------- 「关于」用到的常量 ----------
const REPO_URL = 'https://github.com/Luzikasama/AutoTool'
const RELEASES_URL = `${REPO_URL}/releases`

/** 用系统默认浏览器打开外链。
 *
 *  交给引擎做而不是 window.open：桌面壳里的 window.open 会开出一个没有地址栏、
 *  没有前进/后退的 Tauri 子窗口，GitHub 页面在里面很难用。
 *  引擎不可达时（纯前端开发模式）退回 window.open，至少还能打开。
 */
async function openUrl(url: string) {
  try {
    await engine.openExternal(url)
  } catch {
    window.open(url, '_blank')
  }
}

// ---------- 通用 ----------
async function onToggleOverlay(v: boolean) {
  try {
    const on = await eng.toggleOverlay()
    if (on !== v) message.info(`悬浮框已${on ? '开启' : '关闭'}`)
  } catch (e: any) {
    message.error('切换悬浮框失败：' + (e?.message || e))
  }
}

// ---------- 数据管理 ----------
/** 背景图在 localStorage 里占的大小（base64 → 原始字节约 ×3/4） */
const bgSizeText = computed(() => {
  if (!ui.bgImage) return '未设置'
  const kb = Math.round((ui.bgImage.length * 3) / 4 / 1024)
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`
})

const themeText = computed(() => appearanceLabel(ui.appearance, ui.systemDark))

function resetLocalPrefs() {
  ui.clearBackground()
  ui.setAppearance('system')
  message.success('已恢复默认界面偏好（跟随系统 + 无背景）')
}

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
    :mask-closable="!draft"
    :auto-focus="false"
    class="st-modal"
    transform-origin="center"
  >
    <div class="st-panel">
      <!-- ============ 左侧分组导航 ============ -->
      <aside class="st-nav">
        <div class="st-nav-title">设置</div>
        <div class="st-nav-scroll">
          <template v-for="(g, gi) in NAV_GROUPS" :key="gi">
            <div v-if="g.title" class="st-group">{{ g.title }}</div>
            <button
              v-for="it in g.items"
              :key="it.key"
              type="button"
              class="st-item"
              :class="{ on: nav === it.key && !draft }"
              @click="selectNav(it.key)"
            >
              <span class="st-ico">{{ it.icon }}</span>
              <span class="st-label">{{ it.label }}</span>
            </button>
          </template>
        </div>
        <div class="st-nav-foot">
          <button
            type="button"
            class="st-item"
            :class="{ on: nav === ABOUT_ITEM.key && !draft }"
            @click="selectNav(ABOUT_ITEM.key)"
          >
            <span class="st-ico">{{ ABOUT_ITEM.icon }}</span>
            <span class="st-label">{{ ABOUT_ITEM.label }}</span>
          </button>
        </div>
      </aside>

      <!-- ============ 右侧内容 ============ -->
      <section class="st-body">
        <header class="st-head">
          <div>
            <h2 class="st-h2">{{ draft ? '截取背景图' : NAV_TITLES[nav] }}</h2>
            <div class="st-sub">
              {{ draft ? '按当前窗口比例裁切，所见即所得' : NAV_HINT[nav] }}
            </div>
          </div>
          <button class="st-close" type="button" title="关闭" @click="show = false">×</button>
        </header>

        <div class="st-scroll">
          <!-- ---------------- 截取视图 ---------------- -->
          <template v-if="draft">
            <div class="st-group-label">取景</div>
            <div class="st-card">
              <div class="st-row col">
                <p class="st-note">
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
                  <span class="st-note">缩放</span>
                  <n-slider
                    :value="zoom"
                    :min="1"
                    :max="3"
                    :step="0.01"
                    style="width: 220px"
                    @update:value="onZoom"
                  />
                  <n-button size="small" @click="resetCrop">居中适应</n-button>
                  <span class="file-name">{{ draftName }}</span>
                </div>
              </div>
            </div>
            <div class="st-actions">
              <n-button @click="cancelCrop">取消</n-button>
              <n-button type="primary" @click="confirmCrop">确定并应用</n-button>
            </div>
          </template>

          <!-- ---------------- 通用 ---------------- -->
          <template v-else-if="nav === 'general'">
            <div class="st-group-label">常规</div>
            <div class="st-card">
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">界面主题</div>
                  <div class="st-row-desc">
                    深色是原来的外观；「跟随系统」会跟着 Windows 的浅色/深色设置走（默认）。
                    这个偏好只保存在本机浏览器里，不影响脚本文件。
                  </div>
                </div>
                <div class="st-row-ctl">
                  <n-radio-group
                    :value="ui.appearance"
                    size="small"
                    @update:value="ui.setAppearance"
                  >
                    <n-radio-button v-for="o in APPEARANCE_OPTIONS" :key="o.value" :value="o.value">
                      {{ o.label }}
                    </n-radio-button>
                  </n-radio-group>
                </div>
              </div>
            </div>

            <div class="st-group-label">运行</div>
            <div class="st-card">
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">运行状态悬浮框</div>
                  <div class="st-row-desc">
                    运行时在屏幕角落显示一个小的状态条（进度、暂停/停止按钮），方便切到游戏窗口后
                    还能操作。{{
                      eng.overlayAvailable
                        ? '开关会存进引擎配置，下次启动保持。'
                        : '当前系统上不可用（引擎未就绪或不支持）。'
                    }}
                  </div>
                </div>
                <div class="st-row-ctl">
                  <n-switch
                    :value="eng.overlayEnabled"
                    :disabled="!eng.overlayAvailable || !eng.connected"
                    size="small"
                    @update:value="onToggleOverlay"
                  />
                </div>
              </div>
            </div>
          </template>

          <!-- ---------------- 外观 ---------------- -->
          <template v-else-if="nav === 'appearance'">
            <div class="st-group-label">背景</div>
            <div class="st-card">
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">自定义背景</div>
                  <div class="st-row-desc">
                    选一张本地图片，截取成屏幕比例后作为整个界面的背景。图片只保存在<b>本机浏览器</b>里，
                    不会写进 <code>.agflow</code>，也不会上传到引擎。
                  </div>
                </div>
                <div class="st-row-ctl">
                  <n-button size="small" type="primary" @click="pickFile">
                    {{ ui.bgImage ? '更换图片' : '选择本地图片' }}
                  </n-button>
                  <n-button v-if="ui.bgImage" size="small" @click="ui.clearBackground()">
                    清除背景
                  </n-button>
                  <input
                    ref="fileInput"
                    type="file"
                    accept="image/*"
                    style="display: none"
                    @change="onFile"
                  />
                </div>
              </div>

              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">背景透明度</div>
                  <div class="st-row-desc">
                    透明度越高背景越显眼；面板与画布始终保留一层暗色底，保证文字和连线可读。
                  </div>
                </div>
                <div class="st-row-ctl">
                  <n-slider
                    :value="Math.round(ui.bgOpacity * 100)"
                    :min="5"
                    :max="100"
                    :step="1"
                    style="width: 200px"
                    :disabled="!ui.bgImage"
                    @update:value="(v: number) => ui.setOpacity(v / 100)"
                  />
                  <span class="pct">{{ Math.round(ui.bgOpacity * 100) }}%</span>
                </div>
              </div>

              <div v-if="ui.bgImage" class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">当前背景</div>
                  <div class="st-row-desc">已设置，本机占用 {{ bgSizeText }}</div>
                </div>
                <div class="st-row-ctl">
                  <div class="preview-img" :style="{ backgroundImage: `url(${ui.bgImage})` }" />
                </div>
              </div>
            </div>

            <div v-if="ui.bgWarn" class="st-card">
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title danger">保存失败</div>
                  <div class="st-row-desc">{{ ui.bgWarn }}</div>
                </div>
              </div>
            </div>

            <p class="st-tip">
              换了台电脑打开同一个脚本不会跟着变样 —— 因为背景根本不在脚本里。
            </p>
          </template>

          <!-- ---------------- 快捷键 ---------------- -->
          <template v-else-if="nav === 'hotkeys'">
            <div class="st-group-label">全局快捷键</div>
            <div class="st-card">
              <div v-for="b in bindings" :key="b.id" class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">{{ b.label }}</div>
                  <div class="st-row-desc">{{ b.enabled ? '已启用' : '已停用（仍可用界面上的按钮）' }}</div>
                </div>
                <div class="st-row-ctl hk-ctl">
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
                </div>
              </div>
              <div v-if="hotkeyLoaded && !bindings.length" class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">读不到快捷键</div>
                  <div class="st-row-desc">引擎未就绪，稍后重新打开本面板。</div>
                </div>
              </div>
            </div>

            <p class="st-tip">
              点中间那一栏后按下想要的组合键即可，支持 ctrl / alt / shift / win + 字母、数字、f1-f12。
              同一组按键不能给两个功能用，保存时引擎会校验并提示冲突。
            </p>

            <div class="st-actions">
              <n-button size="small" quaternary @click="restoreHotkeyDefaults">恢复默认</n-button>
              <n-button size="small" type="primary" @click="saveHotkeys">保存快捷键</n-button>
            </div>
          </template>

          <!-- ---------------- 数据管理 ---------------- -->
          <template v-else-if="nav === 'data'">
            <div class="st-group-label">本机保存的内容</div>
            <div class="st-card">
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">界面偏好</div>
                  <div class="st-row-desc">
                    主题与背景图存在这台电脑的浏览器里（localStorage），
                    换浏览器或清理浏览数据会丢。当前：{{ themeText }}
                  </div>
                </div>
                <div class="st-row-ctl">
                  <n-button size="small" @click="resetLocalPrefs">恢复默认</n-button>
                </div>
              </div>
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">背景图占用</div>
                  <div class="st-row-desc">浏览器给单个站点约 5 MB，超出会提示"保存失败"。</div>
                </div>
                <div class="st-row-ctl">
                  <span class="st-value">{{ bgSizeText }}</span>
                </div>
              </div>
            </div>

            <div class="st-group-label">脚本文件</div>
            <div class="st-card">
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">存在哪里</div>
                  <div class="st-row-desc">
                    脚本只在你点「保存」时写进你自己选的 <code>.agflow</code> 文件；
                    子脚本随父脚本一起写在这个文件里（子脚本不是单独的文件）。
                  </div>
                </div>
                <div class="st-row-ctl">
                  <span class="st-value">本地文件</span>
                </div>
              </div>
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">全局快捷键</div>
                  <div class="st-row-desc">
                    存在引擎的 <code>config.json</code>（hotkeys 字段），因为全局钩子在引擎进程里。
                  </div>
                </div>
                <div class="st-row-ctl">
                  <n-button size="small" quaternary @click="selectNav('hotkeys')">
                    去改键
                  </n-button>
                </div>
              </div>
            </div>
          </template>

          <!-- ---------------- 关于 ---------------- -->
          <template v-else>
            <div class="st-group-label">版本</div>
            <div class="st-card">
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">AutoTool</div>
                  <div class="st-row-desc">可视化流程编辑器 + 本机自动化引擎（图像识别 / 键鼠）。</div>
                </div>
                <div class="st-row-ctl">
                  <span class="st-value big">{{ eng.version || '—' }}</span>
                </div>
              </div>
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">运行形态</div>
                  <div class="st-row-desc">
                    {{ eng.desktop ? '桌面版（内置窗口，自动带起引擎）' : '浏览器版（在系统浏览器里打开）' }}
                  </div>
                </div>
                <div class="st-row-ctl">
                  <span class="st-value" :class="{ ok: eng.connected, bad: !eng.connected }">
                    {{ eng.connected ? '引擎已连接' : '引擎未连接' }}
                  </span>
                </div>
              </div>
            </div>

            <div class="st-group-label">链接</div>
            <div class="st-card">
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">项目主页</div>
                  <div class="st-row-desc">{{ REPO_URL }}</div>
                </div>
                <div class="st-row-ctl">
                  <n-button size="small" @click="openUrl(REPO_URL)">在浏览器打开</n-button>
                </div>
              </div>
              <div class="st-row">
                <div class="st-row-main">
                  <div class="st-row-title">下载新版本 / 更新日志</div>
                  <div class="st-row-desc">每次发布的说明与安装包、免安装版都在这里。</div>
                </div>
                <div class="st-row-ctl">
                  <n-button size="small" @click="openUrl(RELEASES_URL)">查看发布页</n-button>
                </div>
              </div>
            </div>

            <p class="st-tip">
              本项目使用的第三方开源组件与许可，见随包附带的 <code>THIRD-PARTY-NOTICES.md</code>。
            </p>
          </template>
        </div>

        <footer class="st-foot">
          <n-button size="small" type="primary" @click="show = false">完成</n-button>
        </footer>
      </section>
    </div>
  </n-modal>
</template>

<style scoped>
/* ---------- 外壳：左导航 + 右内容 ---------- */
.st-panel {
  display: flex;
  width: min(1020px, calc(100vw - 40px));
  height: min(760px, calc(100vh - 60px));
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: var(--shadow);
}

/* ---------- 左栏 ---------- */
.st-nav {
  flex: none;
  width: 216px;
  background: var(--bg-nav);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.st-nav-title {
  flex: none;
  padding: 16px 18px 8px;
  font-size: 13px;
  color: var(--text-dim);
  letter-spacing: 0.5px;
}
.st-nav-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 10px 10px;
}
/* 分组标题（功能 / 数据与安全…），比条目更淡更小 */
.st-group {
  font-size: 11px;
  color: var(--text-dim);
  padding: 12px 8px 4px;
}
.st-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: 0.13s;
}
.st-item:hover {
  background: var(--hover);
}
/* 当前分页：浅底 + 加粗（截图里就是这种"没描边、只换底色"的选中态） */
.st-item.on {
  background: var(--hover);
  font-weight: 600;
}
.st-ico {
  flex: none;
  width: 16px;
  text-align: center;
  opacity: 0.85;
}
.st-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 「关于」钉在最下面，与上面隔一条线 */
.st-nav-foot {
  flex: none;
  padding: 8px 10px 12px;
  border-top: 1px solid var(--border);
}

/* ---------- 右栏 ---------- */
.st-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.st-head {
  flex: none;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 22px 12px;
}
.st-h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}
.st-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-dim);
}
.st-close {
  flex: none;
  width: 26px;
  height: 26px;
  line-height: 24px;
  text-align: center;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--text-dim);
  font-size: 18px;
  cursor: pointer;
}
.st-close:hover {
  background: var(--hover);
  color: var(--text);
}
.st-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 22px 18px;
}
.st-foot {
  flex: none;
  display: flex;
  justify-content: flex-end;
  padding: 10px 22px 14px;
  border-top: 1px solid var(--border);
}

/* ---------- 卡片与设置行 ---------- */
.st-group-label {
  font-size: 12px;
  color: var(--text-dim);
  padding: 14px 2px 8px;
}
.st-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}
.st-card + .st-card {
  margin-top: 10px;
}
.st-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 13px 16px;
}
/* 行之间的细分隔线：用 + 而不是给每行加 border-bottom，最后一行就没有多余的一条 */
.st-row + .st-row {
  border-top: 1px solid var(--border);
}
/* 需要整行铺满内容时（例如取景框），不要左右两栏 */
.st-row.col {
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
}
.st-row-main {
  flex: 1;
  min-width: 0;
}
.st-row-title {
  font-size: 13.5px;
  font-weight: 500;
}
.st-row-title.danger {
  color: var(--danger);
}
.st-row-desc {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-dim);
}
.st-row-desc code {
  background: var(--bg);
  padding: 1px 4px;
  border-radius: 4px;
}
.st-row-ctl {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
}
.st-value {
  font-size: 13px;
  color: var(--text-dim);
}
.st-value.big {
  font-size: 15px;
  color: var(--text);
  font-family: 'Cascadia Code', Consolas, monospace;
}
.st-value.ok {
  color: var(--ok);
}
.st-value.bad {
  color: var(--warn);
}
.st-note {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-dim);
  margin: 0;
}
.st-tip {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-dim);
  margin: 12px 2px 0;
}
.st-tip code {
  background: var(--bg-card);
  padding: 1px 4px;
  border-radius: 4px;
}
.st-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}
.pct {
  font-size: 12px;
  color: var(--text-dim);
  width: 40px;
}
.preview-img {
  width: 132px;
  height: 74px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background-size: cover;
  background-position: center;
}

/* ---- 全局快捷键：键位显示区本身就是「录制」按钮，省掉一个按钮 ---- */
.hk-ctl {
  gap: 10px;
}
.hk-keys {
  width: 190px;
  text-align: left;
  padding: 5px 10px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--bg);
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
