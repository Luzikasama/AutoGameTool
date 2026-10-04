<script setup lang="ts">
/**
 * 单个脚本编辑器（一个标签页一个实例）。
 *
 * 0.1.2 起本组件只负责**一个文档**：节点、连线、撤销历史、脚本名等全部是
 * 实例内的局部状态（每个标签天然独立），文档数据实时镜像进 stores/docs.ts，
 * 供保存、标签标题、子脚本列表使用。
 *
 * 与哪个脚本无关的东西（WebSocket、运行状态、悬浮框、模板/窗口列表、录制状态）
 * 统一由 stores/engine.ts 持有 —— 引擎只允许一条页面连接，每个标签各连一次是错的。
 */
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import { VueFlow, type Connection } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import {
  NAlert,
  NButton,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSlider,
  NSwitch,
  NTooltip,
  useDialog,
  useMessage,
} from 'naive-ui'
import StepNode from '../components/StepNode.vue'
import ScreenCapture from '../components/ScreenCapture.vue'
import ScriptPickerModal from '../components/ScriptPickerModal.vue'
import { engine } from '../api/client'
import { useProjectStore } from '../stores/project'
import { useDocsStore } from '../stores/docs'
import { useEngineStore } from '../stores/engine'
import { useClipboardStore } from '../stores/clipboard'
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
import {
  buildGraph,
  chainText,
  findAnyCycle,
  normalizeScripts,
  ROOT_NODE,
  wouldCreateCycle,
} from '../lib/scriptGraph'
import { extractFragment, materializeFragment } from '../lib/clipFragment'

const props = defineProps<{ docId: string; active: boolean }>()

const project = useProjectStore()
const docs = useDocsStore()
const eng = useEngineStore()
const clip = useClipboardStore()
const message = useMessage()
const dialog = useDialog()

/** 本视图对应的标签 */
const tab = computed(() => docs.tabs.find((t) => t.id === props.docId))
/** 所属根文档的数据（子脚本文档下，元信息如循环轮数/绑定窗口仍取自根脚本） */
const root = computed(() => {
  const t = tab.value
  return t ? docs.getRoot(t.rootId) : undefined
})
const isSub = computed(() => tab.value?.kind === 'sub')

const nodeTypes: any = { step: markRaw(StepNode) }
const stepTypes = Object.entries(STEP_META) as Array<[StepType, { label: string; icon: string; color: string }]>

const nodes = ref<any[]>([])
const edges = ref<any[]>([])
const selectedId = ref<string | null>(null)
// 多选（Vue Flow 内建：空白处左键拖拽框选、Ctrl+点击逐个加选）选中的节点 id。
// 用 selection-change 事件单独记一份，而不是依赖 node.selected —— 打包按钮的
// 可用状态/数量要能跟着选择实时变。
const selIds = ref<string[]>([])
const selectedWinHwnd = ref<number>(0)

// ---------- 文档级元信息（局部持有 + 镜像进 docs store）----------
// 局部持有是为了让模板里的 v-model 正常工作（store 里的文档数据刻意不是响应式的，
// 上万节点的图不需要 Vue 去追），镜像则保证「保存 / 另一个标签读得到」。
const flowName = ref('未命名脚本')
const repeat = ref(1)
const inputMode = ref<'real' | 'simulated'>('real')
const boundWindow = ref<{ hwnd: number; title: string } | null>(null)
const fileScreen = ref<{ width: number; height: number } | null>(null)
const fileWindowRect = ref<WindowInfo['rect'] | null>(null)

/** 本视图编辑的流程是根脚本还是子脚本 */
function flowOfRoot(): { nodes: any[]; edges: any[]; name: string } {
  const r = root.value
  const t = tab.value
  if (!r || !t) return { nodes: [], edges: [], name: '未命名脚本' }
  if (t.kind === 'sub') {
    const s = r.scripts[t.scriptId]
    return s ? { nodes: s.nodes, edges: s.edges, name: s.name } : { nodes: [], edges: [], name: t.scriptId }
  }
  return { nodes: r.nodes, edges: r.edges, name: r.name }
}

/** 把本视图的编辑结果写回文档存储（保存、标签标题、子脚本列表都读它） */
function mirrorToStore() {
  const r = root.value
  const t = tab.value
  if (!r || !t) return
  const flow = flowOfRoot()
  flow.nodes = nodes.value
  flow.edges = edges.value
  if (t.kind === 'sub') {
    const s = r.scripts[t.scriptId]
    if (s) s.name = flowName.value
  } else {
    r.name = flowName.value
    r.repeat = repeat.value
    r.inputMode = inputMode.value
    r.boundWindow = boundWindow.value ? { ...boundWindow.value } : null
    r.screen = fileScreen.value
    r.windowRect = fileWindowRect.value
  }
  docs.patchTab(t.id, { name: flowName.value })
}


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

// 缩放/平移实例
let vf: any = null

// 可缩放面板（日志面板在标签外壳里，全局一份）
const inspectorWidth = ref(280)

const fileInput = ref<HTMLInputElement | null>(null)
let nodeSeq = 0

function currentScreen() {
  const dpr = window.devicePixelRatio || 1
  return {
    width: Math.round(window.screen.width * dpr),
    height: Math.round(window.screen.height * dpr),
  }
}

function currentWindowRect(): WindowInfo['rect'] | null {
  if (!boundWindow.value) return null
  const w = eng.windows.find((x) => x.hwnd === boundWindow.value!.hwnd)
  return w ? w.rect : null
}

function flowWindow() {
  if (!boundWindow.value) return null
  return {
    hwnd: boundWindow.value.hwnd,
    title: boundWindow.value.title,
    rect: fileWindowRect.value ?? currentWindowRect(),
  }
}

const selectedNode = computed(() => nodes.value.find((n) => n.id === selectedId.value) || null)

// 画布上所有「键鼠录制」步骤（工具栏的拆分入口据此决定可用状态）
const macroNodes = computed(() => nodes.value.filter((n) => n.data.stepType === 'macro'))

// ---------- 子脚本（脚本库）----------
/** 当前脚本内的子脚本列表（响应式：改名/新增/删除都要立刻反映到下拉框） */
const scriptList = computed(() => {
  const t = tab.value
  return t ? docs.scriptIndex[t.rootId] || [] : []
})
/** 本视图所属的"脚本身份"：根脚本用 ROOT_NODE，子脚本用它的 id */
const selfScriptId = computed(() => (isSub.value ? tab.value!.scriptId : ROOT_NODE))

/** 子脚本名字（找不到就退回 id，配合"脚本不存在"提示） */
function scriptName(id: string): string {
  const t = tab.value
  if (!t) return id
  const r = docs.getRoot(t.rootId)
  return r?.scripts?.[id]?.name || id
}

/** 当前脚本的调用关系图（含根脚本） */
function callGraph() {
  return buildGraph({ nodes: nodes.value }, root.value?.scripts || {}, true)
}

const scriptPickerVisible = ref(false)
/** 正在挑选/新建子脚本的那个「调用脚本」节点 id（空串表示面板未指向任何节点） */
const scriptPickerTarget = ref('')
/** 「导入已有脚本」用的隐藏 file input */
const subFileInput = ref<HTMLInputElement | null>(null)

/** 子脚本重命名弹窗（与"重命名模板"分开两个弹窗，避免共用一份文本状态互相串） */
const scriptRenameVisible = ref(false)
const scriptRenameId = ref('')
const scriptRenameText = ref('')

/** 某个 script_id 对应的子脚本是否存在（不存在时节点要显示"脚本不存在"）。
 *  读的是响应式的 scriptList，所以 StepNode 里用到它的地方会跟着脚本库变化重绘。 */
function scriptExists(id: string): boolean {
  if (!id) return false
  return scriptList.value.some((s) => s.id === id)
}

// 下发给 StepNode：「调用脚本」节点据此显示"脚本不存在"
provide('scriptExists', scriptExists)

/** 在节点上设置要调用的子脚本（带**编辑时防环**：第一道防线）。 */
function assignScript(node: any, scriptId: string): boolean {
  const t = tab.value
  if (!t || !node) return false
  const graph = callGraph()
  // 准备加一条 self → scriptId：若从 scriptId 出发已经能走回自己，加了就成环
  const cycle = wouldCreateCycle(graph, selfScriptId.value, scriptId)
  if (cycle) {
    const names = new Map(scriptList.value.map((s) => [s.id, s.name] as const))
    names.set(ROOT_NODE, flowName.value)
    message.error(
      `无法调用「${scriptName(scriptId)}」，这会形成循环调用：\n${chainText(cycle, (id) => names.get(id) || id)}\n请修改脚本调用关系。`,
      { duration: 12000 },
    )
    return false
  }
  node.data.params.script_id = scriptId
  node.data.params.name = scriptName(scriptId)
  return true
}

/** 新建一个空白子脚本，并把它挂到指定节点上。 */
function createSubScript(node: any) {
  const t = tab.value
  const r = root.value
  if (!t || !r) return
  const id = docs.newScriptId(t.rootId)
  const name = `子脚本 ${Object.keys(r.scripts).length + 1}`
  docs.putScript(t.rootId, { id, name, nodes: [], edges: [] })
  if (!assignScript(node, id)) {
    // 环检测拒绝（理论上空白脚本不可能成环），把刚建的收回去，别留孤儿
    docs.removeScript(t.rootId, id)
    return
  }
  docs.markDirty(t.rootId)
  docs.openSub(t.rootId, id)
  message.success(`已新建子脚本「${name}」并打开编辑器`)
}

/** 从一个 .agflow 文件导入为子脚本（连同它的子脚本一起搬进来）。 */
function importSubScript(node: any) {
  const t = tab.value
  if (!t) return
  scriptPickerTarget.value = node?.id || ''
  subFileInput.value?.click()
}

function onImportSubFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const t = tab.value
  const r = root.value
  if (!file || !t || !r) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result as string) as FlowFile
      if (data.format !== 'agflow') throw new Error('不是有效的 AutoGameTool 脚本文件')
      const node = nodes.value.find((n) => n.id === scriptPickerTarget.value)
      if (!node) return
      const id = docs.newScriptId(t.rootId)
      const innerName = String(data.name ?? '').trim()
      const fileName = String(file.name || '').replace(/\.agflow$/i, '').trim()
      const name = innerName && innerName !== '未命名脚本' ? innerName : fileName || '导入的脚本'
      docs.putScript(t.rootId, {
        id,
        name,
        nodes: data.nodes || [],
        edges: data.edges || [],
      })
      // 它的子脚本也一并嵌入（保持调用关系），并**重新编号**避免与现有 id 撞车
      const imported = normalizeScripts(data.scripts)
      const idMap = new Map<string, string>()
      for (const s of Object.values(imported)) idMap.set(s.id, docs.newScriptId(t.rootId))
      const remap = (arr: any[]) =>
        (arr || []).map((n: any) =>
          n?.data?.stepType === 'script_call' && idMap.has(n.data.params?.script_id)
            ? {
                ...n,
                data: {
                  ...n.data,
                  params: {
                    ...n.data.params,
                    script_id: idMap.get(n.data.params.script_id),
                    name: imported[n.data.params.script_id]?.name,
                  },
                },
              }
            : n,
        )
      for (const s of Object.values(imported)) {
        docs.putScript(t.rootId, {
          id: idMap.get(s.id) as string,
          name: s.name,
          nodes: remap(s.nodes),
          edges: s.edges || [],
        })
      }
      if (!assignScript(node, id)) {
        for (const nid of idMap.values()) docs.removeScript(t.rootId, nid)
        docs.removeScript(t.rootId, id)
        return
      }
      docs.markDirty(t.rootId)
      message.success(
        `已导入子脚本「${name}」${imported && Object.keys(imported).length ? `（含 ${Object.keys(imported).length} 个下级子脚本）` : ''}`,
      )
    } catch (err: any) {
      message.error('导入失败：' + err.message)
    }
  }
  reader.readAsText(file)
}

/** 把某个子脚本单独导出成 .agflow（它自己也是一份合法脚本）。 */
async function exportSubScript(scriptId: string) {
  const t = tab.value
  const r = root.value
  if (!t || !r) return
  const s = r.scripts[scriptId]
  if (!s) {
    message.warning('这个子脚本不存在')
    return
  }
  const payload = {
    name: s.name,
    repeat: repeat.value,
    input_mode: inputMode.value,
    window: flowWindow(),
    screen: fileScreen.value ?? currentScreen(),
    nodes: s.nodes || [],
    edges: s.edges || [],
    scripts: {},
  }
  const ok = await saveJsonToFile({
    format: 'agflow',
    version: 2,
    ...payload,
  } as FlowFile)
  if (ok) message.success(`已导出子脚本「${s.name}」`)
}

/** 清掉所有指向某个子脚本的调用（删除子脚本时用）。 */
function clearScriptRefs(scriptId: string) {
  for (const n of nodes.value) {
    if (n?.data?.stepType === 'script_call' && n.data.params?.script_id === scriptId) {
      n.data.params.script_id = ''
      n.data.params.name = ''
    }
  }
}

function removeSubScript(scriptId: string) {
  const t = tab.value
  if (!t) return
  const used = nodes.value.filter(
    (n) => n?.data?.stepType === 'script_call' && n.data.params?.script_id === scriptId,
  ).length
  if (used) {
    message.warning(`本脚本里还有 ${used} 处调用它，已一并清空这些调用`)
    clearScriptRefs(scriptId)
  }
  docs.removeScript(t.rootId, scriptId)
  docs.markDirty(t.rootId)
  message.success('子脚本已删除')
}

/** 打开某个子脚本的编辑器标签（已打开则聚焦）。 */
function openScriptTab(scriptId: string) {
  const t = tab.value
  if (!t || !scriptId) return
  docs.openSub(t.rootId, scriptId)
}

/**
 * 双击「调用脚本」节点：直接在新编辑器里打开它指向的子脚本。
 * 还没选子脚本（或指向的已不存在）时，双击等同于打开选择框。
 */
function onNodeDoubleClick(payload: any) {
  const n = payload?.node
  if (!n || n?.data?.stepType !== 'script_call') return
  selectedId.value = n.id
  const sid = n.data?.params?.script_id
  if (sid && scriptExists(sid)) openScriptTab(sid)
  else openScriptPicker()
}

/** 打开调用脚本节点右侧的挑选面板。 */
function openScriptPicker() {
  if (!selectedNode.value || selectedNode.value.data.stepType !== 'script_call') return
  scriptPickerTarget.value = selectedNode.value.id
  scriptPickerVisible.value = true
}

function onScriptPicked(scriptId: string) {
  const node = nodes.value.find((n) => n.id === scriptPickerTarget.value) || selectedNode.value
  if (!node) return
  if (!assignScript(node, scriptId)) return
  scriptPickerVisible.value = false
  docs.markDirty(tab.value?.rootId || '')
}

/** 子脚本改名：同步到「脚本库」、标签标题，以及所有引用它的调用节点的显示名。 */
function renameScript(scriptId: string, name: string) {
  const t = tab.value
  if (!t) return
  const r = docs.getRoot(t.rootId)
  const s = r?.scripts?.[scriptId]
  if (!s) return
  s.name = name
  docs.refreshScriptIndex(t.rootId)
  const subTab = docs.tabs.find((x) => x.kind === 'sub' && x.rootId === t.rootId && x.scriptId === scriptId)
  if (subTab) docs.patchTab(subTab.id, { name })
  for (const n of nodes.value) {
    if (n?.data?.stepType === 'script_call' && n.data.params?.script_id === scriptId) {
      n.data.params.name = name
    }
  }
  docs.markDirty(t.rootId)
}

/** 打开子脚本重命名弹窗（输入框预填当前名，改完同步到所有调用点） */
function openScriptRename(scriptId: string) {
  if (!scriptId) return
  scriptRenameId.value = scriptId
  scriptRenameText.value = scriptName(scriptId)
  scriptRenameVisible.value = true
}

function doScriptRename() {
  const name = scriptRenameText.value.trim()
  if (!scriptRenameId.value || !name) return
  renameScript(scriptRenameId.value, name)
  scriptRenameVisible.value = false
  message.success(`子脚本已改名：${name}`)
}

/** 删除子脚本前先确认：它会连同里面的所有步骤一起消失，而且调用点会被清空。 */
function confirmRemoveSubScript(scriptId: string) {
  const id = String(scriptId || '')
  if (!id) return
  const used = nodes.value.filter(
    (n) => n?.data?.stepType === 'script_call' && n.data.params?.script_id === id,
  ).length
  dialog.warning({
    title: '删除这个子脚本？',
    content:
      `「${scriptName(id)}」会从本脚本里删除，里面的所有步骤一起丢失。` +
      (used ? `本脚本里还有 ${used} 处调用它，那些调用会被一并清空。` : '') +
      '删除子脚本不在撤销范围内（Ctrl+Z 只覆盖画布上的步骤增删改），请先导出备份。',
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => removeSubScript(id),
  })
}

/** 本视图里所有「调用脚本」节点指向的、已不存在的子脚本 id（用于顶部提示条）。 */
const missingScripts = computed(() => {
  // 显式依赖 scriptList：脚本库是 markRaw 的普通对象，不引用一下就观察不到增删
  const known = new Set(scriptList.value.map((s) => s.id))
  const ids = new Set<string>()
  for (const n of nodes.value) {
    if (n?.data?.stepType !== 'script_call') continue
    const id = String(n.data.params?.script_id || '')
    if (id && !known.has(id)) ids.add(id)
  }
  return [...ids]
})

const winOptions = computed(() => [
  { label: '🌐 不绑定（全局）', value: 0 },
  ...eng.windows.map((w) => ({ label: w.title.slice(0, 40), value: w.hwnd })),
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
  // 连点器：interval_ms 是两次点击之间的间隔（频率越低间隔越大）
  autoclick: { x: 0, y: 0, button: 'left', interval_ms: 100, count: 10 },
  // 调用脚本：script_id 是「脚本库」里的稳定标识（不是名字）
  script_call: { script_id: '', name: '' },
}

function metaOf(type: string) {
  return STEP_META[type as StepType] ?? { label: type, icon: '❓', color: '#888' }
}

/** 连点器：把「间隔毫秒」换算成「次/秒」，对着"频率"更好理解 */
function clickRate(intervalMs: number): string {
  const ms = Number(intervalMs)
  if (!ms || ms <= 0) return '不限速（尽可能快）'
  return `约 ${(1000 / ms).toFixed(1)} 次/秒`
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

/** 当前选中集合的 id（以 Vue Flow 实例为准，见 refreshSelection 的注释）。 */
function selectionIds(): string[] {
  const list: any = (vf as any)?.getSelectedNodes
  if (Array.isArray(list) && list.length) return list.map((n: any) => n.id)
  if (selIds.value.length) return [...selIds.value]
  return selectedId.value ? [selectedId.value] : []
}

/** 删除当前选中的单个节点（右侧属性面板的「删除」按钮）。 */
function removeSelected() {
  if (!selectedId.value) return
  const id = selectedId.value
  nodes.value = nodes.value.filter((n) => n.id !== id)
  edges.value = edges.value.filter((e) => e.source !== id && e.target !== id)
  selectedId.value = null
  selIds.value = []
}

/** 批量删除：一次删掉所有选中的流程（工具栏「删除」按钮 / Delete 键）。 */
function deleteSelected() {
  const ids = selectionIds()
  if (!ids.length) {
    message.warning('请先在画布上选中要删除的步骤（左键拖拽框选，或 Ctrl+点击逐个加选）')
    return
  }
  const idSet = new Set(ids)
  nodes.value = nodes.value.filter((n) => !idSet.has(n.id))
  edges.value = edges.value.filter((e) => !idSet.has(e.source) && !idSet.has(e.target))
  selectedId.value = null
  selIds.value = []
  message.success(`已删除 ${ids.length} 个步骤`)
}

// ---------- 复制 / 剪切 / 粘贴（可跨编辑器）----------
// 片段逻辑在 lib/clipFragment.ts（纯函数）；这里只负责「从画布取、往画布放」。
function copySelection(quiet = false): boolean {
  const ids = selectionIds()
  if (!ids.length) {
    if (!quiet) message.warning('请先选中要复制的步骤')
    return false
  }
  const frag = extractFragment(nodes.value, edges.value, ids)
  if (!frag) return false
  clip.put(frag, flowName.value)
  if (!quiet) message.success(`已复制 ${ids.length} 个步骤（可切到另一个编辑器粘贴）`)
  return true
}

function cutSelection() {
  if (!copySelection(true)) {
    message.warning('请先选中要剪切的步骤')
    return
  }
  deleteSelected()
}

/** 粘贴位置：鼠标所在的画布坐标；拿不到就退回选中节点右下角一点。 */
function pasteAnchor(): { x: number; y: number } {
  if (vf && typeof vf.screenToFlowCoordinate === 'function') {
    try {
      const p = vf.screenToFlowCoordinate({ x: mousePos.value.x, y: mousePos.value.y })
      if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) return { x: Math.round(p.x), y: Math.round(p.y) }
    } catch {
      /* ignore */
    }
  }
  const base = selectedNode.value?.position
  return base ? { x: Math.round(base.x + 40), y: Math.round(base.y + 40) } : { x: 80, y: 80 }
}

function pasteClipboard() {
  const frag = clip.take()
  if (!frag) {
    message.warning('剪贴板里还没有内容：先在画布上选中步骤并复制')
    return
  }
  const at = pasteAnchor()
  const { nodes: newNodes, edges: newEdges } = materializeFragment(frag, at, () => `n${++nodeSeq}`)
  nodes.value = [...nodes.value, ...newNodes]
  edges.value = [...edges.value, ...newEdges]
  selectedId.value = newNodes[0]?.id ?? null
  selIds.value = newNodes.map((n) => n.id)
  message.success(`已粘贴 ${newNodes.length} 个步骤${clip.source && clip.source !== flowName.value ? `（来自「${clip.source}」）` : ''}`)
}

// ---------- 画布右键菜单 ----------
// 复制 / 剪切 / 粘贴不再占顶栏，改由「在画布上右键」唤出：
//  · 右键点在节点上 → 复制 / 剪切 / 粘贴（能一次搬走一批，含选中集合内部的连线）
//  · 右键点在空白处 → 只有粘贴，落点就是鼠标位置
// 键盘 Ctrl+C / Ctrl+X / Ctrl+V 依旧可用（见 onHistoryKey）。
//
// 定位用 position: fixed + 鼠标视口坐标，所以菜单放在哪个 DOM 位置都行。
const ctxMenu = ref<{ x: number; y: number; onNode: boolean } | null>(null)
const ctxEl = ref<HTMLElement | null>(null)

const ctxStyle = computed(() => {
  const m = ctxMenu.value
  if (!m) return {}
  // 贴边时往回缩，别让菜单跑出窗口
  const w = 160
  const h = m.onNode ? 128 : 40
  return {
    left: Math.max(6, Math.min(m.x, window.innerWidth - w - 6)) + 'px',
    top: Math.max(6, Math.min(m.y, window.innerHeight - h - 6)) + 'px',
  }
})

function openCtxMenu(x: number, y: number, onNode: boolean) {
  // 粘贴的落点取自 mousePos，右键时把它对齐到按下位置
  mousePos.value = { x, y }
  ctxMenu.value = { x, y, onNode }
}

function closeCtxMenu() {
  ctxMenu.value = null
}

/** 右键落在节点上。不是"选中集合里的成员"就先把它变成唯一选中；
 *  已经在集合里则保留整批 —— 这样框选一批后右键可以直接整批复制。 */
function onNodeContextMenu({ event, node }: any) {
  event?.preventDefault?.()
  event?.stopPropagation?.()
  if (!selectionIds().includes(node.id)) {
    const add = (vf as any)?.addSelectedNodes
    if (typeof add === 'function') add.call(vf, [node])
    selectedId.value = node.id
    refreshSelection()
  } else {
    selectedId.value = node.id
  }
  openCtxMenu(event?.clientX ?? mousePos.value.x, event?.clientY ?? mousePos.value.y, true)
}

/** 右键落在空白画布上：只给「粘贴」。（节点的右键已在 node-context-menu 里拦下） */
function onCanvasContextMenu(e: MouseEvent) {
  if ((e.target as HTMLElement | null)?.closest('.vue-flow__node')) return
  openCtxMenu(e.clientX, e.clientY, false)
}

function ctxAction(fn: () => void) {
  closeCtxMenu()
  fn()
}

// 菜单开着时：点到别处 / 按 Esc 就关掉。
// 用捕获阶段的 pointerdown（而不是 click）是为了"点哪都关"，同时放行菜单内部的点击 ——
// 否则菜单会在 click 派发之前被移除，按钮就永远点不上了。
function onCtxDismiss(e: PointerEvent) {
  const t = e.target as Node | null
  if (t && ctxEl.value?.contains(t)) return
  closeCtxMenu()
}

function onCtxKey(e: KeyboardEvent) {
  if (e.key === 'Escape') closeCtxMenu()
}

watch(ctxMenu, (m) => {
  if (m) {
    window.addEventListener('pointerdown', onCtxDismiss, true)
    window.addEventListener('keydown', onCtxKey, true)
  } else {
    window.removeEventListener('pointerdown', onCtxDismiss, true)
    window.removeEventListener('keydown', onCtxKey, true)
  }
})

// 切换标签 / 关闭本编辑器时别把菜单留在屏幕上
watch(
  () => props.active,
  (on) => {
    if (!on) closeCtxMenu()
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onCtxDismiss, true)
  window.removeEventListener('keydown', onCtxKey, true)
})

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
  selIds.value = []
}

// 刷新多选集合。
// 注意 @vue-flow/core 1.48.2 的 emits 列表里**没有** selectionChange，只有
// selectionStart / selectionDrag / selectionEnd / nodeClick / paneClick，所以这里不监听
// 「选择变化」，而是在这几个真实存在的事件里主动向 Vue Flow 要一次当前选中集合。
//
// 另一个坑：实例上的 getSelectedNodes 是**数组**（store 里的 computed 已被 reactive 解包，
// 类型定义写的是 `getSelectedNodes: GraphNode[]`），**不是函数**。旧代码写成
// `vf.getSelectedNodes()` 会抛 TypeError 并被下面的 catch 吞掉，于是每次都会退回
// 「遍历 nodes 找 selected」这条兜底 —— 而 v-model 的数组未必及时跟得上内部 store，
// 表现就是「明明框选上了，打包按钮却不亮」。
function refreshSelection() {
  const list: any = (vf as any)?.getSelectedNodes
  const ids: string[] = Array.isArray(list)
    ? list.map((n: any) => n.id)
    : nodes.value.filter((n: any) => n.selected).map((n) => n.id)
  selIds.value = ids
  // 让右侧属性面板跟着选择走：
  //  · 全清空 → 面板清空
  //  · 当前面板对象已不在选中集合里（例如刚框选了另一批）→ 换到集合里的第一个
  //  · 面板对象仍在集合里 → 保持不动，多选时面板不会来回跳
  if (ids.length === 0) {
    selectedId.value = null
  } else if (!selectedId.value || !ids.includes(selectedId.value)) {
    selectedId.value = ids[0]
  }
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
    mirrorToStore()
    if (histTimer) clearTimeout(histTimer)
    histTimer = setTimeout(() => pushHistory(), HISTORY_DEBOUNCE_MS)
  },
  { deep: true },
)

// 元信息（脚本名 / 轮数 / 输入方式 / 绑定窗口）也要实时镜像，否则保存时读到旧值
watch([flowName, repeat, inputMode, boundWindow, fileScreen, fileWindowRect], () => {
  if (restoring) return
  mirrorToStore()
})

// 键盘：Ctrl+Z 撤销、Ctrl+Y（或 Ctrl+Shift+Z）重做、Ctrl+C/X/V 复制剪切粘贴、Delete 删除选中。
// 输入框内不拦截：那里让浏览器做原生的文本编辑更符合直觉。
//
// ⚠️ 所有标签的编辑器实例都挂在同一个 window 上，必须只让**当前活动标签**响应，
// 否则在 A 脚本里按 Ctrl+V 会同时粘进 B 脚本。
function onHistoryKey(e: KeyboardEvent) {
  if (!props.active) return
  const t = e.target as HTMLElement | null
  const tag = (t?.tagName || '').toLowerCase()
  const inField = tag === 'input' || tag === 'textarea' || tag === 'select' || !!t?.isContentEditable
  if (inField) return
  const k = e.key.toLowerCase()

  if (e.ctrlKey || e.metaKey) {
    if (e.altKey) return
    if (k === 'z' && !e.shiftKey) {
      e.preventDefault()
      undo()
    } else if (k === 'y' || (k === 'z' && e.shiftKey)) {
      e.preventDefault()
      redo()
    } else if (k === 'c') {
      e.preventDefault()
      copySelection()
    } else if (k === 'x') {
      e.preventDefault()
      cutSelection()
    } else if (k === 'v') {
      e.preventDefault()
      pasteClipboard()
    }
    return
  }

  if (k === 'delete' || k === 'backspace') {
    e.preventDefault()
    deleteSelected()
  }
}

// ---------- 模板 / 坐标拾取 ----------
// 模板列表是全局的（一台机器一份），维护在 engine store 里，多个标签共用一份缓存
function refreshTemplates() {
  return eng.refreshTemplates().then(() => {
    /* 错误已由 store 记入日志 */
  })
}

function openCapture(mode: 'region' | 'point') {
  capMode.value = mode
  capVisible.value = true
}

async function onCaptured(tplId: string) {
  capVisible.value = false
  await eng.refreshTemplates(true)
  const st = selectedNode.value?.data.stepType
  if (st === 'find_image' || st === 'judge') {
    selectedNode.value.data.params.template = tplId
    previewTemplate(tplId)
  }
}

function onPicked(x: number, y: number) {
  if (!pickingVisible.value) return
  pickingVisible.value = false
  const st = selectedNode.value?.data.stepType
  if (selectedNode.value && (st === 'click' || st === 'autoclick')) {
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
    const win = boundWindow.value?.hwnd ?? null
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
function refreshWindows() {
  return eng.refreshWindows()
}

function onWindowChange(hwnd: number) {
  selectedWinHwnd.value = hwnd
  if (!hwnd) {
    boundWindow.value = null
  } else {
    const w = eng.windows.find((x) => x.hwnd === hwnd)
    boundWindow.value = w ? { hwnd: w.hwnd, title: w.title } : null
  }
}

// ---------- 保存 / 加载 ----------
/** 组装成 .agflow 的 JSON（含内嵌的子脚本库）。 */
function buildFile(): FlowFile {
  const screenRef = fileScreen.value ?? currentScreen()
  const windowRef = fileWindowRect.value ?? currentWindowRect()
  const r = root.value
  const subScripts = r ? normalizeScripts(r.scripts) : {}
  return {
    format: 'agflow',
    version: 2,
    name: flowName.value,
    repeat: repeat.value,
    input_mode: inputMode.value,
    window: boundWindow.value ? { ...boundWindow.value, rect: windowRef } : null,
    screen: screenRef,
    nodes: cloneData(nodes.value),
    edges: cloneData(edges.value),
    // 子脚本一并写进同一个文件：脚本拖到别的机器上也能完整跑起来
    scripts: isSub.value ? {} : subScripts,
  }
}

/** 把一份脚本 JSON 存成文件（保存当前脚本 / 导出子脚本共用）。 */
async function saveJsonToFile(data: FlowFile) {
  const json = JSON.stringify(data, null, 2)
  const w = window as any
  const baseName = data.name || '脚本'
  // 优先使用文件系统访问 API：弹出原生保存对话框（可覆盖/另存）
  if (typeof w.showSaveFilePicker === 'function') {
    try {
      const handle = await w.showSaveFilePicker({
        suggestedName: `${baseName}.agflow`,
        types: [{ description: 'AutoGameTool 脚本', accept: { 'application/json': ['.agflow'] } }],
      })
      const writable = await handle.createWritable()
      await writable.write(json)
      await writable.close()
      return true
    } catch (e: any) {
      if (e && e.name === 'AbortError') return false // 用户取消
      // 否则回退到下载
    }
  }
  // 回退：浏览器下载
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${baseName}.agflow`
  a.click()
  URL.revokeObjectURL(url)
  return true
}

async function saveFlow() {
  const data = buildFile()
  const ok = await saveJsonToFile(data)
  if (!ok) return
  fileScreen.value = data.screen ?? null
  fileWindowRect.value = data.window?.rect ?? null
  docs.patchTab(props.docId, { dirty: false })
  message.success('脚本已保存')
}

function triggerLoad() {
  fileInput.value?.click()
}

/**
 * 打开脚本文件。
 *
 * 「类浏览器」语义：**当前标签是空白脚本时直接取代它**，而不是再开一个新页 ——
 * 否则每加载一次就多留一个空白页。空白脚本上已有改动痕迹时，先问要不要保存。
 * 当前标签里本来就有流程（不是空白脚本）时才新开一个标签。
 */
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
      const name =
        innerName && innerName !== '未命名脚本' ? innerName : fileName || innerName || '未命名脚本'
      openLoaded(data, name, !!data.window)
    } catch (err: any) {
      message.error('加载失败：' + err.message)
    }
  }
  reader.readAsText(file)
  input.value = ''
}

/** 当前标签能不能被"取代"：必须是根脚本标签，且画布上还没有任何步骤 */
function canReplaceCurrent() {
  const t = tab.value
  return !!t && t.kind === 'root' && nodes.value.length === 0 && edges.value.length === 0
}

/** 取代前询问：空白脚本上有改动痕迹，要不要先保存 */
function askSaveBeforeReplace(name: string): Promise<'save' | 'discard' | 'cancel'> {
  return new Promise((resolve) => {
    dialog.warning({
      title: '当前空白脚本有改动',
      content: `「${name}」画布上还没有步骤，但有未保存的改动痕迹。加载新脚本前要先保存它吗？`,
      positiveText: '保存',
      negativeText: '不保存',
      onPositiveClick: () => resolve('save'),
      onNegativeClick: () => resolve('discard'),
      onClose: () => resolve('cancel'),
    })
  })
}

/** 加载进来的脚本：落到当前空白标签（取代）或新开一个标签。 */
async function openLoaded(data: FlowFile, name: string, hadWindow: boolean) {
  const init = {
    name,
    repeat: data.repeat || 1,
    inputMode: data.input_mode || 'real',
    // 默认全局：不恢复脚本里保存的窗口绑定。
    // 旧文件里的 hwnd 早就失效，直接恢复会让下拉框显示成一个「空进程」并要求手动重选。
    boundWindow: null,
    screen: data.screen ?? null,
    windowRect: null,
    nodes: data.nodes || [],
    edges: data.edges || [],
    scripts: normalizeScripts(data.scripts),
  }
  const t = tab.value
  let id = ''
  if (canReplaceCurrent() && t) {
    if (t.dirty) {
      const act = await askSaveBeforeReplace(t.name)
      if (act === 'cancel') return
      if (act === 'save') {
        await saveFlow()
        // 保存对话框被取消时（仍处于 dirty）不继续，免得把改动直接丢掉
        if (docs.tabs.find((x) => x.id === t.id)?.dirty) return
      }
    }
    if (docs.replaceRoot(t.id, init, name)) id = t.id
  }
  if (!id) id = docs.openRoot(init, name)
  docs.activate(id)
  // 载入时就存在的循环依赖：先提示，运行时引擎还会再拦一次
  const bad = findAnyCycle(
    buildGraph({ nodes: data.nodes || [] }, normalizeScripts(data.scripts), true),
  )
  if (bad) {
    const names = new Map(
      Object.values(normalizeScripts(data.scripts)).map((s) => [s.id, s.name] as const),
    )
    message.error(`这个脚本里存在循环调用，无法运行：${chainText(bad, (id2) => names.get(id2) || id2)}`, {
      duration: 9000,
    })
  } else {
    message.success(hadWindow ? '脚本已加载（默认全局绑定，未恢复原窗口）' : '脚本已加载')
  }
}

// 全局快捷键的改键界面已挪到「⚙ 设定 → 快捷键」（见 components/SettingsModal.vue）：
// 它属于"设定"而不是"高频操作"，放在顶栏会挤掉真正的常用按钮。
// 「关于」0.1.2 起也移入设定面板（顶栏只留高频操作）。

// ---------- 运行 ----------
/** Vue Flow 节点 → 引擎节点。
 *
 *  引擎只认扁平的 {id, type, params, once}；Vue Flow 往节点上挂的
 *  dimensions / selected / handleBounds 等运行时属性既没用又会让负载明显变大。
 *  根脚本与子脚本共用这一份转换，避免两处各写一遍后悄悄写歪。
 */
function toGraphNodes(ns: any[]) {
  return ns.map((n) => ({
    id: n.id,
    type: (n.data as any)?.stepType,
    params: (n.data as any)?.params || {},
    once: !!(n.data as any)?.once,
  }))
}

function toGraphEdges(es: any[]) {
  return es.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle || null,
  }))
}

function flowGraph() {
  return { nodes: toGraphNodes(nodes.value), edges: toGraphEdges(edges.value) }
}

/** 子脚本库 → 引擎负载用的扁平形式。
 *
 *  文件里存的是 Vue Flow 形式（带坐标，才能还原画布布局），
 *  但**下发引擎时必须是扁平形式**，否则执行器读 node["type"] / node["params"] 全是空，
 *  子脚本会静默地什么都不做。
 */
function graphScripts(): Record<string, any> {
  const r = root.value
  if (!r) return {}
  const out: Record<string, any> = {}
  for (const [id, s] of Object.entries(normalizeScripts(r.scripts))) {
    out[id] = {
      id,
      name: s.name,
      nodes: toGraphNodes(s.nodes || []),
      edges: toGraphEdges(s.edges || []),
    }
  }
  return out
}

/**
 * 交给引擎的完整负载。
 *
 * 子脚本随负载一起下发（`scripts`），由引擎在执行 script_call 节点时就地展开 ——
 * 因此"调用脚本"在运行上与"打包合并"基本等价，区别只是子脚本体面可复用、可单独编辑导出。
 */
function runPayload() {
  return {
    name: flowName.value,
    repeat: repeat.value,
    input_mode: inputMode.value,
    window: flowWindow(),
    screen: fileScreen.value ?? currentScreen(),
    ...flowGraph(),
    scripts: graphScripts(),
  }
}

/** 运行前的静态防环检查（第二道防线；第一道在添加调用关系时）。 */
function checkCycles(): boolean {
  const graph = buildGraph({ nodes: nodes.value }, root.value?.scripts || {}, true)
  const cycle = findAnyCycle(graph)
  if (!cycle) return true
  const t = tab.value
  const reg = t ? docs.getRoot(t.rootId)?.scripts || {} : {}
  const names = new Map(Object.values(normalizeScripts(reg)).map((s) => [s.id, s.name] as const))
  message.error(
    `检测到脚本循环调用，已拒绝运行：\n${chainText(cycle, (id) => names.get(id) || id)}\n请先修改脚本调用关系。`,
    { duration: 12000 },
  )
  return false
}

async function run() {
  if (nodes.value.length === 0) {
    message.warning('请先添加步骤')
    return
  }
  if (!checkCycles()) return
  project.clearLogs()
  try {
    await engine.run(runPayload())
    project.running = true
    if (isSub.value) {
      project.addLog({
        level: 'info',
        message: `单独运行子脚本「${flowName.value}」（使用所属脚本「${root.value?.name || ''}」的循环与窗口设置）`,
        ts: Date.now() / 1000,
      })
    }
  } catch (e: any) {
    message.error('启动失败：' + e.message)
  }
}

async function stop() {
  try {
    const r = await engine.stop()
    // 以引擎返回的真实状态为准：若流程早已结束（假运行），立即解除按钮卡死
    project.running = !!r.running
    project.paused = !!r.paused
  } catch (e: any) {
    message.error('停止失败：' + e.message)
  }
}

// 暂停 / 继续：暂停只是让流程停在下一个检查点，继续后从原地接着跑（不是重新开始）
async function togglePause() {
  try {
    const r = project.paused ? await engine.resume() : await engine.pause()
    project.running = !!r.running
    project.paused = !!r.paused
    if (project.paused) message.info('已暂停（在当前节点结束后生效）')
  } catch (e: any) {
    message.error('切换暂停失败：' + e.message)
  }
}

// 引擎侧的「启动」请求。
// 新版引擎把启停方向的决定权收回自己手里（它才知道 executor 的真实状态）：
// 要停止就直接在引擎侧停掉，要启动才发这条请求——因为只有页面知道画布上最新的流程。
// 所以这里不再自行判断方向，避免两边 running 有偏差时点「停止」反而又启动一次。
function requestRun() {
  if (project.running) return
  run()
}

// ---------- 新建脚本 ----------
// 「新建」= 开一个新的空白标签；但当前标签**本来就是干净的空白脚本**时不再重复开一个，
// 否则连点几次就会攒出一排一模一样的空白页。
function newFlow() {
  if (canReplaceCurrent() && !tab.value?.dirty) return
  docs.openRoot()
}

// ---------- 键鼠录制 ----------
function startRecording() {
  eng.startRecording().catch((e: any) => message.error('启动录制失败：' + e.message))
}

function stopRecording() {
  eng.stopRecording().catch((e: any) => message.error('停止录制失败：' + e.message))
}

function onRecorded(events: any[]) {
  eng.macroRecording = false
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
    message.warning('流程里还没有「键鼠录制」步骤：先点「⏺ 开始录制」录一段操作')
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
 *  这样即使响应式刷新慢一拍，按钮亮着就一定能打包。
 *  同样注意 getSelectedNodes 在实例上是**数组**，不是函数（见 refreshSelection 的注释）。 */
function currentSelection(): any[] {
  const list: any = (vf as any)?.getSelectedNodes
  if (Array.isArray(list) && list.length >= 2) return list
  return selNodes.value
}

/** 打包合并：把选中的一串相邻步骤合并成一个「键鼠录制」步骤。 */
function mergeSelected() {
  const sel = currentSelection()
  if (sel.length < 2) {
    message.warning('请先在画布上选中至少 2 个相邻步骤（左键拖拽框选，或 Ctrl+点击逐个加选）')
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

// 以引擎为唯一事实来源同步运行状态的轮询放在 engine store（eng.syncRunState）：
// 它是全应用一份的状态，多个标签各轮询一次纯属浪费，也容易互相打架。

// ---------- 悬浮框（由引擎创建的原生置顶小窗，显示循环进度与当前步骤）----------
// 开关是全局的（引擎侧一份），状态放在 engine store；按钮在外壳的底部控制条上
// （views/Editor.vue），这里不再重复放一个。

// ---------- 面板缩放 ----------
function startResize(type: 'inspector', e: MouseEvent) {
  e.preventDefault()
  const startX = e.clientX
  const startW = inspectorWidth.value
  const onMove = (ev: MouseEvent) => {
    if (type === 'inspector') {
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

let loadTimer: ReturnType<typeof setTimeout> | null = null

let lastSyncedJson = ''

/**
 * 把当前脚本同步到引擎（供全局快捷键 / 悬浮框按钮启动）。
 *
 * 只有**活动标签**才同步：引擎侧只缓存一份"当前流程"，后台标签也往里写就会互相覆盖，
 * 于是按快捷键启动的可能是另一个脚本。
 */
function loadFlowToEngine(force = false) {
  if (!props.active) return
  const payload = runPayload()
  // 指纹未变化则跳过，避免每秒全量同步空打引擎
  const json = JSON.stringify(payload)
  if (!force && json === lastSyncedJson) return
  lastSyncedJson = json
  engine.loadFlow(payload).catch(() => {
    lastSyncedJson = '' // 失败后下次重试
  })
}

/** 强制重新同步（切回本标签时用：期间流程可能被别的标签改过） */
function resyncFlow() {
  lastSyncedJson = ''
  loadFlowToEngine(true)
}

// 流程变化时同步到引擎，供快捷键 alt+f1 启停（直接用 refs 监听 + 短防抖）
watch(
  [nodes, edges, flowName, repeat, inputMode, boundWindow],
  () => {
    if (loadTimer) clearTimeout(loadTimer)
    loadTimer = setTimeout(loadFlowToEngine, 150)
  },
  { deep: true },
)

let syncTimer: ReturnType<typeof setInterval> | null = null
let stateTimer: ReturnType<typeof setInterval> | null = null

/** 把引擎广播来的页面事件接到本编辑器上。 */
function bindEngineHandlers() {
  eng.setHandlers({
    onRunRequest: requestRun,
    onPicked,
    onRecorded,
    onRepeat: (v) => {
      repeat.value = v
    },
    payload: runPayload,
  })
}

/** 从文档存储里读出初始状态（本编辑器实例第一次挂载时用）。 */
function initFromStore() {
  const t = tab.value
  const r = root.value
  if (!t || !r) return
  const flow = flowOfRoot()
  nodes.value = flow.nodes
  edges.value = flow.edges
  flowName.value = flow.name
  repeat.value = r.repeat
  inputMode.value = r.inputMode
  boundWindow.value = r.boundWindow ? { ...r.boundWindow } : null
  // 默认全局绑定：脚本里存下来的 hwnd 早就失效（旧文件尤其明显），不自动恢复
  selectedWinHwnd.value = 0
  fileScreen.value = r.screen
  fileWindowRect.value = r.windowRect
  // 取现有节点 ID 的最大数字后缀，避免新增节点撞 ID
  nodeSeq = Math.max(
    0,
    ...nodes.value.map((n) => parseInt(String(n.id).replace(/\D/g, ''), 10) || 0),
  )
  mirrorToStore()
  resetHistory()
}

/** 活动标签变化：接管引擎事件、把流程同步给引擎。 */
watch(
  () => props.active,
  (on) => {
    if (on) {
      bindEngineHandlers()
      resyncFlow()
    }
  },
)

/**
 * 文档内容被从外部**就地替换**（「加载」取代了当前空白脚本）。
 *
 * 文档数据放在 store 里且刻意 markRaw（不参与响应式），就地改写它没有任何通知，
 * 所以 store 每次替换都会把一个计数 +1，这里据此重新读一遍。
 */
watch(
  () => docs.rev[props.docId],
  (n) => {
    if (!n) return
    selectedId.value = null
    selIds.value = []
    initFromStore()
    if (props.active) resyncFlow()
  },
)

onMounted(() => {
  initFromStore()
  if (props.active) {
    bindEngineHandlers()
    loadFlowToEngine(true)
  }
  // 定时兜底同步流程到引擎（内部已按指纹去重），确保全局快捷键随时可用
  syncTimer = setInterval(() => loadFlowToEngine(), 1000)
  // 定时同步真实运行状态：任何状态广播丢失都能在一秒内自愈，按钮不再卡死
  stateTimer = setInterval(() => eng.syncRunState(), 1000)
  window.addEventListener('keydown', onHistoryKey)
})
onBeforeUnmount(() => {
  if (syncTimer) clearInterval(syncTimer)
  if (stateTimer) clearInterval(stateTimer)
  if (histTimer) clearTimeout(histTimer)
  window.removeEventListener('keydown', onHistoryKey)
})
</script>

<template>
  <div class="editor">
    <header class="topbar">
      <!-- 左侧：文件操作 + 脚本名。不再放 Logo/品牌名——桌面窗口的标题栏已经写了 AutoGameTool，
           顶栏那块位置留给真正高频的操作。 -->
      <n-button size="small" @click="newFlow">＋ 新建</n-button>
      <n-button size="small" @click="triggerLoad">📂 加载</n-button>
      <n-button size="small" @click="saveFlow">💾 保存</n-button>
      <input ref="fileInput" type="file" accept=".agflow,application/json" style="display: none" @change="onLoadFile" />
      <input
        ref="subFileInput"
        type="file"
        accept=".agflow,application/json"
        style="display: none"
        @change="onImportSubFile"
      />
      <span class="topbar-divider" />
      <n-input
        v-model:value="flowName"
        class="name-input"
        :placeholder="isSub ? '子脚本名称' : '脚本名称'"
      />
      <span v-if="isSub" class="sub-badge">子脚本 · 属于「{{ root?.name }}」</span>
      <div class="spacer" />
      <!-- 右侧：循环轮数紧挨着运行按钮。设定齿轮与悬浮框开关在底部控制条上（views/Editor.vue）。 -->
      <span class="tb-label">循环轮数</span>
      <n-input-number
        v-model:value="repeat"
        :min="1"
        :max="99999"
        size="small"
        style="width: 122px"
      />
      <n-button v-if="!project.running" type="primary" @click="run">▶ 运行</n-button>
      <template v-else>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button :type="project.paused ? 'warning' : 'default'" @click="togglePause">
              {{ project.paused ? '▶ 继续' : '⏸ 暂停' }}
            </n-button>
          </template>
          {{ project.paused ? '从暂停处继续执行' : '在当前节点结束后暂停，继续时从原地接着跑' }}
        </n-tooltip>
        <n-button type="error" @click="stop">■ 停止</n-button>
      </template>
    </header>

    <!-- 脚本浏览（标签）栏：由外壳以 #tabs 传进来，位置就在这里 —— 文件操作行的正下方 -->
    <slot name="tabs" />

    <!-- 脚本库有问题的提示：缺失的子脚本 / 循环依赖都属于"早点说清楚"的事 -->
    <n-alert v-if="missingScripts.length" type="warning" class="pane-alert" :show-icon="true">
      有 {{ missingScripts.length }} 个「调用脚本」步骤指向的子脚本不存在：{{ missingScripts.join('、') }}。
      请重新选择子脚本，或把它从流程里删掉。
    </n-alert>

    <div class="settings-bar">
      <div class="setting">
        <span class="setting-label">输入方式</span>
        <n-radio-group v-model:value="inputMode" size="small">
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
            <n-button size="small" type="error" :disabled="!selNodes.length" @click="deleteSelected">
              🗑 删除{{ selNodes.length > 1 ? ` (${selNodes.length})` : '' }}
            </n-button>
          </template>
          删除所有选中的步骤（Delete 键）。先在画布上左键拖拽框选，或按住 Ctrl 逐个点击加选
        </n-tooltip>
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
      </div>
      <div class="setting">
        <n-button
          size="small"
          :type="eng.macroRecording ? 'error' : 'default'"
          @click="eng.macroRecording ? stopRecording() : startRecording()"
        >
          {{ eng.macroRecording ? '⏹ 停止录制' : '⏺ 开始录制' }}
        </n-button>
      </div>
      <!-- 拆分与打包是一对逆操作，放在同一个不换行容器里，保证它们始终同一行 -->
      <div class="setting nowrap-group">
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button
              size="small"
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
              : '流程里还没有「键鼠录制」步骤：先用「⏺ 开始录制」录一段操作'
          }}
        </n-tooltip>
        <n-tooltip trigger="hover">
          <template #trigger>
            <n-button size="small" :disabled="selNodes.length < 2" @click="mergeSelected">
              📦 打包合并{{ selNodes.length >= 2 ? ` (${selNodes.length})` : '' }}
            </n-button>
          </template>
          {{
            selNodes.length >= 2
              ? `把选中的 ${selNodes.length} 个相邻步骤合并成一个「键鼠录制」步骤（拆分的逆操作）`
              : '先选中至少 2 个相邻步骤：在画布上左键拖拽框选，或按住 Ctrl 逐个点击加选'
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
      </aside>

      <!-- 画布操作（与常见流程图软件一致）：
           · 左键在空白处拖拽 = 框选多个节点
           · 右键拖拽 = 平移画布（panOnDrag=[2]，2 是鼠标右键）
           两者是互斥的：既然左键被框选占用，平移就必须换个按键，否则没法既框选又平移。
           原生菜单照样屏蔽掉，改成我们自己的右键菜单（复制 / 剪切 / 粘贴，见下面的 .ctx-menu）。

           ⚠️ 框选开关的坑（@vue-flow/core 1.48.2）：
           · 这个版本**没有** selectionOnDrag 这个 prop —— 那是 React Flow 的 API，
             传进来只会变成一个没人读的 DOM 属性，什么也不会发生。
           · 真正管事的只有 selectionKeyCode，它的语义是：
               普通按键字符串（默认 'Shift'）= 按住该键才能框选
               true                          = **左键按下即框选**（常开）
               null                          = 彻底禁用框选
             之前传的正是 null，所以左键拖拽只会落到「什么都不做」上。 -->
      <section class="canvas" @mousemove="onCanvasMove" @contextmenu.prevent="onCanvasContextMenu">
        <VueFlow
          v-model:nodes="nodes"
          v-model:edges="edges"
          :node-types="nodeTypes"
          :min-zoom="0.2"
          :max-zoom="2"
          :fit-view-on-init="false"
          :pan-on-drag="[2]"
          :selection-key-code="true"
          multi-selection-key-code="Control"
          @connect="onConnect"
          @node-click="onNodeClick"
          @node-double-click="onNodeDoubleClick"
          @node-context-menu="onNodeContextMenu"
          @selection-start="refreshSelection"
          @selection-drag="refreshSelection"
          @selection-end="refreshSelection"
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

      <!-- 画布右键菜单：定位用 fixed，坐标直接来自鼠标（ctxStyle 里做了贴边收拢） -->
      <div v-if="ctxMenu" ref="ctxEl" class="ctx-menu" :style="ctxStyle" @contextmenu.prevent>
        <template v-if="ctxMenu.onNode">
          <button class="ctx-item" type="button" @click="ctxAction(() => copySelection())">
            <span class="ctx-icon">⧉</span>复制<span class="ctx-key">Ctrl+C</span>
          </button>
          <button class="ctx-item" type="button" @click="ctxAction(cutSelection)">
            <span class="ctx-icon">✂</span>剪切<span class="ctx-key">Ctrl+X</span>
          </button>
        </template>
        <button
          class="ctx-item"
          type="button"
          :disabled="!clip.hasContent"
          @click="ctxAction(pasteClipboard)"
        >
          <span class="ctx-icon">⎘</span>粘贴<span class="ctx-key">Ctrl+V</span>
        </button>
      </div>

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
                  :options="eng.templates"
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

          <template v-else-if="selectedNode.data.stepType === 'autoclick'">
            <div class="field">
              <label>连点坐标（X, Y）</label>
              <div class="row">
                <n-input-number v-model:value="selectedNode.data.params.x" :step="1" style="flex: 1" />
                <n-input-number v-model:value="selectedNode.data.params.y" :step="1" style="flex: 1" />
              </div>
              <n-button size="small" block style="margin-top: 6px" @click="startPicking">🎯 采集点击坐标</n-button>
              <p class="terminate-hint" style="margin-top: 6px">
                点「采集」后切到游戏画面，按拾取快捷键（默认 alt+F3）再单击左键，坐标会自动填进来。
              </p>
            </div>
            <div class="field">
              <label>点击频率：{{ clickRate(selectedNode.data.params.interval_ms) }}</label>
              <n-slider
                v-model:value="selectedNode.data.params.interval_ms"
                :min="0"
                :max="2000"
                :step="1"
                :format-tooltip="(v: number) => `${v} ms（${clickRate(v)}）`"
              />
            </div>
            <div class="field">
              <label>间隔（毫秒，两次点击之间；0 = 不限速）</label>
              <n-input-number
                v-model:value="selectedNode.data.params.interval_ms"
                :min="0"
                :max="600000"
                :step="10"
              />
            </div>
            <div class="field">
              <label>点击次数</label>
              <n-input-number v-model:value="selectedNode.data.params.count" :min="1" :max="100000" :step="10" />
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
              <p class="terminate-hint">
                连点过程中可以随时暂停 / 停止：每次点击前都会查一次状态，长连点也不会卡住「停止」。
                整个过程算作一个步骤，循环轮数照常生效。
              </p>
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
                :type="eng.macroRecording ? 'error' : 'primary'"
                @click="eng.macroRecording ? stopRecording() : startRecording()"
              >
                {{ eng.macroRecording ? '⏹ 停止录制' : '⏺ 重新录制' }}
              </n-button>
            </div>
            <div class="field">
              <p class="terminate-hint">
                提示：录制会覆盖当前步骤内容；录制时请切换到目标窗口操作，再按一次录制快捷键（默认 alt+F2）结束。
                拆分后每个动作都是独立节点，可以单独删除/改坐标/改按键；长按某个键会被化简为单击（如需长按可在其后手动加延时）。
              </p>
            </div>
          </template>

          <!-- ============ 调用脚本（子脚本）============ -->
          <template v-else-if="selectedNode.data.stepType === 'script_call'">
            <div class="field">
              <label>要调用的子脚本</label>
              <div class="row">
                <n-input
                  :value="selectedNode.data.params.script_id ? scriptName(selectedNode.data.params.script_id) : ''"
                  placeholder="尚未选择子脚本"
                  readonly
                  style="flex: 1"
                />
                <n-button size="small" type="primary" @click="openScriptPicker">选择…</n-button>
              </div>
              <p v-if="selectedNode.data.params.script_id && !scriptExists(selectedNode.data.params.script_id)" class="missing-hint">
                ⚠ 这个子脚本已不存在（可能是删除或从外部导入时缺失）。运行时会明确报错，请重新选择。
              </p>
            </div>
            <div v-if="selectedNode.data.params.script_id && scriptExists(selectedNode.data.params.script_id)" class="field">
              <label>子脚本</label>
              <div class="row">
                <n-button size="small" @click="openScriptTab(selectedNode.data.params.script_id)">
                  ✎ 在新编辑器打开
                </n-button>
                <n-button size="small" @click="exportSubScript(selectedNode.data.params.script_id)">
                  ⬇ 导出为文件
                </n-button>
              </div>
              <div class="row" style="margin-top: 6px">
                <n-button size="small" quaternary @click="openScriptRename(selectedNode.data.params.script_id)">
                  改个名字
                </n-button>
                <n-button
                  size="small"
                  ghost
                  type="error"
                  @click="confirmRemoveSubScript(selectedNode.data.params.script_id)"
                >
                  删除这个子脚本
                </n-button>
              </div>
            </div>
            <div class="field">
              <p class="terminate-hint">
                子脚本存在本脚本文件内部（随脚本一起保存），运行时会被<b>就地展开执行</b> ——
                与「打包合并」的运行效果基本相同，差别是子脚本可以单独编辑、单独导出，也能被多个脚本复用。<br />
                子脚本之间不允许循环调用（例如 A 调 B、B 又调回 A），选择时会立刻检测并阻止。
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

    <ScreenCapture
      :show="capVisible"
      :mode="capMode"
      :initial-window="boundWindow?.hwnd ?? null"
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

    <!-- 子脚本改名：改完同步到所有调用它的节点与标签标题 -->
    <n-modal
      v-model:show="scriptRenameVisible"
      preset="card"
      title="重命名子脚本"
      style="width: 420px"
    >
      <div class="rename-body">
        <n-input
          v-model:value="scriptRenameText"
          placeholder="输入新的子脚本名"
          @keyup.enter="doScriptRename"
        />
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <n-button @click="scriptRenameVisible = false">取消</n-button>
          <n-button type="primary" @click="doScriptRename">确定</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal v-model:show="matchVisible" preset="card" title="识别结果" style="width: min(760px, 92vw)">
      <img :src="matchImage" alt="match result" style="max-width: 100%; border-radius: 8px" />
    </n-modal>

    <!-- 子脚本挑选：选已有的 / 新建空白的 / 从文件导入 -->
    <ScriptPickerModal
      v-model:show="scriptPickerVisible"
      :scripts="scriptList"
      :current="selectedNode?.data?.params?.script_id || ''"
      @pick="onScriptPicked"
      @create="createSubScript(nodes.find((n) => n.id === scriptPickerTarget))"
      @import="importSubScript(nodes.find((n) => n.id === scriptPickerTarget))"
      @open="openScriptTab"
    />
  </div>
</template>

<style scoped>
.editor {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-soft);
  flex: none;
}
/* 左侧文件操作与脚本名之间的细分隔线 */
.topbar-divider {
  width: 1px;
  height: 18px;
  background: var(--border);
  flex: none;
}
.name-input {
  max-width: 200px;
}
/* 顶栏右组的字段名（循环轮数） */
.tb-label {
  font-size: 12px;
  color: var(--text-dim);
  white-space: nowrap;
}
.spacer {
  flex: 1;
}
/* 「子脚本」标记：让人一眼知道当前编辑的不是顶层脚本 */
.sub-badge {
  font-size: 12px;
  color: var(--badge-text);
  border: 1px solid var(--badge-border);
  border-radius: 10px;
  padding: 1px 8px;
  white-space: nowrap;
  flex: none;
}
.pane-alert {
  margin: 0;
  border-radius: 0;
  flex: none;
}
/* 调用脚本节点指向的子脚本已不存在 */
.missing-hint {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--warn);
}

.settings-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 6px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  flex-wrap: wrap;
  flex: none;
}
.setting {
  display: flex;
  align-items: center;
  gap: 6px;
}
/* 组内必须同一行（拆分录制 / 打包合并是一对逆操作，拆开看会很别扭） */
.nowrap-group {
  flex-wrap: nowrap;
  white-space: nowrap;
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
  /* 步骤类型多于可用高度时在**自己内部**滚动，不能溢出去压到画布/日志上 */
  min-height: 0;
  overflow-y: auto;
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
  box-shadow: var(--shadow);
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
  background: var(--ctl-hover);
  border-color: var(--border);
}
.ctl svg {
  width: 16px;
  height: 16px;
}

/* ---------- 画布右键菜单 ----------
   position 用 fixed：坐标直接是鼠标的视口坐标，不受画布滚动 / 缩放影响 */
.ctx-menu {
  position: fixed;
  z-index: 60;
  min-width: 150px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel);
  box-shadow: var(--shadow);
}
.ctx-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.ctx-item:hover:not(:disabled) {
  background: var(--hover);
}
.ctx-item:disabled {
  color: var(--text-dim);
  opacity: 0.5;
  cursor: default;
}
.ctx-icon {
  width: 14px;
  text-align: center;
  flex: none;
}
.ctx-key {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 11px;
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
  background: var(--preview-bg);
}
.terminate-hint {
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.5;
}

/* 运行日志面板已移到外壳（views/Editor.vue）的右下角浮层，相关样式随之搬走 */

/* 快捷键改键界面已挪到「⚙ 设定」（SettingsModal.vue），相关样式随之搬走 */

/* 被「只允许一个编辑器窗口」拒绝时的遮罩：此时页面本来也没连上引擎，先挡住误操作 */
.busy-mask {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.45);
}
.busy-card {
  width: min(420px, 88vw);
  padding: 18px 20px;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: var(--bg-panel);
  box-shadow: var(--shadow);
}
.busy-title {
  font-weight: 700;
  margin-bottom: 8px;
}
.busy-text {
  margin: 0 0 14px;
  color: var(--text-dim);
  font-size: 13px;
  line-height: 1.7;
}
</style>
