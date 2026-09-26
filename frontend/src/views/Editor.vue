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
import {
  canPack,
  COL_PITCH,
  compileMacroPieces,
  expandPieces,
  NODE_H,
  NODE_W,
  orderChain,
  packStepsToMacro,
  ROW_PITCH,
  splitGridLayout,
  splitGridPositions,
} from '../lib/macroSplit'

const store = useProjectStore()
const message = useMessage()
const router = useRouter()

const nodeTypes: any = { step: markRaw(StepNode) }
const stepTypes = Object.entries(STEP_META) as Array<[StepType, { label: string; icon: string; color: string }]>

const nodes = ref<any[]>([])
const edges = ref<any[]>([])
const selectedId = ref<string | null>(null)
// 多选（Vue Flow 内建：Shift+拖拽框选、Ctrl+点击逐个加选）选中的节点 id。
// 用 selection-change 事件单独记一份，而不是依赖 node.selected —— 打包按钮的
// 可用状态/数量要能跟着选择实时变。
const selIds = ref<string[]>([])
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

// 画布上所有「键鼠录制」步骤（工具栏的拆分入口据此决定可用状态）
const macroNodes = computed(() => nodes.value.filter((n) => n.data.stepType === 'macro'))

// 引擎版本：显示在顶栏。排查「界面没看到某个功能」时，一眼就能确认页面/进程是不是新版
const engineVersion = ref('')

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
  refreshSelection()
}

function onPaneClick() {
  selectedId.value = null
  refreshSelection()
}

// 刷新多选集合。
// 注意：@vue-flow/core 1.48 的 emits 列表里**没有** selectionChange（只有
// selectionStart / selectionDrag / selectionEnd / nodeClick / paneClick），
// 所以这里不监听"选择变化"，而是在这几个真实存在的事件里主动向 Vue Flow
// 要一次当前选中集合（getSelectedNodes 是权威来源）。
function refreshSelection() {
  try {
    const list = vf?.getSelectedNodes?.()
    if (Array.isArray(list)) {
      selIds.value = list.map((n: any) => n.id)
      return
    }
  } catch {
    /* 退回到节点自身的 selected 标记 */
  }
  selIds.value = nodes.value.filter((n: any) => n.selected).map((n) => n.id)
}

// ---------- 撤销 / 重做 ----------
// 实现方式是**快照式历史**，而不是在每个修改点手动入栈。
// 原因：画布上会改 nodes/edges 的地方远不止我们自己的那几个函数——Vue Flow
// 自己就会改（Delete 键删节点/连线、拖动坐标），属性面板里还有一堆直接
// v-model 到 params 的输入框。逐个包起来必然漏，漏掉的那部分就会表现为
// 「撤销时灵时不灵」。改成「深度监听 + 防抖 + 按内容去重」后，所有改动路径
// 都被同一套机制覆盖，也不需要去猜哪些操作算“一步”。
const HISTORY_MAX = 60
const HISTORY_DEBOUNCE_MS = 350

interface Snapshot {
  json: string
  nodes: any[]
  edges: any[]
  selectedId: string | null
}

const history = ref<Snapshot[]>([])
const hIndex = ref(-1)
const canUndo = computed(() => hIndex.value > 0)
const canRedo = computed(() => hIndex.value < history.value.length - 1)
// 应用快照期间不要记录历史（否则撤销本身会被记成一步，撤销就再也回不去）
let restoring = false
let histTimer: ReturnType<typeof setTimeout> | null = null

function cloneData<T>(v: T): T {
  return JSON.parse(JSON.stringify(v ?? null)) as T
}

/** 只保留流程语义字段。
 *  Vue Flow 会往节点上挂 dimensions / selected / dragging / handleBounds 等
 *  运行时属性，若不剔除，随便点一下选中就会产生"看起来变了"的假快照，
 *  历史很快被这些噪音填满，真正要撤销的改动反而被挤出去。 */
function snapshotOf(): Snapshot {
  const ns = nodes.value.map((n: any) => ({
    id: n.id,
    type: n.type ?? 'step',
    position: { x: Math.round(n.position?.x ?? 0), y: Math.round(n.position?.y ?? 0) },
    data: cloneData(n.data),
  }))
  const es = edges.value.map((e: any) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle ?? null,
  }))
  return { json: JSON.stringify({ ns, es }), nodes: ns, edges: es, selectedId: selectedId.value }
}

function pushHistory(force = false) {
  if (restoring) return
  const snap = snapshotOf()
  const top = history.value[hIndex.value]
  if (!force && top && top.json === snap.json) return
  // 撤销之后又做了新改动 → 丢弃原来的「未来」分支
  if (hIndex.value < history.value.length - 1) history.value = history.value.slice(0, hIndex.value + 1)
  history.value.push(snap)
  if (history.value.length > HISTORY_MAX) history.value.shift()
  hIndex.value = history.value.length - 1
}

/** 重置历史（新建 / 加载脚本时调用）：撤销不应该跨脚本跳回上一个流程。 */
function resetHistory() {
  history.value = []
  hIndex.value = -1
  pushHistory(true)
}

function applySnapshot(snap: Snapshot) {
  if (!snap) return
  restoring = true
  nodes.value = snap.nodes.map((n) => ({ ...n, position: { ...n.position }, data: cloneData(n.data) }))
  edges.value = snap.edges.map((e) => ({ ...e }))
  selectedId.value = snap.nodes.some((n) => n.id === snap.selectedId) ? snap.selectedId : null
  // id 计数器必须跟上：否则撤销后再新增节点会和历史里的节点撞 id
  nodeSeq = snap.nodes.reduce((m, n) => Math.max(m, Number(String(n.id).replace(/^n/, '')) || 0), 0)
  nextTick(() => {
    restoring = false
    refreshSelection()
    loadFlowToEngine()
  })
}

function undo() {
  if (!canUndo.value) {
    message.info('没有可撤销的改动了')
    return
  }
  hIndex.value -= 1
  applySnapshot(history.value[hIndex.value])
}

function redo() {
  if (!canRedo.value) {
    message.info('没有可重做的改动了')
    return
  }
  hIndex.value += 1
  applySnapshot(history.value[hIndex.value])
}

// 深度监听 + 防抖：拖动节点、连续输入参数会被合并成一步，而不是几十步
watch(
  [nodes, edges],
  () => {
    if (restoring) return
    if (histTimer) clearTimeout(histTimer)
    histTimer = setTimeout(() => pushHistory(), HISTORY_DEBOUNCE_MS)
  },
  { deep: true },
)

// Ctrl+Z 撤销、Ctrl+Y（或 Ctrl+Shift+Z）重做。
// 输入框内不拦截：那里让浏览器做原生的文本撤销更符合直觉。
function onHistoryKey(e: KeyboardEvent) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return
  const t = e.target as HTMLElement | null
  const tag = (t?.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || t?.isContentEditable) return
  const k = e.key.toLowerCase()
  if (k === 'z' && !e.shiftKey) {
    e.preventDefault()
    undo()
  } else if (k === 'y' || (k === 'z' && e.shiftKey)) {
    e.preventDefault()
    redo()
  }
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
      // 脚本名：优先用文件内记录的名字；若为空或是占位名「未命名脚本」，则退回用文件名。
      // （没改名就保存的文件，内部记的就是占位名，此时用文件名才对应你给脚本起的名字）
      const innerName = String(data.name ?? '').trim()
      const fileName = String(file.name || '').replace(/\.agflow$/i, '').trim()
      store.flowName =
        innerName && innerName !== '未命名脚本' ? innerName : fileName || innerName || '未命名脚本'
      store.repeat = data.repeat || 1
      store.inputMode = data.input_mode || 'real'
      // 默认全局：不恢复脚本里保存的窗口绑定。
      // 旧文件里的 hwnd 早就失效，直接恢复会让下拉框显示成一个「空进程」并要求手动重选。
      // 需要绑定时在顶栏手动选择即可。
      const hadWindow = !!data.window
      store.boundWindow = null
      selectedWinHwnd.value = 0
      nodes.value = data.nodes || []
      edges.value = data.edges || []
      // 保留文件的分辨率参考（其中的坐标以该分辨率为基准）
      fileScreen.value = data.screen ?? null
      // 不再绑定窗口，窗口 rect 参考也一并作废，避免之后手动绑定窗口时用到旧 rect
      fileWindowRect.value = null
      // 取现有节点 ID 的最大数字后缀，避免新增节点撞 ID
      nodeSeq = Math.max(
        0,
        ...nodes.value.map((n) => parseInt(String(n.id).replace(/\D/g, ''), 10) || 0),
      )
      selectedId.value = null
      message.success(hadWindow ? '脚本已加载（默认全局绑定，未恢复原窗口）' : '脚本已加载')
      // 历史从「刚加载完」这一刻重新开始：撤销不应该跨脚本跳回上一个流程
      resetHistory()
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

// 快捷键触发：与点击“运行/停止”完全一致（仅用于兼容旧版引擎）
function toggleScript() {
  if (store.running) {
    store.addLog({ level: 'warn', message: '收到快捷键：停止脚本', ts: Date.now() / 1000 })
    stop()
  } else {
    store.addLog({ level: 'info', message: '收到快捷键：启动脚本', ts: Date.now() / 1000 })
    run()
  }
}

// 引擎侧的「启动」请求。
// 新版引擎把启停方向的决定权收回自己手里（它才知道 executor 的真实状态）：
// 要停止就直接在引擎侧停掉，要启动才发这条请求——因为只有页面知道画布上最新的流程。
// 所以这里不再自行判断方向，避免两边 running 有偏差时点「停止」反而又启动一次。
function requestRun() {
  if (store.running) return
  run()
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
  message.success(
    `已录制 ${events.length} 个事件，并生成一个录制步骤（可点顶栏「✂ 拆分录制」拆成可编辑节点）`,
    { duration: 6000 },
  )
  loadFlowToEngine()
}

// ---------- 拆分/打包的布局 ----------
/** 画布可见区域换算成 flow 坐标（用于决定"填多少才叫填满编辑区"）。 */
function viewportFlowHeight(): number {
  let h = 520
  try {
    const d: any = (vf as any)?.dimensions
    const dim = d && typeof d === 'object' && 'value' in d ? d.value : d
    const zoom = Number(vf?.getViewport?.()?.zoom) || 1
    if (dim?.height > 0 && zoom > 0) h = dim.height / zoom
  } catch {
    /* 视口拿不到时用默认值，不影响正确性 */
  }
  return h
}

// 把一段键鼠录制拆成可编辑的流程节点。
// 具体合并规则见 src/lib/macroSplit.ts（纯函数，便于单独验证）。
// nodeArg 省略时作用于当前选中的录制节点（属性面板按钮的用法）。
function splitMacro(nodeArg?: any) {
  const node = nodeArg || selectedNode.value
  if (!node || node.data.stepType !== 'macro') return
  const events: any[] = node.data.params?.events || []
  if (!events.length) {
    message.warning('录制内容为空，无法拆分')
    return
  }

  const speed = node.data.params?.speed ?? 1.0
  const steps = expandPieces(compileMacroPieces(events, speed))
  if (!steps.length) {
    message.warning('没有可转换的事件')
    return
  }

  // 布局：蛇形网格填满编辑区（原来是一条一直往下的长竖线，几十步就拖出去很远，
  // 还会盖住下面的节点、连线也绕）。间隔 >= 80ms 的位置已插入延时节点，保留节奏。
  const macroId = node.id
  const base = node.position || { x: 0, y: 0 }
  const gridH = viewportFlowHeight()
  const { rows, cols } = splitGridLayout(steps.length, gridH)
  const slots = splitGridPositions(steps.length, gridH)
  const created: any[] = []
  const ids: string[] = []
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i]
    const nid = `n${++nodeSeq}`
    created.push({
      id: nid,
      type: 'step',
      position: { x: base.x + slots[i].x, y: base.y + slots[i].y },
      data: { stepType: s.stepType, label: STEP_META[s.stepType].label, params: s.params, once: false },
    })
    ids.push(nid)
  }

  const incoming = edges.value.filter((e) => e.target === macroId)
  const outgoing = edges.value.filter((e) => e.source === macroId)
  nodes.value = nodes.value.filter((nd) => nd.id !== macroId)
  edges.value = edges.value.filter((e) => e.source !== macroId && e.target !== macroId)

  // 方块会盖住原本在它范围内的节点：把被盖住的节点**整体**下移同一个距离，
  // 既让开了位置，又保持它们彼此之间的相对排布不变。
  const blockRight = base.x + (cols - 1) * COL_PITCH + NODE_W
  const blockBottom = base.y + (rows - 1) * ROW_PITCH + NODE_H
  const covered = (p: any) =>
    p && p.x + NODE_W > base.x && p.x < blockRight && p.y + NODE_H > base.y && p.y < blockBottom
  let shift = 0
  for (const nd of nodes.value) {
    if (covered(nd.position)) shift = Math.max(shift, blockBottom + 40 - nd.position.y)
  }
  if (shift > 0) {
    for (const nd of nodes.value) {
      if (covered(nd.position)) nd.position = { x: nd.position.x, y: nd.position.y + shift }
    }
  }

  nodes.value.push(...created)
  // 步骤之间依次相连（i → i+1），蛇形走位保证这些连线都很短、不交叉
  for (let i = 0; i + 1 < ids.length; i++) {
    edges.value.push({ id: `e-${ids[i]}-${ids[i + 1]}`, source: ids[i], target: ids[i + 1], sourceHandle: null })
  }
  // 原本接在录制节点前后的连线，改接到拆分后的首尾节点上
  for (const e of incoming) {
    edges.value.push({ ...e, id: `e-${e.source}-${ids[0]}`, target: ids[0] })
  }
  for (const e of outgoing) {
    edges.value.push({ ...e, id: `e-${ids[ids.length - 1]}-${e.target}`, source: ids[ids.length - 1], sourceHandle: null })
  }

  selectedId.value = ids[0]
  message.success(`已拆分为 ${ids.length} 个可编辑步骤（${cols} 列 × ${rows} 行）`)
  loadFlowToEngine()
  nextTick(() => fitView())
}

// 工具栏上的「✂ 拆分录制」入口。
// 之所以要有它：拆分按钮原先只在「选中录制节点」时出现在右侧属性面板里，
// 不在工具栏、也不在左侧步骤面板，用户根本找不到。现在流程里只要有录制步骤，
// 顶栏就有一个常驻可见的入口。
function splitMacroFromToolbar() {
  const sel = selectedNode.value
  if (sel && sel.data.stepType === 'macro') return splitMacro(sel)
  const list = macroNodes.value
  if (!list.length) {
    message.warning('流程里还没有「键鼠录制」步骤：先点「⏺ 开始录制 (alt+9)」录一段操作')
    return
  }
  if (list.length > 1) {
    message.warning(`流程里有 ${list.length} 个录制步骤，请先在画布上选中要拆分的那个`)
    return
  }
  return splitMacro(list[0])
}

// ---------- 打包合并（拆分的逆操作）----------

// 当前选中的节点。以 selection-change 记下的 id 为准，并用节点自身的 selected
// 标记兜底（不同 Vue Flow 版本对选择状态的同步方式略有差异）。
const selNodes = computed(() => {
  const byId = nodes.value.filter((n) => selIds.value.includes(n.id))
  const flagged = nodes.value.filter((n: any) => n.selected)
  return flagged.length > byId.length ? flagged : byId
})

/** 把选中的节点按连线顺序排成一条链；不是「一条连续链」时返回 null。
 *  判定规则见 src/lib/macroSplit.ts 的 orderChain（纯函数，可单独断言）。 */
function orderSelectedChain(sel: any[]): any[] | null {
  return orderChain(sel, edges.value)
}

/** 打包时真正要用的选中集合：优先向 Vue Flow 要（权威），再退回本地记录。
 *  这样即使响应式刷新慢一拍，按钮亮着就一定能打包。 */
function currentSelection(): any[] {
  try {
    const list = vf?.getSelectedNodes?.()
    if (Array.isArray(list) && list.length >= 2) return list
  } catch {
    /* 忽略 */
  }
  return selNodes.value
}

/** 打包合并：把选中的一串相邻步骤合并成一个「键鼠录制」步骤。 */
function mergeSelected() {
  const sel = currentSelection()
  if (sel.length < 2) {
    message.warning('请先在画布上选中至少 2 个相邻步骤（Shift+拖拽框选，或 Ctrl+点击逐个加选）')
    return
  }
  const chain = orderSelectedChain(sel)
  if (!chain) {
    message.warning('只能打包**连成一串**的相邻步骤：请确认选中的步骤首尾相接、且中间没有分支')
    return
  }
  const badTypes = [...new Set(chain.filter((n) => !canPack(n.data.stepType)).map((n) => n.data.stepType))]
  if (badTypes.length) {
    message.warning(
      '这些步骤没法打包进录制：' +
        badTypes.map((t) => STEP_META[t as StepType]?.label || t).join('、') +
        '（录制只表达键鼠动作）',
    )
    return
  }
  const onceOn = chain.filter((n) => n.data.once)
  if (onceOn.length) {
    message.warning(`选中的步骤里有 ${onceOn.length} 个勾了「单次执行」，录制步骤表达不了，请先取消勾选`)
    return
  }

  const res = packStepsToMacro(
    chain.map((n) => ({ stepType: n.data.stepType, params: n.data.params || {} })),
  )
  if (!res.ok) {
    message.warning(res.badTypes.length ? '选中的步骤里没有可打包的键鼠动作' : '选中的步骤打包后没有任何事件')
    return
  }

  const ids = chain.map((n) => n.id)
  const idSet = new Set(ids)
  const head = chain[0]
  const newId = `n${++nodeSeq}`
  const incoming = edges.value.filter((e) => !idSet.has(e.source) && idSet.has(e.target))
  const outgoing = edges.value.filter((e) => idSet.has(e.source) && !idSet.has(e.target))

  nodes.value = nodes.value.filter((n) => !idSet.has(n.id))
  edges.value = edges.value.filter((e) => !idSet.has(e.source) && !idSet.has(e.target))
  nodes.value.push({
    id: newId,
    type: 'step',
    position: { x: head.position?.x ?? 0, y: head.position?.y ?? 0 },
    data: { stepType: 'macro', label: '键鼠录制', params: { events: res.events, speed: 1.0 }, once: false },
  })
  for (const e of incoming) {
    edges.value.push({ ...e, id: `e-${e.source}-${newId}`, target: newId })
  }
  for (const e of outgoing) {
    edges.value.push({ ...e, id: `e-${newId}-${e.target}`, source: newId, sourceHandle: null })
  }

  selectedId.value = newId
  refreshSelection()
  message.success(`已把 ${chain.length} 个步骤打包成一个录制步骤（${res.events.length} 个键鼠事件）`)
  loadFlowToEngine()
  nextTick(() => fitView())
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

// ---------- 悬浮框（由引擎创建的原生置顶小窗，显示循环进度与当前步骤）----------
const overlayEnabled = ref(false)
const overlayAvailable = ref(true)

async function syncOverlay() {
  try {
    const s = await engine.overlayState()
    overlayEnabled.value = !!s.enabled
    overlayAvailable.value = s.available !== false
  } catch {
    /* 引擎不可达时下个周期再试 */
  }
}

async function toggleOverlay() {
  try {
    const s = await engine.setOverlay(!overlayEnabled.value)
    overlayEnabled.value = !!s.enabled
    overlayAvailable.value = s.available !== false
    message.success(overlayEnabled.value ? '悬浮框已开启' : '悬浮框已关闭')
  } catch (e: any) {
    message.error('切换悬浮框失败：' + e.message)
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
      else if (msg.type === 'overlay') overlayEnabled.value = !!msg.enabled
      else if (msg.type === 'repeat') store.repeat = Number(msg.value) || 1
      else if (msg.type === 'picked') onPicked(msg.x, msg.y)
      else if (msg.type === 'run_request') requestRun()
      else if (msg.type === 'hotkey') toggleScript() // 兼容旧版引擎的启停广播
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
  syncOverlay()
  loadFlowToEngine(true)
  // 顶栏显示引擎版本：确认「当前跑的是哪一版」时不用再翻发布页
  engine
    .health()
    .then((h) => {
      engineVersion.value = String(h?.version || '')
    })
    .catch(() => {
      /* 引擎不可达时留空 */
    })
  // 定时兜底同步流程到引擎（内部已按指纹去重），确保全局快捷键随时可用
  syncTimer = setInterval(() => loadFlowToEngine(), 1000)
  // 定时同步真实运行状态：任何状态广播丢失都能在一秒内自愈，按钮不再卡死
  stateTimer = setInterval(syncRunState, 1000)
  // 撤销/重做的历史起点 + 快捷键
  resetHistory()
  window.addEventListener('keydown', onHistoryKey)
})
onBeforeUnmount(() => {
  destroyed = true
  if (wsRetry) clearTimeout(wsRetry)
  ws?.close()
  if (syncTimer) clearInterval(syncTimer)
  if (stateTimer) clearInterval(stateTimer)
  if (histTimer) clearTimeout(histTimer)
  window.removeEventListener('keydown', onHistoryKey)
})
</script>

<template>
  <div class="editor">
    <header class="topbar">
      <n-button quaternary @click="router.push('/')">← 返回</n-button>
      <div class="brand">🎮 AutoGameTool</div>
      <n-input v-model:value="store.flowName" class="name-input" placeholder="脚本名称" />
      <n-tooltip trigger="hover">
        <template #trigger>
          <n-button size="small" :disabled="!canUndo" @click="undo">↶ 撤销</n-button>
        </template>
        撤销上一步改动（Ctrl+Z）
      </n-tooltip>
      <n-tooltip trigger="hover">
        <template #trigger>
          <n-button size="small" :disabled="!canRedo" @click="redo">↷ 重做</n-button>
        </template>
        重做（Ctrl+Y 或 Ctrl+Shift+Z）
      </n-tooltip>
      <div class="spacer" />
      <span v-if="engineVersion" class="ver-badge" title="引擎版本（界面右上角可确认是否为最新版）">
        v{{ engineVersion }}
      </span>
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
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button
              size="small"
              :type="overlayEnabled ? 'primary' : 'default'"
              :disabled="!overlayAvailable"
              @click="toggleOverlay"
            >
              🪟 悬浮框{{ overlayEnabled ? '已开' : '' }}
            </n-button>
          </template>
          {{ overlayAvailable
            ? '在游戏画面上方置顶显示循环进度与当前步骤（可拖拽，点 ✕ 收起）'
            : '悬浮框不可用：当前运行环境缺少 tkinter' }}
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
      <div class="setting">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button
              size="small"
              type="warning"
              :disabled="!macroNodes.length"
              @click="splitMacroFromToolbar"
            >
              ✂ 拆分录制{{ macroNodes.length > 1 ? ` (${macroNodes.length})` : '' }}
            </n-button>
          </template>
          {{
            macroNodes.length
              ? '把「键鼠录制」步骤拆成可单独编辑的鼠标点击 / 键盘按键 / 延时节点' +
                (macroNodes.length > 1 ? '；流程里有多个录制步骤，先在画布上选中要拆的那个' : '')
              : '流程里还没有「键鼠录制」步骤：先用 ⏺ 开始录制 (alt+9) 录一段操作'
          }}
        </n-tooltip>
      </div>
      <div class="setting">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button size="small" :disabled="selNodes.length < 2" @click="mergeSelected">
              📦 打包合并{{ selNodes.length >= 2 ? ` (${selNodes.length})` : '' }}
            </n-button>
          </template>
          {{
            selNodes.length >= 2
              ? `把选中的 ${selNodes.length} 个相邻步骤合并成一个「键鼠录制」步骤（拆分的逆操作）`
              : '先选中至少 2 个相邻步骤：Shift+拖拽框选，或按住 Ctrl 逐个点击加选'
          }}
        </n-tooltip>
      </div>
    </div>

    <div class="main">
      <aside class="palette">
        <div class="palette-title">步骤类型</div>
        <div v-for="[t, meta] in stepTypes" :key="t" class="palette-item" @click="addStep(t)">
          <span class="palette-icon" :style="{ background: meta.color }">{{ meta.icon }}</span>
          <span>{{ meta.label }}</span>
        </div>
        <div class="palette-hint">
          点击添加步骤<br />拖动节点圆点手动连线<br /><b>Shift+拖拽</b> 框选多个步骤<br /><b>Ctrl+点击</b> 逐个加选
        </div>
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
          @selection-end="refreshSelection"
          @selection-drag="refreshSelection"
          @pane-click="onPaneClick"
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
                共 {{ (selectedNode.data.params.events || []).length }} 个事件（鼠标点击、滚轮、键盘按下/抬起；不再记录鼠标轨迹）
              </p>
            </div>
            <div class="field">
              <label>回放速度：x{{ selectedNode.data.params.speed }}</label>
              <n-slider v-model:value="selectedNode.data.params.speed" :min="0.25" :max="4" :step="0.25" />
            </div>
            <div class="field">
              <label>拆分为可编辑步骤</label>
              <n-popconfirm @positive-click="splitMacro()">
                <template #trigger>
                  <n-button size="small" block type="warning">✂ 拆分为可编辑步骤</n-button>
                </template>
                拆分会把这一步替换成一串「鼠标点击 / 键盘按键 / 滚轮 / 延时」节点，原录制节点将被删除（间隔 ≥80ms 会插入延时以保留节奏）。确定？
              </n-popconfirm>
              <p class="terminate-hint">
                顶栏也有常驻入口「✂ 拆分录制」，不必先选中本节点（流程里只有一个录制步骤时直接生效）。
                想把拆开的步骤再合回去：选中它们后点顶栏「📦 打包合并」。
              </p>
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
              <p class="terminate-hint">
                提示：录制会覆盖当前步骤内容；录制时请切换到目标窗口操作，再次按 alt+9 结束。
                拆分后每个动作都是独立节点，可以单独删除/改坐标/改按键；长按某个键会被化简为单击（如需长按可在其后手动加延时）。
              </p>
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
/* 顶栏版本号：排查「界面里看不到某功能」时用来确认页面是不是最新版 */
.ver-badge {
  font-size: 12px;
  color: #94a3b8;
  border: 1px solid #334155;
  border-radius: 10px;
  padding: 1px 8px;
  white-space: nowrap;
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
