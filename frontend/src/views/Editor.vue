<script setup lang="ts">
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { VueFlow, type Connection } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import {
  NButton,
  NInput,
  NInputNumber,
  NModal,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSlider,
  NSwitch,
  NTooltip,
  useMessage,
} from 'naive-ui'
import StepNode from '../components/StepNode.vue'
import ScreenCapture from '../components/ScreenCapture.vue'
import { engine, engineWsUrl } from '../api/client'
import { useProjectStore } from '../stores/project'
import { STEP_META, type FlowFile, type StepType, type WindowInfo } from '../types'

const store = useProjectStore()
const message = useMessage()
const router = useRouter()

const nodeTypes: any = { step: markRaw(StepNode) }
const stepTypes = Object.entries(STEP_META) as Array<[StepType, { label: string; icon: string; color: string }]>

const nodes = ref<any[]>([])
const edges = ref<any[]>([])
const selectedId = ref<string | null>(null)
const templates = ref<{ label: string; value: string }[]>([])
const windows = ref<WindowInfo[]>([])
const selectedWinHwnd = ref<number>(0)

// 截图/拾取
const capVisible = ref(false)
const capMode = ref<'region' | 'point'>('region')

// 匹配结果
const matchVisible = ref(false)
const matchImage = ref('')
const pickingVisible = ref(false)
const mousePos = ref({ x: 0, y: 0 })
// 模板管理
const tplPreview = ref('')
const tplPreviewId = ref('')
const renameVisible = ref(false)
const renameText = ref('')
// 按键录制
const keyRecording = ref(false)
// 键鼠录制
const macroRecording = ref(false)

// 快捷键
const hotkeyVisible = ref(false)
const hotkeyText = ref('alt+f1')
const recording = ref(false)
const recordParts = ref<string[]>([])

// 缩放/平移实例
let vf: any = null

// 可缩放面板
const logHeight = ref(170)
const inspectorWidth = ref(280)

const logBody = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
let ws: WebSocket | null = null
let wsRetry: ReturnType<typeof setTimeout> | null = null
let wsFailCount = 0
let destroyed = false
let nodeSeq = 0

// 分辨率参考上下文：从加载的脚本文件中带出（坐标/模板均以此分辨率为基准），
// 新建脚本则使用当前分辨率。引擎运行时据此做跨分辨率坐标换算。
const fileScreen = ref<{ width: number; height: number } | null>(null)
const fileWindowRect = ref<WindowInfo['rect'] | null>(null)

function currentScreen() {
  const dpr = window.devicePixelRatio || 1
  return {
    width: Math.round(window.screen.width * dpr),
    height: Math.round(window.screen.height * dpr),
  }
}

function currentWindowRect(): WindowInfo['rect'] | null {
  if (!store.boundWindow) return null
  const w = windows.value.find((x) => x.hwnd === store.boundWindow!.hwnd)
  return w ? w.rect : null
}

function flowWindow() {
  if (!store.boundWindow) return null
  return {
    hwnd: store.boundWindow.hwnd,
    title: store.boundWindow.title,
    rect: fileWindowRect.value ?? currentWindowRect(),
  }
}

const selectedNode = computed(() => nodes.value.find((n) => n.id === selectedId.value) || null)

const winOptions = computed(() => [
  { label: '🌐 不绑定（全局）', value: 0 },
  ...windows.value.map((w) => ({ label: w.title.slice(0, 40), value: w.hwnd })),
])

const DEFAULTS: Record<StepType, Record<string, any>> = {
  delay: { ms: 1000 },
  find_image: { template: '', threshold: 0.85, timeout_ms: 5000, click: false, on_timeout: 'skip' },
  click: { x: 0, y: 0, button: 'left', clicks: 1 },
  key: { key: '' },
  text: { text: '' },
  judge: { template: '', threshold: 0.85, timeout_ms: 5000 },
  terminate: {},
  macro: { events: [], speed: 1.0 },
}

function metaOf(type: string) {
  return STEP_META[type as StepType] ?? { label: type, icon: '❓', color: '#888' }
}

// ---------- 画布控制 ----------
function onPaneReady(instance: any) {
  vf = instance
}
function zoomIn() {
  vf?.zoomIn()
}
function zoomOut() {
  vf?.zoomOut()
}
function fitView() {
  vf?.fitView({ padding: 0.2 })
}
function pan(dx: number, dy: number) {
  if (!vf) return
  const vp = vf.getViewport()
  vf.setViewport({ x: vp.x + dx, y: vp.y + dy, zoom: vp.zoom })
}

// ---------- 节点操作 ----------
function addStep(type: StepType) {
  const meta = STEP_META[type]
  const id = `n${++nodeSeq}`
  let pos = { x: 60, y: 80 }
  if (vf && typeof vf.screenToFlowCoordinate === 'function') {
    try {
      const p = vf.screenToFlowCoordinate({ x: mousePos.value.x, y: mousePos.value.y })
      if (p) pos = { x: Math.round(p.x), y: Math.round(p.y) }
    } catch {
      /* ignore */
    }
  }
  const node: any = {
    id,
    type: 'step',
    position: pos,
    data: { stepType: type, label: meta.label, params: { ...DEFAULTS[type] }, once: false },
  }
  nodes.value.push(node)
  selectedId.value = id
}

function onCanvasMove(e: MouseEvent) {
  mousePos.value = { x: e.clientX, y: e.clientY }
}

function removeSelected() {
  if (!selectedId.value) return
  const id = selectedId.value
  nodes.value = nodes.value.filter((n) => n.id !== id)
  edges.value = edges.value.filter((e) => e.source !== id && e.target !== id)
  selectedId.value = null
}

function onConnect(conn: Connection) {
  if (!conn.source || !conn.target) return
  if (edges.value.some((e) => e.source === conn.source && e.target === conn.target)) return
  edges.value.push({
    id: `e-${conn.source}-${conn.target}`,
    source: conn.source,
    target: conn.target,
    sourceHandle: (conn as any).sourceHandle || null,
  })
}

function onNodeClick({ node }: any) {
  selectedId.value = node.id
}

// ---------- 模板 / 坐标拾取 ----------
async function refreshTemplates() {
  try {
    const r = await engine.listTemplates()
    templates.value = r.templates.map((t) => ({ label: t.id, value: t.id }))
  } catch (e: any) {
    message.error('获取模板失败：' + e.message)
  }
}

function openCapture(mode: 'region' | 'point') {
  capMode.value = mode
  capVisible.value = true
}

async function onCaptured(tplId: string) {
  capVisible.value = false
  await refreshTemplates()
  const st = selectedNode.value?.data.stepType
  if (st === 'find_image' || st === 'judge') {
    selectedNode.value.data.params.template = tplId
    previewTemplate(tplId)
  }
}

function onPicked(x: number, y: number) {
  if (!pickingVisible.value) return
  pickingVisible.value = false
  if (selectedNode.value && selectedNode.value.data.stepType === 'click') {
    selectedNode.value.data.params.x = x
    selectedNode.value.data.params.y = y
    message.success(`已拾取坐标 (${x}, ${y})`)
  }
}

function startPicking() {
  pickingVisible.value = true
  engine.startPick().catch(() => {})
}

function cancelPicking() {
  pickingVisible.value = false
  engine.cancelPick().catch(() => {})
}

async function testMatch() {
  const node = selectedNode.value
  if (!node || node.data.stepType !== 'find_image') return
  if (!node.data.params.template) {
    message.warning('请先选择模板')
    return
  }
  try {
    const win = store.boundWindow?.hwnd ?? null
    const r = await engine.match(node.data.params.template, node.data.params.threshold, win)
    if (r.found) {
      message.success(`找到目标：(${r.x}, ${r.y})，相似度 ${(r.score * 100).toFixed(1)}%`)
      if (r.annotated) {
        matchImage.value = r.annotated
        matchVisible.value = true
      }
    } else {
      message.warning(`未找到（最高相似度 ${(r.score * 100).toFixed(1)}%）`)
    }
  } catch (e: any) {
    message.error('测试识别失败：' + e.message)
  }
}

// ---------- 模板管理 ----------
async function previewTemplate(id: string) {
  if (!id) {
    tplPreview.value = ''
    tplPreviewId.value = ''
    return
  }
  try {
    const r = await engine.templateImage(id)
    tplPreview.value = r.image
    tplPreviewId.value = id
  } catch (e: any) {
    tplPreview.value = ''
    tplPreviewId.value = ''
  }
}

function openRename() {
  const id = selectedNode.value?.data.params.template || tplPreviewId.value
  if (!id) return
  renameText.value = id
  renameVisible.value = true
}

async function doRename() {
  const id = selectedNode.value?.data.params.template || tplPreviewId.value
  if (!id || !renameText.value.trim()) return
  const newId = renameText.value.trim()
  try {
    const r = await engine.renameTemplate(id, newId)
    message.success('已重命名：' + r.id)
    renameVisible.value = false
    // 更新所有引用旧模板名的节点
    for (const n of nodes.value) {
      const st = n.data?.stepType
      if ((st === 'find_image' || st === 'judge') && n.data?.params?.template === id) {
        n.data.params.template = r.id
      }
    }
    await refreshTemplates()
    previewTemplate(r.id)
    loadFlowToEngine()
  } catch (e: any) {
    message.error('重命名失败：' + e.message)
  }
}

async function doDeleteTemplate() {
  const id = selectedNode.value?.data.params.template || tplPreviewId.value
  if (!id) return
  try {
    await engine.deleteTemplate(id)
    message.success('已删除模板：' + id)
    tplPreview.value = ''
    tplPreviewId.value = ''
    // 清空所有引用该模板的节点
    for (const n of nodes.value) {
      const st = n.data?.stepType
      if ((st === 'find_image' || st === 'judge') && n.data?.params?.template === id) {
        n.data.params.template = ''
      }
    }
    await refreshTemplates()
    loadFlowToEngine()
  } catch (e: any) {
    message.error('删除失败：' + e.message)
  }
}

// ---------- 按键录制 ----------
function startKeyRecord() {
  keyRecording.value = true
  window.addEventListener('keydown', onKeyRecordKey)
}

function onKeyRecordKey(e: KeyboardEvent) {
  e.preventDefault()
  e.stopPropagation()
  const k = e.key.toLowerCase()
  if (k === 'control' || k === 'alt' || k === 'shift' || k === 'meta') return
  const parts: string[] = []
  if (e.ctrlKey) parts.push('ctrl')
  if (e.altKey) parts.push('alt')
  if (e.shiftKey) parts.push('shift')
  parts.push(k === ' ' ? 'space' : k)
  const keyName = parts.join('+')
  if (selectedNode.value && selectedNode.value.data.stepType === 'key') {
    selectedNode.value.data.params.key = keyName
    message.success('已录入按键：' + keyName)
  }
  finishKeyRecord()
}

function finishKeyRecord() {
  keyRecording.value = false
  window.removeEventListener('keydown', onKeyRecordKey)
}

// 选中节点变化时自动预览模板
watch(selectedNode, (n) => {
  if (n && (n.data.stepType === 'find_image' || n.data.stepType === 'judge')) {
    previewTemplate(n.data.params.template)
  } else {
    tplPreview.value = ''
    tplPreviewId.value = ''
  }
})

// ---------- 窗口绑定 ----------
async function refreshWindows() {
  try {
    const r = await engine.listWindows()
    windows.value = r.windows
  } catch (e: any) {
    message.error('获取窗口列表失败：' + e.message)
  }
}

function onWindowChange(hwnd: number) {
  selectedWinHwnd.value = hwnd
  if (!hwnd) {
    store.boundWindow = null
  } else {
    const w = windows.value.find((x) => x.hwnd === hwnd)
    store.boundWindow = w ? { hwnd: w.hwnd, title: w.title } : null
  }
}

// ---------- 保存 / 加载 ----------
async function saveFlow() {
  // 分辨率参考：沿用文件原参考（坐标未变），新建脚本用当前分辨率
  const screenRef = fileScreen.value ?? currentScreen()
  const windowRef = fileWindowRect.value ?? currentWindowRect()
  const data: FlowFile = {
    format: 'agflow',
    version: 1,
    name: store.flowName,
    repeat: store.repeat,
    input_mode: store.inputMode,
    window: store.boundWindow ? { ...store.boundWindow, rect: windowRef } : null,
    screen: screenRef,
    nodes: nodes.value,
    edges: edges.value,
  }
  fileScreen.value = screenRef
  fileWindowRect.value = windowRef
  const json = JSON.stringify(data, null, 2)
  const w = window as any
  // 优先使用文件系统访问 API：弹出原生保存对话框（可覆盖/另存）
  if (typeof w.showSaveFilePicker === 'function') {
    try {
      const handle = await w.showSaveFilePicker({
        suggestedName: `${store.flowName || '脚本'}.agflow`,
        types: [{ description: 'AutoGameTool 脚本', accept: { 'application/json': ['.agflow'] } }],
      })
      const writable = await handle.createWritable()
      await writable.write(json)
      await writable.close()
      message.success('脚本已保存')
      return
    } catch (e: any) {
      if (e && e.name === 'AbortError') return // 用户取消
      // 否则回退到下载
    }
  }
  // 回退：浏览器下载
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${store.flowName || '脚本'}.agflow`
  a.click()
  URL.revokeObjectURL(url)
  message.success('脚本已保存')
}

function triggerLoad() {
  fileInput.value?.click()
}

function onLoadFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result as string) as FlowFile
      if (data.format !== 'agflow') throw new Error('不是有效的 AutoGameTool 脚本文件')
      store.flowName = data.name || '未命名脚本'
      store.repeat = data.repeat || 1
      store.inputMode = data.input_mode || 'real'
      store.boundWindow = data.window || null
      selectedWinHwnd.value = data.window?.hwnd ?? 0
      nodes.value = data.nodes || []
      edges.value = data.edges || []
      // 保留文件的分辨率参考（其中的坐标以该分辨率为基准）
      fileScreen.value = data.screen ?? null
      fileWindowRect.value = data.window?.rect ?? null
      // 取现有节点 ID 的最大数字后缀，避免新增节点撞 ID
      nodeSeq = Math.max(
        0,
        ...nodes.value.map((n) => parseInt(String(n.id).replace(/\D/g, ''), 10) || 0),
      )
      selectedId.value = null
      message.success('脚本已加载')
    } catch (err: any) {
      message.error('加载失败：' + err.message)
    }
  }
  reader.readAsText(file)
  input.value = ''
}

// ---------- 快捷键 ----------
function joinHotkey(keys: string[]) {
  return keys.join(' + ')
}

async function loadHotkey() {
  try {
    const r = await engine.getHotkey()
    hotkeyText.value = joinHotkey(r.hotkey)
  } catch {
    /* ignore */
  }
}

async function saveHotkey() {
  const keys = hotkeyText.value
    .split(/[+\s]+/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
  if (keys.length === 0) {
    message.warning('请输入快捷键，例如 alt+f1')
    return
  }
  try {
    await engine.setHotkey(keys)
    message.success('快捷键已保存：' + joinHotkey(keys))
  } catch (e: any) {
    message.error('保存快捷键失败：' + e.message)
  }
}

function startRecord() {
  recording.value = true
  recordParts.value = []
  window.addEventListener('keydown', onRecordKey)
}

function onRecordKey(e: KeyboardEvent) {
  e.preventDefault()
  e.stopPropagation()
  const k = e.key.toLowerCase()
  const modMap: Record<string, string> = { control: 'ctrl', alt: 'alt', shift: 'shift', meta: 'win' }
  if (k === 'control' || k === 'alt' || k === 'shift' || k === 'meta') {
    if (!recordParts.value.includes(modMap[k])) recordParts.value.push(modMap[k])
    return
  }
  const key = k === ' ' ? 'space' : k
  if (!recordParts.value.includes(key)) recordParts.value.push(key)
  hotkeyText.value = joinHotkey(recordParts.value)
  finishRecord()
}

function finishRecord() {
  recording.value = false
  window.removeEventListener('keydown', onRecordKey)
}

// ---------- 运行 ----------
function flowGraph() {
  const gNodes = nodes.value.map((n) => ({
    id: n.id,
    type: (n.data as any).stepType,
    params: (n.data as any).params || {},
    once: !!(n.data as any).once,
  }))
  const gEdges = edges.value.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle || null,
  }))
  return { nodes: gNodes, edges: gEdges }
}

async function run() {
  if (nodes.value.length === 0) {
    message.warning('请先添加步骤')
    return
  }
  const graph = flowGraph()
  store.clearLogs()
  try {
    await engine.run({
      name: store.flowName,
      repeat: store.repeat,
      input_mode: store.inputMode,
      window: flowWindow(),
      screen: fileScreen.value ?? currentScreen(),
      ...graph,
    })
    store.running = true
  } catch (e: any) {
    message.error('启动失败：' + e.message)
  }
}

async function stop() {
  try {
    const r = await engine.stop()
    // 以引擎返回的真实状态为准：若流程早已结束（假运行），立即解除按钮卡死
    store.running = !!r.running
  } catch (e: any) {
    message.error('停止失败：' + e.message)
  }
}

// 快捷键触发：与点击“运行/停止”完全一致
function toggleScript() {
  if (store.running) {
    store.addLog({ level: 'warn', message: '收到快捷键：停止脚本', ts: Date.now() / 1000 })
    stop()
  } else {
    store.addLog({ level: 'info', message: '收到快捷键：启动脚本', ts: Date.now() / 1000 })
    run()
  }
}

// ---------- 键鼠录制 ----------
function startRecording() {
  macroRecording.value = true
  engine.recordStart().catch((e: any) => {
    macroRecording.value = false
    message.error('启动录制失败：' + e.message)
  })
}

function stopRecording() {
  engine.recordStop().catch((e: any) => message.error('停止录制失败：' + e.message))
}

function onRecorded(events: any[]) {
  macroRecording.value = false
  if (!events || events.length === 0) {
    message.warning('录制内容为空')
    return
  }
  const id = `n${++nodeSeq}`
  let pos = { x: 60, y: 80 }
  if (vf && typeof vf.screenToFlowCoordinate === 'function') {
    try {
      const p = vf.screenToFlowCoordinate({ x: mousePos.value.x, y: mousePos.value.y })
      if (p) pos = { x: Math.round(p.x), y: Math.round(p.y) }
    } catch {
      /* ignore */
    }
  }
  nodes.value.push({
    id,
    type: 'step',
    position: pos,
    data: { stepType: 'macro', label: '键鼠录制', params: { events, speed: 1.0 }, once: false },
  } as any)
  selectedId.value = id
  message.success(`已录制 ${events.length} 个事件，并生成一个录制步骤`)
  loadFlowToEngine()
}

// 以引擎为唯一事实来源同步运行状态（WS 断连/广播丢失时靠它自愈）
async function syncRunState() {
  try {
    const r = await engine.runState()
    store.running = !!r.running
  } catch {
    /* 引擎不可达时下个周期再试 */
  }
}

function connectWs() {
  if (destroyed) return
  ws = new WebSocket(engineWsUrl())
  ws.onopen = () => {
    if (wsFailCount >= 3) message.success('已重新连接引擎')
    wsFailCount = 0
    syncRunState()
  }
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'log') store.addLog(msg)
      else if (msg.type === 'state') store.running = msg.state === 'running'
      else if (msg.type === 'picked') onPicked(msg.x, msg.y)
      else if (msg.type === 'hotkey') toggleScript()
      else if (msg.type === 'recording') macroRecording.value = !!msg.recording
      else if (msg.type === 'recorded') onRecorded(msg.events || [])
    } catch {
      /* ignore */
    }
  }
  ws.onclose = () => {
    store.running = false
    if (destroyed) return
    // 自动重连：断线期间日志/状态会丢，重连后立即同步真实状态
    wsFailCount += 1
    if (wsFailCount === 3) {
      message.warning('与引擎的连接已断开，正在自动重连…若引擎刚重启，请从程序重新打开页面')
    }
    if (wsRetry) clearTimeout(wsRetry)
    wsRetry = setTimeout(connectWs, 2000)
  }
}

// ---------- 面板缩放 ----------
function startResize(type: 'log' | 'inspector', e: MouseEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startY = e.clientY
  const startH = logHeight.value
  const startW = inspectorWidth.value
  const onMove = (ev: MouseEvent) => {
    if (type === 'log') {
      logHeight.value = Math.max(80, Math.min(600, startH + (startY - ev.clientY)))
    } else {
      inspectorWidth.value = Math.max(220, Math.min(520, startW + (startX - ev.clientX)))
    }
  }
  const onUp = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

watch(
  () => store.logs.length,
  async () => {
    await nextTick()
    logBody.value?.scrollTo({ top: logBody.value.scrollHeight })
  },
)

function formatTime(ts: number) {
  const d = new Date(ts * 1000)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  const ms = String(d.getMilliseconds()).padStart(3, '0')
  return `${hh}:${mm}:${ss}.${ms}`
}

let loadTimer: ReturnType<typeof setTimeout> | null = null

let lastSyncedJson = ''

function loadFlowToEngine(force = false) {
  const payload = {
    name: store.flowName,
    repeat: store.repeat,
    input_mode: store.inputMode,
    window: flowWindow(),
    screen: fileScreen.value ?? currentScreen(),
    ...flowGraph(),
  }
  // 指纹未变化则跳过，避免每秒全量同步空打引擎
  const json = JSON.stringify(payload)
  if (!force && json === lastSyncedJson) return
  lastSyncedJson = json
  engine.loadFlow(payload).catch(() => {
    lastSyncedJson = '' // 失败后下次重试
  })
}

// 流程变化时同步到引擎，供快捷键 alt+f1 启停（直接用 refs 监听 + 短防抖）
watch(
  [nodes, edges, () => store.flowName, () => store.repeat, () => store.inputMode, () => store.boundWindow],
  () => {
    if (loadTimer) clearTimeout(loadTimer)
    loadTimer = setTimeout(loadFlowToEngine, 150)
  },
  { deep: true },
)

let syncTimer: ReturnType<typeof setInterval> | null = null
let stateTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  connectWs()
  refreshTemplates()
  refreshWindows()
  loadHotkey()
  loadFlowToEngine(true)
  // 定时兜底同步流程到引擎（内部已按指纹去重），确保全局快捷键随时可用
  syncTimer = setInterval(() => loadFlowToEngine(), 1000)
  // 定时同步真实运行状态：任何状态广播丢失都能在一秒内自愈，按钮不再卡死
  stateTimer = setInterval(syncRunState, 1000)
})
onBeforeUnmount(() => {
  destroyed = true
  if (wsRetry) clearTimeout(wsRetry)
  ws?.close()
  if (syncTimer) clearInterval(syncTimer)
  if (stateTimer) clearInterval(stateTimer)
})
</script>

<template>
  <div class="editor">
    <header class="topbar">
      <n-button quaternary @click="router.push('/')">← 返回</n-button>
      <div class="brand">🎮 AutoGameTool</div>
      <n-input v-model:value="store.flowName" class="name-input" placeholder="脚本名称" />
      <div class="spacer" />
      <n-button size="small" @click="saveFlow">💾 保存</n-button>
      <n-button size="small" @click="triggerLoad">📂 加载</n-button>
      <input ref="fileInput" type="file" accept=".agflow,application/json" style="display: none" @change="onLoadFile" />
      <n-button v-if="!store.running" type="primary" @click="run">▶ 运行</n-button>
      <n-button v-else type="error" @click="stop">■ 停止</n-button>
    </header>

    <div class="settings-bar">
      <div class="setting">
        <span class="setting-label">循环轮数</span>
        <n-input-number v-model:value="store.repeat" :min="1" :max="9999" size="small" style="width: 82px" />
      </div>
      <div class="setting">
        <span class="setting-label">输入方式</span>
        <n-radio-group v-model:value="store.inputMode" size="small">
          <n-radio-button value="real">🖱 键鼠输入</n-radio-button>
          <n-radio-button value="simulated">📨 模拟输入</n-radio-button>
        </n-radio-group>
      </div>
      <div class="setting">
        <span class="setting-label">绑定窗口</span>
        <n-select
          v-model:value="selectedWinHwnd"
          :options="winOptions"
          size="small"
          style="width: 260px"
          placeholder="选择目标窗口"
          @update:value="onWindowChange"
        />
        <n-button size="small" quaternary @click="refreshWindows">🔄</n-button>
      </div>
      <div class="setting">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button size="small" @click="hotkeyVisible = true">⌨ 快捷键</n-button>
          </template>
          全局启停快捷键（默认 alt+f1）
        </n-tooltip>
      </div>
      <div class="setting">
        <n-button
          size="small"
          :type="macroRecording ? 'error' : 'default'"
          @click="macroRecording ? stopRecording() : startRecording()"
        >
          {{ macroRecording ? '⏹ 停止录制 (alt+9)' : '⏺ 开始录制 (alt+9)' }}
        </n-button>
      </div>
    </div>

    <div class="main">
      <aside class="palette">
        <div class="palette-title">步骤类型</div>
        <div v-for="[t, meta] in stepTypes" :key="t" class="palette-item" @click="addStep(t)">
          <span class="palette-icon" :style="{ background: meta.color }">{{ meta.icon }}</span>
          <span>{{ meta.label }}</span>
        </div>
        <div class="palette-hint">点击添加步骤<br />拖动节点圆点手动连线</div>
      </aside>

      <section class="canvas" @mousemove="onCanvasMove">
        <VueFlow
          v-model:nodes="nodes"
          v-model:edges="edges"
          :node-types="nodeTypes"
          :min-zoom="0.2"
          :max-zoom="2"
          :fit-view-on-init="false"
          @connect="onConnect"
          @node-click="onNodeClick"
          @pane-click="selectedId = null"
          @pane-ready="onPaneReady"
        >
          <Background :gap="18" />
        </VueFlow>
        <div v-if="nodes.length === 0" class="canvas-empty">
          <div class="empty-emoji">🧩</div>
          <div>从左侧点击步骤类型开始搭建脚本流程</div>
        </div>

        <div class="flow-controls">
          <n-tooltip trigger="hover"><template #trigger><button class="ctl" @click="zoomIn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" /></svg></button></template>放大</n-tooltip>
          <n-tooltip trigger="hover"><template #trigger><button class="ctl" @click="zoomOut"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="8" y1="11" x2="14" y2="11" /></svg></button></template>缩小</n-tooltip>
          <n-tooltip trigger="hover"><template #trigger><button class="ctl" @click="fitView"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3" /><path d="M21 8V5a2 2 0 0 0-2-2h-3" /><path d="M3 16v3a2 2 0 0 0 2 2h3" /><path d="M16 21h3a2 2 0 0 0 2-2v-3" /></svg></button></template>适应视图</n-tooltip>
          <n-tooltip trigger="hover"><template #trigger><button class="ctl" @click="pan(120, 0)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg></button></template>左移</n-tooltip>
          <n-tooltip trigger="hover"><template #trigger><button class="ctl" @click="pan(-120, 0)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" /></svg></button></template>右移</n-tooltip>
          <n-tooltip trigger="hover"><template #trigger><button class="ctl" @click="pan(0, 120)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="19" x2="12" y2="5" /><polyline points="5 12 12 5 19 12" /></svg></button></template>上移</n-tooltip>
          <n-tooltip trigger="hover"><template #trigger><button class="ctl" @click="pan(0, -120)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><polyline points="19 12 12 19 5 12" /></svg></button></template>下移</n-tooltip>
        </div>
      </section>

      <div class="resize-handle inspector-handle" @mousedown="startResize('inspector', $event)" />

      <aside class="inspector" :style="{ width: inspectorWidth + 'px' }">
        <template v-if="selectedNode">
          <div class="inspector-head">
            <span class="inspector-title">
              {{ metaOf(selectedNode.data.stepType).icon }}
              {{ metaOf(selectedNode.data.stepType).label }}
            </span>
            <n-button size="tiny" quaternary type="error" @click="removeSelected">删除</n-button>
          </div>

          <template v-if="!['judge', 'terminate'].includes(selectedNode.data.stepType)">
            <div class="field">
              <label>单次执行（仅第一轮循环）</label>
              <n-switch v-model:value="selectedNode.data.once" />
            </div>
          </template>

          <template v-if="selectedNode.data.stepType === 'delay'">
            <div class="field">
              <label>延时（毫秒）</label>
              <n-input-number v-model:value="selectedNode.data.params.ms" :min="0" :step="100" />
            </div>
          </template>

          <template v-else-if="selectedNode.data.stepType === 'find_image' || selectedNode.data.stepType === 'judge'">
            <div class="field">
              <label>识别模板</label>
              <div class="row">
                <n-select
                  v-model:value="selectedNode.data.params.template"
                  :options="templates"
                  placeholder="选择模板"
                  filterable
                  style="flex: 1"
                  @update:value="previewTemplate"
                />
                <n-button size="small" @click="openCapture('region')">截取</n-button>
              </div>
            </div>
            <div v-if="tplPreview" class="field">
              <label>模板预览</label>
              <img :src="tplPreview" class="tpl-preview" alt="模板预览" />
              <div class="row" style="margin-top: 6px">
                <n-button size="tiny" @click="openRename">重命名</n-button>
                <n-button size="tiny" type="error" @click="doDeleteTemplate">删除</n-button>
              </div>
            </div>
            <div class="field">
              <label>相似度阈值：{{ (selectedNode.data.params.threshold * 100).toFixed(0) }}%</label>
              <n-slider v-model:value="selectedNode.data.params.threshold" :min="0.5" :max="1" :step="0.01" />
            </div>
            <div class="field">
              <label>超时（毫秒）</label>
              <n-input-number v-model:value="selectedNode.data.params.timeout_ms" :min="0" :step="500" />
            </div>
            <template v-if="selectedNode.data.stepType === 'find_image'">
              <div class="field">
                <label>超时处理</label>
                <n-select
                  v-model:value="selectedNode.data.params.on_timeout"
                  :options="[
                    { label: '跳过（继续下一步）', value: 'skip' },
                    { label: '退出（停止整个脚本）', value: 'exit' },
                  ]"
                />
              </div>
              <div class="field">
                <label>找到后自动点击</label>
                <n-switch v-model:value="selectedNode.data.params.click" />
              </div>
              <div class="field">
                <n-button size="small" block @click="testMatch">测试识别</n-button>
              </div>
            </template>
          </template>

          <template v-else-if="selectedNode.data.stepType === 'click'">
            <div class="field">
              <label>坐标（X, Y）</label>
              <div class="row">
                <n-input-number v-model:value="selectedNode.data.params.x" :step="1" style="flex: 1" />
                <n-input-number v-model:value="selectedNode.data.params.y" :step="1" style="flex: 1" />
              </div>
              <n-button size="small" block style="margin-top: 6px" @click="startPicking">🎯 拾取屏幕坐标</n-button>
            </div>
            <div class="field">
              <label>按键</label>
              <n-select
                v-model:value="selectedNode.data.params.button"
                :options="[
                  { label: '左键', value: 'left' },
                  { label: '右键', value: 'right' },
                  { label: '中键', value: 'middle' },
                ]"
              />
            </div>
            <div class="field">
              <label>点击次数</label>
              <n-input-number v-model:value="selectedNode.data.params.clicks" :min="1" :max="10" />
            </div>
          </template>

          <template v-else-if="selectedNode.data.stepType === 'key'">
            <div class="field">
              <label>按键（点「录制」后按下按键）</label>
              <div class="row">
                <n-input :value="selectedNode.data.params.key" placeholder="未设置" readonly style="flex: 1" />
                <n-button size="small" :type="keyRecording ? 'error' : 'primary'" @click="keyRecording ? finishKeyRecord() : startKeyRecord()">
                  {{ keyRecording ? '按下按键…' : '录制' }}
                </n-button>
              </div>
            </div>
          </template>

          <template v-else-if="selectedNode.data.stepType === 'text'">
            <div class="field">
              <label>文本内容</label>
              <n-input v-model:value="selectedNode.data.params.text" type="textarea" :rows="3" placeholder="要输入的文本" />
            </div>
          </template>

          <template v-else-if="selectedNode.data.stepType === 'terminate'">
            <div class="field">
              <p class="terminate-hint">执行到此节点时，无论脚本或循环是否完成，立即停止整个运行。</p>
            </div>
          </template>

          <template v-else-if="selectedNode.data.stepType === 'macro'">
            <div class="field">
              <label>录制内容</label>
              <p class="terminate-hint">
                共 {{ (selectedNode.data.params.events || []).length }} 个事件（鼠标移动/点击/滚轮、键盘按下/抬起）
              </p>
            </div>
            <div class="field">
              <label>回放速度：x{{ selectedNode.data.params.speed }}</label>
              <n-slider v-model:value="selectedNode.data.params.speed" :min="0.25" :max="4" :step="0.25" />
            </div>
            <div class="field">
              <n-button
                size="small"
                block
                :type="macroRecording ? 'error' : 'primary'"
                @click="macroRecording ? stopRecording() : startRecording()"
              >
                {{ macroRecording ? '⏹ 停止录制' : '⏺ 重新录制（alt+9）' }}
              </n-button>
            </div>
            <div class="field">
              <p class="terminate-hint">提示：录制会覆盖当前步骤内容；录制时请切换到目标窗口操作，再次按 alt+9 结束。</p>
            </div>
          </template>
        </template>
        <div v-else class="inspector-empty">
          <div class="empty-emoji">🖐</div>
          <div>选中画布中的节点以配置参数</div>
        </div>
      </aside>
    </div>

    <div class="resize-handle log-handle" @mousedown="startResize('log', $event)" />

    <footer class="logpanel" :style="{ height: logHeight + 'px' }">
      <div class="logpanel-head">
        <span>运行日志</span>
        <n-button size="tiny" quaternary @click="store.clearLogs()">清空</n-button>
      </div>
      <div ref="logBody" class="logpanel-body">
        <div v-if="store.logs.length === 0" class="log-empty">暂无日志，点击「运行」开始执行流程</div>
        <div v-for="(l, i) in store.logs" :key="i" class="log-line" :class="l.level">
          <span class="log-ts">{{ formatTime(l.ts) }}</span>
          <span class="log-level">{{ l.level }}</span>
          <span class="log-msg">{{ l.message }}</span>
        </div>
      </div>
    </footer>

    <ScreenCapture
      :show="capVisible"
      :mode="capMode"
      :initial-window="store.boundWindow?.hwnd ?? null"
      @captured="onCaptured"
      @picked="onPicked"
      @cancel="capVisible = false"
    />

    <n-modal v-model:show="pickingVisible" preset="card" title="拾取屏幕坐标" style="width: 480px" :mask-closable="false">
      <div class="pick-body">
        <p>已进入坐标拾取模式，请按以下步骤操作：</p>
        <ol>
          <li>切换到目标窗口（游戏画面）</li>
          <li>按下快捷键 <b>F8</b> 进入选取</li>
          <li><b>单击鼠标左键</b>，该点的真实屏幕坐标会自动填入</li>
        </ol>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end">
          <n-button @click="cancelPicking">取消</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="renameVisible" preset="card" title="重命名模板" style="width: 420px">
      <div class="rename-body">
        <n-input v-model:value="renameText" placeholder="输入新模板名" @keyup.enter="doRename" />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="renameVisible = false">取消</n-button>
          <n-button type="primary" @click="doRename">确定</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="matchVisible" preset="card" title="识别结果" style="width: min(760px, 92vw)">
      <img :src="matchImage" alt="match result" style="max-width: 100%; border-radius: 8px" />
    </n-modal>

    <n-modal v-model:show="hotkeyVisible" preset="card" title="全局快捷键设置" style="width: 420px">
      <div class="hotkey-body">
        <p class="hk-tip">设置运行/停止脚本的全局快捷键（不占用键鼠的模拟输入模式下尤其有用）。</p>
        <div class="hk-row">
          <n-input v-model:value="hotkeyText" placeholder="如 alt+f1" :disabled="recording" />
          <n-button :type="recording ? 'error' : 'primary'" @click="recording ? finishRecord() : startRecord()">
            {{ recording ? '按下组合键完成录制' : '录制' }}
          </n-button>
        </div>
        <p class="hk-hint">支持 ctrl / alt / shift / win + 字母/数字/f1-f12，例如 alt+f1、ctrl+shift+a</p>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="hotkeyVisible = false">取消</n-button>
          <n-button type="primary" @click="saveHotkey">保存</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.editor {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-soft);
}
.brand {
  font-weight: 700;
  white-space: nowrap;
}
.name-input {
  max-width: 200px;
}
.spacer {
  flex: 1;
}

.settings-bar {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 6px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  flex-wrap: wrap;
}
.setting {
  display: flex;
  align-items: center;
  gap: 6px;
}
.setting-label {
  font-size: 12px;
  color: var(--text-dim);
  white-space: nowrap;
}

.main {
  flex: 1;
  display: flex;
  min-height: 0;
}
.palette {
  width: 150px;
  flex: none;
  border-right: 1px solid var(--border);
  background: var(--bg-soft);
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.palette-title {
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 600;
  margin-bottom: 2px;
}
.palette-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: 0.15s;
  font-size: 13px;
}
.palette-item:hover {
  background: var(--bg-panel);
  border-color: var(--border);
}
.palette-icon {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  font-size: 12px;
  flex: none;
}
.palette-hint {
  margin-top: auto;
  font-size: 11px;
  color: var(--text-dim);
  line-height: 1.5;
}

.canvas {
  flex: 1;
  position: relative;
  min-width: 0;
}
.canvas-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-dim);
  pointer-events: none;
}
.empty-emoji {
  font-size: 42px;
}

.flow-controls {
  position: absolute;
  left: 12px;
  bottom: 12px;
  display: flex;
  gap: 6px;
  padding: 6px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
.ctl {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--text);
  cursor: pointer;
  transition: 0.15s;
}
.ctl:hover {
  background: #2a3140;
  border-color: var(--border);
}
.ctl svg {
  width: 16px;
  height: 16px;
}

.resize-handle {
  flex: none;
}
.inspector-handle {
  width: 5px;
  cursor: col-resize;
  background: transparent;
}
.inspector-handle:hover {
  background: var(--accent);
}
.log-handle {
  height: 5px;
  cursor: row-resize;
  background: transparent;
}
.log-handle:hover {
  background: var(--accent);
}

.inspector {
  flex: none;
  border-left: 1px solid var(--border);
  background: var(--bg-soft);
  padding: 14px;
  overflow-y: auto;
}
.inspector-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.inspector-title {
  font-weight: 700;
  font-size: 15px;
}
.inspector-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-dim);
  text-align: center;
}
.field {
  margin-bottom: 14px;
}
.field label {
  display: block;
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 6px;
}
.row {
  display: flex;
  gap: 8px;
}
.tpl-preview {
  max-width: 100%;
  max-height: 120px;
  border: 1px solid var(--border);
  border-radius: 6px;
  display: block;
  background: #000;
}
.terminate-hint {
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.5;
}

.logpanel {
  flex: none;
  border-top: 1px solid var(--border);
  background: var(--bg-soft);
  display: flex;
  flex-direction: column;
}
.logpanel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 14px;
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}
.logpanel-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px 14px;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
}
.log-empty {
  color: var(--text-dim);
  padding: 8px 0;
}
.log-line {
  display: flex;
  gap: 10px;
  padding: 2px 0;
  align-items: baseline;
}
.log-ts {
  color: var(--text-dim);
  flex: none;
}
.log-level {
  flex: none;
  width: 40px;
  text-transform: uppercase;
  font-weight: 700;
}
.log-line.info .log-level {
  color: var(--ok);
}
.log-line.warn .log-level {
  color: var(--warn);
}
.log-line.error .log-level {
  color: var(--danger);
}
.log-line.debug .log-level {
  color: var(--accent);
}
.log-msg {
  color: var(--text);
  word-break: break-all;
}

.hotkey-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.hk-tip {
  margin: 0;
  color: var(--text-dim);
  font-size: 13px;
}
.hk-row {
  display: flex;
  gap: 8px;
}
.hk-hint {
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
}
</style>
