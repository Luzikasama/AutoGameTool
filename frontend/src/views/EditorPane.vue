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
  NSelect,
  NSwitch,
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
import {
  CATEGORY_META,
  CATEGORY_ORDER,
  GROUP_META,
  GROUP_TYPE,
  NODE_META,
  nodesOfCategory,
  VAR_TYPES,
  type FlowFile,
  type NodeCategory,
  type NodeType,
  type VarItem,
  type WindowInfo,
} from '../types'
import {
  CONDITION_OPS,
  UNARY_OPS,
  defaultsFor,
  fieldVisible,
  mergeWithDefaults,
  nodeOutputs,
  outputVisible,
  NODE_SCHEMA,
  type NodeField,
  type NodeOutput,
} from '../lib/nodeSchema'
import { migrateScript } from '../lib/migrateFlow'
import {
  COL_PITCH,
  compileMacroPieces,
  expandPieces,
  NODE_H,
  NODE_W,
  orderChain,
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
/** 本标签是不是在编辑某个「组合节点」的内部图（双击组合节点进来） */
const isGroup = computed(() => tab.value?.kind === 'group')

const nodeTypes: any = { step: markRaw(StepNode) }
/** 目前 palette 里展开的是哪一类（六大类通过上方切换） */
const paletteCat = ref<NodeCategory>('input')

const nodes = ref<any[]>([])
const edges = ref<any[]>([])
const selectedId = ref<string | null>(null)
// 多选（Vue Flow 内建：空白处左键拖拽框选、Ctrl+点击逐个加选）选中的节点 id。
// 用 selection-change 事件单独记一份，而不是依赖 node.selected —— 合并按钮的
// 可用状态/数量要能跟着选择实时变。
const selIds = ref<string[]>([])
const selectedWinHwnd = ref<number>(0)

// ---------- 文档级元信息（局部持有 + 镜像进 docs store）----------
// 局部持有是为了让模板里的 v-model 正常工作（store 里的文档数据刻意不是响应式的，
// 上万节点的图不需要 Vue 去追），镜像则保证「保存 / 另一个标签读得到」。
const flowName = ref('未命名脚本')
const repeat = ref(1)
const boundWindow = ref<{ hwnd: number; title: string } | null>(null)
const fileScreen = ref<{ width: number; height: number } | null>(null)
const fileWindowRect = ref<WindowInfo['rect'] | null>(null)
/**
 * 本层作用域声明的变量。
 *
 * 局部持有 + 镜像进容器（和 nodes/edges 同一套路）：容器对象是 markRaw 的普通数据，
 * 直接改它不会触发任何响应式刷新，右侧变量面板就永远是打开时那一份。
 */
const variables = ref<VarItem[]>([])

/** 右侧面板当前显示哪一页 */
const inspTab = ref<'params' | 'vars'>('params')

/**
 * 本标签编辑的「流程容器」——节点与连线的实际落点。
 *
 * 三种可能：
 *  · 根脚本标签    → 根文档本身（里面就是主流程）
 *  · 子脚本标签    → 根文档 scripts 里的某个子脚本
 *  · 组合节点标签  → 沿 groupPath 逐层下钻，最终落在某个组合节点的 params 上
 *
 * 之所以要一个统一的"容器"概念：0.1.4 起同一个编辑器要能编辑这三种东西，
 * 而它们的 nodes/edges/name/variables 形状是一样的，只是所在对象不同。
 */
function container(): { kind: 'root' | 'sub' | 'group'; obj: any } | null {
  const t = tab.value
  const r = root.value
  if (!t || !r) return null
  if (t.kind === 'root') return { kind: 'root', obj: r }
  if (t.kind === 'sub') {
    const s = r.scripts[t.scriptId]
    return s ? { kind: 'sub', obj: s } : null
  }
  // 组合节点：起点是"它所在的那份脚本"（根脚本或某个子脚本），然后沿路径下钻
  let arr: any[] = t.scriptId ? r.scripts[t.scriptId]?.nodes || [] : r.nodes
  let params: any = null
  for (const id of t.groupPath || []) {
    const n = arr.find((x: any) => x?.id === id)
    if (!n || n?.data?.nodeType !== GROUP_TYPE) return null
    params = n.data.params || {}
    arr = params.nodes || []
  }
  return params ? { kind: 'group', obj: params } : null
}

/** 本视图的流程是根脚本、子脚本还是组合节点内部（读初始状态用） */
function flowOfRoot(): { nodes: any[]; edges: any[]; name: string; variables: VarItem[] } {
  const c = container()
  const t = tab.value
  if (!c || !t) return { nodes: [], edges: [], name: '未命名脚本', variables: [] }
  return {
    nodes: c.obj.nodes || [],
    edges: c.obj.edges || [],
    name: c.obj.name || (t.kind === 'group' ? '组合节点' : '未命名脚本'),
    variables: Array.isArray(c.obj.variables) ? c.obj.variables : [],
  }
}

/** 把本视图的编辑结果写回文档存储（保存、标签标题、子脚本列表都读它） */
function mirrorToStore() {
  const c = container()
  const t = tab.value
  const r = root.value
  if (!c || !t || !r) return
  c.obj.nodes = nodes.value
  c.obj.edges = edges.value
  c.obj.name = flowName.value
  c.obj.variables = variables.value
  if (c.kind === 'root') {
    r.repeat = repeat.value
    r.boundWindow = boundWindow.value ? { ...boundWindow.value } : null
    r.screen = fileScreen.value
    r.windowRect = fileWindowRect.value
  }
  docs.patchTab(t.id, { name: flowName.value })
}


// 截图/拾取
const capVisible = ref(false)
const capMode = ref<'region' | 'point' | 'rect'>('region')

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

// 画布上所有「键鼠录制」节点（工具栏的拆分入口据此决定可用状态）
const macroNodes = computed(() => nodes.value.filter((n) => n.data.nodeType === 'record'))

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
      if (data.format !== 'agflow') throw new Error('不是有效的 AutoTool 脚本文件')
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
          n?.data?.nodeType === 'script_call' && idMap.has(n.data.params?.script_id)
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
    window: flowWindow(),
    screen: fileScreen.value ?? currentScreen(),
    nodes: s.nodes || [],
    edges: s.edges || [],
    // 子脚本自己的「局部变量」导出成独立文件后，就成了那份文件的全局变量
    variables: Array.isArray(s.variables) ? cloneData(s.variables) : [],
    scripts: {},
  }
  const ok = await saveJsonToFile({
    format: 'agflow',
    version: 3,
    ...payload,
  } as FlowFile)
  if (ok) message.success(`已导出子脚本「${s.name}」`)
}

/** 清掉所有指向某个子脚本的调用（删除子脚本时用）。 */
function clearScriptRefs(scriptId: string) {
  for (const n of nodes.value) {
    if (n?.data?.nodeType === 'script_call' && n.data.params?.script_id === scriptId) {
      n.data.params.script_id = ''
      n.data.params.name = ''
    }
  }
}

function removeSubScript(scriptId: string) {
  const t = tab.value
  if (!t) return
  const used = nodes.value.filter(
    (n) => n?.data?.nodeType === 'script_call' && n.data.params?.script_id === scriptId,
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
 * 打开某个「组合节点」的编辑器标签（双击画布上的组合节点）。
 *
 * 路径是**逐层累加**的：在一张组合节点内部再双击里层的组合节点时，
 * 新标签的 groupPath = 当前标签的路径 + 这个节点 id。
 */
function openGroupTab(node: any) {
  const t = tab.value
  if (!t || !node) return
  const basePath = t.kind === 'group' ? t.groupPath : []
  const path = [...basePath, node.id]
  const name = String(node.data?.params?.name || GROUP_META.label)
  docs.openGroup(t.rootId, t.scriptId, path, name)
}

/**
 * 双击节点：
 *  · 「调用脚本」→ 打开它指向的子脚本
 *  · 「组合节点」→ 打开它内部的编辑界面
 *  · 其它      → 不做任何事（保持和以前一致）
 */
function onNodeDoubleClick(payload: any) {
  const n = payload?.node
  if (!n) return
  selectedId.value = n.id
  if (n?.data?.nodeType === GROUP_TYPE) {
    openGroupTab(n)
    return
  }
  if (n?.data?.nodeType !== 'script_call') return
  const sid = n.data?.params?.script_id
  if (sid && scriptExists(sid)) openScriptTab(sid)
  else openScriptPicker()
}

/** 打开调用脚本节点右侧的挑选面板。 */
function openScriptPicker() {
  if (!selectedNode.value || selectedNode.value.data.nodeType !== 'script_call') return
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
    if (n?.data?.nodeType === 'script_call' && n.data.params?.script_id === scriptId) {
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

/** 删除子脚本前先确认：它会连同里面的所有节点一起消失，而且调用点会被清空。 */
function confirmRemoveSubScript(scriptId: string) {
  const id = String(scriptId || '')
  if (!id) return
  const used = nodes.value.filter(
    (n) => n?.data?.nodeType === 'script_call' && n.data.params?.script_id === id,
  ).length
  dialog.warning({
    title: '删除这个子脚本？',
    content:
      `「${scriptName(id)}」会从本脚本里删除，里面的所有节点一起丢失。` +
      (used ? `本脚本里还有 ${used} 处调用它，那些调用会被一并清空。` : '') +
      '删除子脚本不在撤销范围内（Ctrl+Z 只覆盖画布上的节点增删改），请先导出备份。',
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
    if (n?.data?.nodeType !== 'script_call') continue
    const id = String(n.data.params?.script_id || '')
    if (id && !known.has(id)) ids.add(id)
  }
  return [...ids]
})

const winOptions = computed(() => [
  { label: '🌐 不绑定（全局）', value: 0 },
  ...eng.windows.map((w) => ({ label: w.title.slice(0, 40), value: w.hwnd })),
])

/**
 * 取节点的展示信息（标题 / 图标 / 配色）。
 *
 * 0.1.3 起**颜色不再是每个节点一个**，而是"同类节点同色"——六类各一个色，
 * 一眼就能看出一段流程在干什么（输入=蓝 / 视觉=绿 / 流程=青 / 工具=橙 / 数据=紫 / 系统=灰）。
 */
function metaOf(type: string) {
  if (type === GROUP_TYPE) {
    return { label: GROUP_META.label, icon: GROUP_META.icon, color: GROUP_META.color }
  }
  const m = NODE_META[type as NodeType]
  if (!m) return { label: type, icon: '❓', color: '#888' }
  return { label: m.label, icon: m.icon, color: CATEGORY_META[m.category].color }
}

// ---------- 变量管理（右侧「变量」标签页）----------
/**
 * 当前这一层变量叫什么、给谁看。
 *
 * 0.1.4 的语义：主脚本那份是**全局变量**（整个工作流可见）；
 * 子脚本 / 组合节点各有一份**局部变量**（只在自己内部有效）。
 */
const scopeInfo = computed(() => {
  const k = container()?.kind
  if (k === 'root') {
    return {
      title: '全局变量',
      desc: '整个工作流（含所有子脚本与组合节点）都能读到；在子脚本里要改它得把「变量」节点的作用域选成「全局」。',
    }
  }
  const owner = k === 'sub' ? `子脚本「${flowName.value}」` : `组合节点「${flowName.value}」`
  return {
    title: '局部变量',
    desc: `只在${owner}内部有效（读得到全局，写不外泄）。要跨层共享就用全局变量。`,
  }
})

/** 新增一条变量声明（名称自动避重） */
function addVariable() {
  const used = new Set(variables.value.map((v) => v.name))
  let n = variables.value.length + 1
  while (used.has(`var${n}`)) n += 1
  variables.value = [...variables.value, { name: `var${n}`, type: 'auto', value: '' }]
}

function removeVariable(idx: number) {
  const name = String(variables.value[idx]?.name || '').trim()
  variables.value = variables.value.filter((_, i) => i !== idx)
  // 顺带把节点里指向它的输出绑定清掉，免得留下一个"节点还在写、变量表里却没有"的幽灵
  if (name) renameBindings(name, '')
}

// ---------- 节点输出变量属性（0.1.5）----------
/**
 * 变量在这层分两种，界面里也分开管：
 *
 *  · **用户自建变量** —— 点「＋ 新增变量」自己建的，用来攒中间数据；
 *  · **节点输出变量** —— 节点算出来的东西（找图找到没有 / 坐标 / OCR 文本 / 命令输出…）。
 *
 * 节点**只声明**"我能产出这些"（见 `nodeSchema` 的 `outputs`），**不会**在创建时自动建变量：
 * 挂机脚本里绝大多数输出其实用不到，一建就带一堆变量只是往变量表里倒垃圾。
 * 需要哪个，就在这儿点一下「添加」——这时才真的建变量，并把变量名写回节点参数。
 */
const selectedOutputs = computed<NodeOutput[]>(() => {
  const n = selectedNode.value
  if (!n) return []
  return nodeOutputs(n.data.nodeType).filter((o) => outputVisible(o, n.data.params || {}))
})

/** 某个输出属性当前绑定到哪个变量名（空串 = 用户还没添加）。 */
function outputBound(o: NodeOutput): string {
  const n = selectedNode.value
  return n ? String(n.data.params?.[o.param] ?? '').trim() : ''
}

/**
 * 本层全部节点（含组合节点内部）输出绑定到的变量名集合。
 * 用于判断"删掉这个变量还有没有别人在用"。
 */
function collectOutputBinds(): Set<string> {
  const out = new Set<string>()
  const walk = (arr: any[]) => {
    for (const nd of arr || []) {
      for (const o of nodeOutputs(nd?.data?.nodeType)) {
        const v = String(nd?.data?.params?.[o.param] ?? '').trim()
        // 含 {{}} 的是"按轮次写不同变量"，静态判断不了，跳过
        if (v && !v.includes('{{')) out.add(v)
      }
      const inner = nd?.data?.params?.nodes
      if (Array.isArray(inner)) walk(inner)
    }
  }
  walk(nodes.value)
  return out
}
const outputBoundNames = computed(() => collectOutputBinds())

/** 把某个输出属性添加成本层变量（已有同名变量则直接复用，不重复声明）。 */
function addOutputVar(o: NodeOutput) {
  const n = selectedNode.value
  if (!n || outputBound(o)) return
  const name = String(o.suggest || o.param).trim()
  if (!variables.value.some((v) => String(v.name || '').trim() === name)) {
    variables.value = [...variables.value, { name, type: o.type || 'auto', value: '' }]
  }
  n.data.params[o.param] = name
  markEdited()
  message.success(`已添加变量「${name}」，运行时会写进这个变量`)
}

/** 取消添加：清掉节点参数；若没有别的节点再用它，变量本身也一起删掉。 */
function removeOutputVar(o: NodeOutput) {
  const n = selectedNode.value
  if (!n) return
  const name = outputBound(o)
  n.data.params[o.param] = ''
  markEdited()
  if (!name) return
  if (!collectOutputBinds().has(name)) {
    variables.value = variables.value.filter((v) => String(v.name || '').trim() !== name)
  }
}

/** 变量改名时，把节点里指向旧名字的输出绑定一起改掉（否则绑定会悄悄断掉）。 */
function renameBindings(prev: string, next: string) {
  if (!prev || prev === next) return
  const walk = (arr: any[]) => {
    for (const nd of arr || []) {
      for (const o of nodeOutputs(nd?.data?.nodeType)) {
        const cur = String(nd?.data?.params?.[o.param] ?? '').trim()
        if (cur === prev) nd.data.params[o.param] = next
      }
      const inner = nd?.data?.params?.nodes
      if (Array.isArray(inner)) walk(inner)
    }
  }
  walk(nodes.value)
}

/** 变量名输入框：边打边同步绑定（防止改名把节点输出指到一个不存在的变量上）。 */
function onVarNameInput(idx: number, val: string) {
  const v = variables.value[idx]
  if (!v) return
  const prev = String(v.name || '').trim()
  v.name = val
  renameBindings(prev, String(val || '').trim())
}

/** 变量名重复检查（重名会让后面的覆盖前面的，必须提醒） */
function duplicateVarNames(): string[] {
  const seen = new Set<string>()
  const dup = new Set<string>()
  for (const v of variables.value) {
    const n = String(v.name || '').trim()
    if (!n) continue
    if (seen.has(n)) dup.add(n)
    seen.add(n)
  }
  return [...dup]
}

// ---------- 属性面板（由参数模式表驱动）----------

/** 当前选中节点的参数模式 */
const currentSchema = computed(() => {
  const t = selectedNode.value?.data?.nodeType as NodeType | undefined
  return t ? NODE_SCHEMA[t] : undefined
})

/** 当前参数下应当显示的字段（按字段自己的 showIf 过滤——同一个节点按模式显示不同参数） */
const visibleFields = computed<NodeField[]>(() => {
  const n = selectedNode.value
  const schema = currentSchema.value
  if (!n || !schema) return []
  return schema.fields.filter((f) => fieldVisible(f, n.data.params || {}))
})

/** 条件参数拆开读（左值 / 运算符 / 右值） */
function condPart(key: string, part: 'left' | 'op' | 'right'): any {
  const c = selectedNode.value?.data?.params?.[key]
  if (c && typeof c === 'object') return c[part] ?? ''
  return part === 'op' ? '==' : ''
}

/** 条件参数拆开写；缺字段时补成标准三件套，避免写出半个对象 */
function setCondPart(key: string, part: 'left' | 'op' | 'right', v: any) {
  const n = selectedNode.value
  if (!n) return
  const p = n.data.params
  const c = p[key] && typeof p[key] === 'object' ? { ...p[key] } : { left: '', op: '==', right: '' }
  c[part] = v
  p[key] = c
}

/** 区域参数的显示文本 */
function regionText(key: string): string {
  const r = selectedNode.value?.data?.params?.[key]
  if (!r || typeof r !== 'object') return '未选择区域'
  return `${r.left}, ${r.top}  ·  ${r.width}×${r.height}`
}

/** 正在为哪个参数框选区域（ScreenCapture 回调时写回它） */
const regionFieldKey = ref('')

function openRegionPick(key: string) {
  regionFieldKey.value = key
  capMode.value = 'rect'
  capVisible.value = true
}

function onRect(r: { left: number; top: number; width: number; height: number }) {
  capVisible.value = false
  const n = selectedNode.value
  if (n && regionFieldKey.value) n.data.params[regionFieldKey.value] = { ...r }
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
function addStep(type: NodeType) {
  const meta = metaOf(type)
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
    data: { nodeType: type, label: meta.label, params: defaultsFor(type), once: false },
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
    message.warning('请先在画布上选中要删除的节点（左键拖拽框选，或 Ctrl+点击逐个加选）')
    return
  }
  const idSet = new Set(ids)
  nodes.value = nodes.value.filter((n) => !idSet.has(n.id))
  edges.value = edges.value.filter((e) => !idSet.has(e.source) && !idSet.has(e.target))
  selectedId.value = null
  selIds.value = []
  message.success(`已删除 ${ids.length} 个节点`)
}

// ---------- 复制 / 剪切 / 粘贴（可跨编辑器）----------
// 片段逻辑在 lib/clipFragment.ts（纯函数）；这里只负责「从画布取、往画布放」。
function copySelection(quiet = false): boolean {
  const ids = selectionIds()
  if (!ids.length) {
    if (!quiet) message.warning('请先选中要复制的节点')
    return false
  }
  const frag = extractFragment(nodes.value, edges.value, ids)
  if (!frag) return false
  clip.put(frag, flowName.value)
  if (!quiet) message.success(`已复制 ${ids.length} 个节点（可切到另一个编辑器粘贴）`)
  return true
}

function cutSelection() {
  if (!copySelection(true)) {
    message.warning('请先选中要剪切的节点')
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
    message.warning('剪贴板里还没有内容：先在画布上选中节点并复制')
    return
  }
  const at = pasteAnchor()
  const { nodes: newNodes, edges: newEdges } = materializeFragment(frag, at, () => `n${++nodeSeq}`)
  nodes.value = [...nodes.value, ...newNodes]
  edges.value = [...edges.value, ...newEdges]
  selectedId.value = newNodes[0]?.id ?? null
  selIds.value = newNodes.map((n) => n.id)
  message.success(`已粘贴 ${newNodes.length} 个节点${clip.source && clip.source !== flowName.value ? `（来自「${clip.source}」）` : ''}`)
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
/**
 * 首次装载（新建 / 加载 / 就地替换）期间不要标"未保存"。
 *
 * 装载会把 nodes / flowName / variables 等 ref 重新赋值，随后各 watcher 会照常触发一次；
 * 若不区分，刚打开的脚本会立刻显示成"有改动"。装载完成后的下一个 tick 才置 true。
 */
let ready = false
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
  // 真正的内容改动才标"未保存"（force=true 是新建 / 加载时的初始化，不算改动）
  if (!force) markEdited()
  // 撤销之后又做了新改动 → 丢弃原来的「未来」分支
  if (hIndex.value < history.value.length - 1) history.value = history.value.slice(0, hIndex.value + 1)
  history.value.push(snap)
  if (history.value.length > HISTORY_MAX) history.value.shift()
  hIndex.value = history.value.length - 1
}

/**
 * 标"有未保存的改动"。
 *
 * 本标签 + 所属根脚本标签都要标：子脚本 / 组合节点的内容随根脚本文件一起保存，
 * 所以它们的改动同样让根文件变脏（关标签时的确认弹窗据此触发）。
 */
function markEdited() {
  if (!ready) return
  const t = tab.value
  if (!t) return
  docs.patchTab(t.id, { dirty: true })
  if (t.kind !== 'root') docs.patchTab(t.rootId, { dirty: true })
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

// 元信息（脚本名 / 轮数 / 变量 / 绑定窗口）也要实时镜像，否则保存时读到旧值。
// variables 是数组，改动（改名/改值/增删）要 deep 才观察得到。
watch(
  [flowName, repeat, boundWindow, fileScreen, fileWindowRect, variables],
  () => {
    if (restoring) return
    mirrorToStore()
    markEdited()
  },
  { deep: true },
)

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
    } else if (k === 's') {
      // Ctrl+S 保存（直接写回原文件，不弹路径）；Ctrl+Shift+S 另存为（弹路径）
      e.preventDefault()
      if (e.shiftKey) saveFlowAs()
      else saveFlow()
    }
    return
  }

  if (k === 'delete' || k === 'backspace') {
    e.preventDefault()
    deleteSelected()
  }
}

/**
 * 节点上"放识别模板"的参数键名（没有则为空串）。
 *
 * 0.1.3 里有好几个节点都带模板：图像识别(template)、等待-等图片(template)、
 * 区域分析-对比参考图(reference)。模板的拾取 / 重命名 / 删除都要**同时**照顾到它们，
 * 所以按「参数模式」推导键名，而不是硬编码 `nodeType === 'find_image'`
 * （0.1.2 就是这么写的，拆出「判断」节点后就漏掉了）。
 */
function templateKeyOf(n: any): string {
  const t = n?.data?.nodeType as NodeType | undefined
  const schema = t ? NODE_SCHEMA[t] : undefined
  if (!schema) return ''
  for (const f of schema.fields) {
    if (f.key !== 'template' && f.key !== 'reference') continue
    if (fieldVisible(f, n.data.params || {})) return f.key
  }
  return ''
}

/** 节点是否带坐标参数（能被「拾取坐标」写入） */
function hasXY(n: any): boolean {
  const t = n?.data?.nodeType as NodeType | undefined
  const schema = t ? NODE_SCHEMA[t] : undefined
  if (!schema) return false
  const keys = schema.fields.map((f) => f.key)
  return keys.includes('x') && keys.includes('y')
}

/** 读出节点当前引用的模板 id（无则空串） */
function nodeTemplateId(n: any): string {
  const k = templateKeyOf(n)
  return k ? String(n.data.params[k] || '') : ''
}

// ---------- 模板 / 坐标拾取 ----------
// 模板列表是全局的（一台机器一份），维护在 engine store 里，多个标签共用一份缓存
function refreshTemplates() {
  return eng.refreshTemplates().then(() => {
    /* 错误已由 store 记入日志 */
  })
}


function openCapture(mode: 'region' | 'point' | 'rect') {
  capMode.value = mode
  capVisible.value = true
}

async function onCaptured(tplId: string) {
  capVisible.value = false
  await eng.refreshTemplates(true)
  const node = selectedNode.value
  const key = templateKeyOf(node)
  if (node && key) {
    node.data.params[key] = tplId
    previewTemplate(tplId)
  }
}

function onPicked(x: number, y: number) {
  if (!pickingVisible.value) return
  pickingVisible.value = false
  const node = selectedNode.value
  if (node && hasXY(node)) {
    node.data.params.x = x
    node.data.params.y = y
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
  const key = templateKeyOf(node)
  if (!node || !key) return
  if (!node.data.params[key]) {
    message.warning('请先选择模板')
    return
  }
  try {
    const win = boundWindow.value?.hwnd ?? null
    const r = await engine.match(node.data.params[key], node.data.params.threshold, win)
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
  const id = nodeTemplateId(selectedNode.value) || tplPreviewId.value
  if (!id) return
  renameText.value = id
  renameVisible.value = true
}

async function doRename() {
  const id = nodeTemplateId(selectedNode.value) || tplPreviewId.value
  if (!id || !renameText.value.trim()) return
  const newId = renameText.value.trim()
  try {
    const r = await engine.renameTemplate(id, newId)
    message.success('已重命名：' + r.id)
    renameVisible.value = false
    // 更新所有引用旧模板名的节点
    for (const n of nodes.value) {
      const k = templateKeyOf(n)
      if (k && n.data?.params?.[k] === id) {
        n.data.params[k] = r.id
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
  const id = nodeTemplateId(selectedNode.value) || tplPreviewId.value
  if (!id) return
  try {
    await engine.deleteTemplate(id)
    message.success('已删除模板：' + id)
    tplPreview.value = ''
    tplPreviewId.value = ''
    // 清空所有引用该模板的节点
    for (const n of nodes.value) {
      const k = templateKeyOf(n)
      if (k && n.data?.params?.[k] === id) {
        n.data.params[k] = ''
      }
    }
    await refreshTemplates()
    loadFlowToEngine()
  } catch (e: any) {
    message.error('删除失败：' + e.message)
  }
}

// ---------- 按键录制 ----------
/** 正在为哪个参数键录入按键（属性面板里每个 keys 字段各有自己的录入按钮） */
const keyTarget = ref('')

function startKeyRecord(fieldKey = 'keys') {
  keyTarget.value = fieldKey
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
  const n = selectedNode.value
  if (n && keyTarget.value) {
    n.data.params[keyTarget.value] = keyName
    message.success('已录入按键：' + keyName)
  }
  finishKeyRecord()
}

function finishKeyRecord() {
  keyRecording.value = false
  keyTarget.value = ''
  window.removeEventListener('keydown', onKeyRecordKey)
}

// 选中节点变化时自动预览模板
watch(selectedNode, (n) => {
  const id = n ? nodeTemplateId(n) : ''
  if (id) previewTemplate(id)
  else {
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
/**
 * 组装成 .agflow 的 JSON（含内嵌的子脚本库）。
 *
 * ⚠️ 保存的永远是**整份根脚本**，与当前停在哪个标签无关：0.1.4 起一个根文档下可以有
 * 子脚本标签、组合节点标签，若按"当前标签的 nodes"来写，在子脚本 / 组合节点里点保存
 * 就会把内部图当成主流程写进文件（数据直接被改坏）。所以这里先把当前视图镜像回容器，
 * 再统一取根文档的 nodes/edges/variables。
 */
function buildFile(): FlowFile {
  mirrorToStore()
  const screenRef = fileScreen.value ?? currentScreen()
  const windowRef = fileWindowRect.value ?? currentWindowRect()
  const r = root.value
  const subScripts = r ? normalizeScripts(r.scripts) : {}
  return {
    format: 'agflow',
    version: 3,
    name: r?.name || flowName.value,
    repeat: r?.repeat ?? repeat.value,
    window: r?.boundWindow ? { ...r.boundWindow, rect: windowRef } : null,
    screen: screenRef,
    nodes: cloneData(r?.nodes || []),
    edges: cloneData(r?.edges || []),
    // 主脚本的「全局变量」声明
    variables: cloneData(r?.variables || []),
    // 子脚本一并写进同一个文件：脚本拖到别的机器上也能完整跑起来
    scripts: subScripts,
  }
}

const SCRIPT_FILE_TYPES = [
  { description: 'AutoTool 脚本', accept: { 'application/json': ['.agflow'] } },
]

/** 当前环境有没有文件系统访问 API（桌面壳的 WebView2 / Chrome 系浏览器都有）。 */
function hasFilePicker(): boolean {
  return typeof (window as any).showSaveFilePicker === 'function'
}

function handleLabel(handle: any): string {
  return String(handle?.name || '脚本文件')
}

/** 弹系统「保存」对话框挑位置。用户取消 / 环境不支持 → null。 */
async function pickSaveHandle(suggestedName: string): Promise<any | null> {
  const w = window as any
  if (!hasFilePicker()) return null
  try {
    return await w.showSaveFilePicker({
      suggestedName: `${suggestedName}.agflow`,
      types: SCRIPT_FILE_TYPES,
    })
  } catch (e: any) {
    if (e && e.name === 'AbortError') return null // 用户取消
    message.error('打开保存对话框失败：' + (e?.message || e))
    return null
  }
}

/** 写进一个已有句柄。句柄失效（文件被删 / 权限被撤）时返回 false。 */
async function writeHandle(handle: any, json: string): Promise<boolean> {
  try {
    const writable = await handle.createWritable()
    await writable.write(json)
    await writable.close()
    return true
  } catch {
    return false
  }
}

/** 兜底：浏览器下载（没有文件系统 API 时；下载目录不弹路径，行为上等同"静默保存"）。 */
function downloadJson(baseName: string, json: string): void {
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${baseName}.agflow`
  a.click()
  URL.revokeObjectURL(url)
}

/**
 * 把一份脚本 JSON 存成文件 —— **总是弹路径**（导出子脚本用；语义就是"另存为"）。
 * 主流程的保存 / 另存为走下面的 `saveFlow` / `saveFlowAs`。
 */
async function saveJsonToFile(data: FlowFile): Promise<boolean> {
  const json = JSON.stringify(data, null, 2)
  const baseName = data.name || '脚本'
  if (!hasFilePicker()) {
    downloadJson(baseName, json)
    return true
  }
  const handle = await pickSaveHandle(baseName)
  if (!handle) return false
  if (!(await writeHandle(handle, json))) {
    message.error('写文件失败，请换个位置再试')
    return false
  }
  return true
}

/** 保存收尾：记下这次的屏幕 / 窗口参照，并把这批标签标成"已保存"。 */
function finishSave(data: FlowFile, note: string) {
  fileScreen.value = data.screen ?? null
  fileWindowRect.value = data.window?.rect ?? null
  // 存的是整份根脚本（含子脚本 / 组合节点），所以这些标签都算"已保存"
  const t = tab.value
  if (t) {
    docs.patchTab(t.id, { dirty: false })
    if (t.kind !== 'root') docs.patchTab(t.rootId, { dirty: false })
  }
  message.success(note)
}

/**
 * 保存 / 另存为。
 *
 * 0.1.5 起**「保存」不再弹路径选择**：脚本一旦有了对应的磁盘文件（第一次保存时选过、
 * 或者就是从"加载"打开的），之后每次保存都直接写回那个文件。只有三种情况才会弹：
 *  · 第一次保存（还没有对应文件）；
 *  · 点的是「另存为」；
 *  · 原文件已经被删 / 权限被撤销，写不进去了。
 */
async function doSave(asNew: boolean): Promise<void> {
  const data = buildFile()
  const json = JSON.stringify(data, null, 2)
  const baseName = data.name || '脚本'
  const rootId = tab.value?.rootId || ''

  // 没有文件系统 API：只能下载（不弹路径，等于静默保存到下载目录）
  if (!hasFilePicker()) {
    downloadJson(baseName, json)
    finishSave(data, '已下载到浏览器的下载目录')
    return
  }

  const existing = asNew ? null : docs.getFileHandle(rootId)
  if (existing && (await writeHandle(existing, json))) {
    finishSave(data, `已保存到「${handleLabel(existing)}」`)
    return
  }

  // 没有句柄 / 句柄失效 → 让用户选一次位置
  const picked = await pickSaveHandle(baseName)
  if (!picked) return // 用户取消：什么都不动（标签保持"未保存"）
  docs.setFileHandle(rootId, picked)
  if (!(await writeHandle(picked, json))) {
    docs.setFileHandle(rootId, null)
    message.error('保存失败，请换一个位置再试')
    return
  }
  finishSave(data, `已保存到「${handleLabel(picked)}」`)
}

async function saveFlow() {
  await doSave(false)
}

async function saveFlowAs() {
  await doSave(true)
}

/**
 * 打开脚本。
 *
 * 0.1.5 起优先走系统「打开」对话框（`showOpenFilePicker`）而不是隐藏的 file input：
 * 这样能顺便拿到**文件句柄**，之后点「保存」就直接写回这个文件、不用再选路径。
 * 环境不支持时（或打开失败）退回 file input。
 */
async function triggerLoad() {
  const w = window as any
  if (typeof w.showOpenFilePicker !== 'function') {
    fileInput.value?.click()
    return
  }
  try {
    const [handle] = await w.showOpenFilePicker({ multiple: false, types: SCRIPT_FILE_TYPES })
    const file = await handle.getFile()
    loadFileObject(file, handle)
  } catch (e: any) {
    if (e && e.name === 'AbortError') return // 用户取消
    fileInput.value?.click() // 其它原因（权限等）→ 退回传统方式
  }
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
  // file input 拿不到文件句柄，所以 handle 传 null（下次保存会弹一次路径）
  if (file) loadFileObject(file, null)
  input.value = ''
}

/** 读一个 File 并打开（handle 非空时会被记成"这份脚本对应的磁盘文件"）。 */
function loadFileObject(file: File, handle: any) {
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result as string) as FlowFile
      if (data.format !== 'agflow') throw new Error('不是有效的 AutoTool 脚本文件')
      // 脚本名：优先用文件内记录的名字；若为空或是占位名「未命名脚本」，则退回用文件名。
      // （没改名就保存的文件，内部记的就是占位名，此时用文件名才对应你给脚本起的名字）
      const innerName = String(data.name ?? '').trim()
      const fileName = String(file.name || '').replace(/\.agflow$/i, '').trim()
      const name =
        innerName && innerName !== '未命名脚本' ? innerName : fileName || innerName || '未命名脚本'
      openLoaded(data, name, !!data.window, handle)
    } catch (err: any) {
      message.error('加载失败：' + err.message)
    }
  }
  reader.readAsText(file)
}

/** 当前标签能不能被"取代"：必须是根脚本标签，且画布上还没有任何节点 */
function canReplaceCurrent() {
  const t = tab.value
  return !!t && t.kind === 'root' && nodes.value.length === 0 && edges.value.length === 0
}

/** 取代前询问：空白脚本上有改动痕迹，要不要先保存 */
function askSaveBeforeReplace(name: string): Promise<'save' | 'discard' | 'cancel'> {
  return new Promise((resolve) => {
    dialog.warning({
      title: '当前空白脚本有改动',
      content: `「${name}」画布上还没有节点，但有未保存的改动痕迹。加载新脚本前要先保存它吗？`,
      positiveText: '保存',
      negativeText: '不保存',
      onPositiveClick: () => resolve('save'),
      onNegativeClick: () => resolve('discard'),
      onClose: () => resolve('cancel'),
    })
  })
}

/**
 * 加载进来的脚本：落到当前空白标签（取代）或新开一个标签。
 *
 * `handle`：从系统「打开」对话框打开时带过来的文件句柄 —— 记下来之后，
 * 「保存」就能直接写回同一个文件，不再弹路径。
 */
async function openLoaded(data: FlowFile, name: string, hadWindow: boolean, handle: any = null) {
  // 0.1.2 及更早的脚本在这里升级到 0.1.3 的节点体系：
  // 字段改名（stepType→nodeType）、类型改名（click→mouse…）、以及按规范拆开的
  // 「找图判断」。升级是幂等的，所以再打开一次也不会变样。
  const migrated = migrateScript(data)
  data = migrated.data as FlowFile
  if (migrated.notes.length) {
    message.info('已按 0.1.3 的新规范升级这份脚本：' + migrated.notes.join('；'), { duration: 9000 })
  }
  const init = {
    name,
    repeat: data.repeat || 1,
    // 默认全局：不恢复脚本里保存的窗口绑定。
    // 旧文件里的 hwnd 早就失效，直接恢复会让下拉框显示成一个「空进程」并要求手动重选。
    boundWindow: null,
    screen: data.screen ?? null,
    windowRect: null,
    nodes: data.nodes || [],
    edges: data.edges || [],
    // 0.1.4：主脚本的全局变量声明（老文件没有这个字段，按空处理）
    variables: Array.isArray(data.variables) ? data.variables : [],
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
  // 记住"这份脚本对应磁盘上的哪个文件"：从系统「打开」对话框进来时能拿到句柄，
  // 之后「保存」直接写回它、不再弹路径；用 file input 打开的则忘掉旧句柄。
  docs.setFileHandle(id, handle)
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
    type: (n.data as any)?.nodeType,
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
      // 子脚本自己的「局部变量」：引擎执行到 script_call 时用它初始化子作用域
      variables: Array.isArray(s.variables) ? cloneData(s.variables) : [],
    }
  }
  return out
}

/**
 * 交给引擎的完整负载。
 *
 * 子脚本随负载一起下发（`scripts`），由引擎在执行 script_call 节点时就地展开 ——
 * 因此"调用脚本""组合节点"在运行上与"内联展开"基本等价，区别只是子脚本体面可复用、
 * 可单独编辑导出，而组合节点双击就能进去改。
 */
function runPayload() {
  return {
    name: flowName.value,
    repeat: repeat.value,
    window: flowWindow(),
    screen: fileScreen.value ?? currentScreen(),
    ...flowGraph(),
    // 本层的变量声明（根脚本 = 全局；单独跑子脚本时 = 该子脚本的局部）
    variables: cloneData(variables.value),
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
    message.warning('请先添加节点')
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
    data: { nodeType: 'record', label: '键鼠录制', params: mergeWithDefaults('record', { events, speed: 1.0 }), once: false },
  } as any)
  selectedId.value = id
  message.success(
    `已录制 ${events.length} 个事件，并生成一个录制节点（可点顶栏「✂ 拆分节点」拆成可编辑节点）`,
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
  if (!node || node.data.nodeType !== 'record') return
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
      data: {
        nodeType: s.nodeType,
        label: metaOf(s.nodeType).label,
        params: mergeWithDefaults(s.nodeType, s.params),
        once: false,
      },
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
  // 节点之间依次相连（i → i+1），蛇形走位保证这些连线都很短、不交叉
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
  message.success(`已拆分为 ${ids.length} 个可编辑节点（${cols} 列 × ${rows} 行）`)
  loadFlowToEngine()
  nextTick(() => fitView())
}

// 工具栏上的「✂ 拆分节点」入口。
// 之所以要有它：拆分按钮原先只在「选中录制节点」时出现在右侧属性面板里，
// 不在工具栏、也不在左侧节点面板，用户根本找不到。现在流程里只要有录制节点，
// 顶栏就有一个常驻可见的入口。
function splitMacroFromToolbar() {
  const sel = selectedNode.value
  if (sel && sel.data.nodeType === 'record') return splitMacro(sel)
  const list = macroNodes.value
  if (!list.length) {
    message.warning('流程里还没有「键鼠录制」节点：先点「⏺ 开始录制」录一段操作')
    return
  }
  if (list.length > 1) {
    message.warning(`流程里有 ${list.length} 个录制节点，请先在画布上选中要拆分的那个`)
    return
  }
  return splitMacro(list[0])
}

// ---------- 合并节点（把一段流程收成一个「组合节点」）----------

// 当前选中的节点。以 selection-change 记下的 id 为准，并用节点自身的 selected
// 标记兜底（不同 Vue Flow 版本对选择状态的同步方式略有差异）。
const selNodes = computed(() => {
  const byId = nodes.value.filter((n) => selIds.value.includes(n.id))
  const flagged = nodes.value.filter((n: any) => n.selected)
  return flagged.length > byId.length ? flagged : byId
})

/** 把选中的节点按连线顺序排成一条链；不是「一条连续、干净的链」时返回 null。
 *  判定规则见 src/lib/macroSplit.ts 的 orderChain / isCleanSegment（纯函数，可单独断言）。 */
function orderSelectedChain(sel: any[]): any[] | null {
  return orderChain(sel, edges.value)
}

/** 合并时真正要用的选中集合：优先向 Vue Flow 要（权威），再退回本地记录。
 *  这样即使响应式刷新慢一拍，按钮亮着就一定能合并。
 *  同样注意 getSelectedNodes 在实例上是**数组**，不是函数（见 refreshSelection 的注释）。 */
function currentSelection(): any[] {
  const list: any = (vf as any)?.getSelectedNodes
  if (Array.isArray(list) && list.length >= 2) return list
  return selNodes.value
}

/**
 * 合并节点：把选中的一串相邻节点收成一个「组合节点」。
 *
 * 与 0.1.3 的「打包合并」本质不同：那时是把键鼠动作压回一个录制节点（有损、只认键鼠），
 * 现在是把这段流程**原样**装进一个容器（任意节点都能收，语义不变），双击可进去编辑。
 * 选中链的合法性由 orderChain（含 isCleanSegment）把关：不跨边界分支、尾部最多一条出边。
 */
function mergeSelected() {
  const sel = currentSelection()
  if (sel.length < 2) {
    message.warning('请先在画布上选中至少 2 个相邻节点（左键拖拽框选，或 Ctrl+点击逐个加选）')
    return
  }
  const chain = orderSelectedChain(sel)
  if (!chain) {
    message.warning(
      '只能合并连成一串、且中间没有分支的相邻节点：请确认选中的节点首尾相接，并且没有连到这段之外的线',
    )
    return
  }

  const ids = chain.map((n) => n.id)
  const idSet = new Set(ids)
  const head = chain[0]

  // 内部图：把选中链的节点与它们**内部**的连线原样装进组合节点；
  // 坐标平移到以 head 为原点，免得内部图落在很远的地方（进去编辑时得先 fitView）。
  const baseX = head.position?.x ?? 0
  const baseY = head.position?.y ?? 0
  const innerNodes = chain.map((n) => ({
    id: n.id,
    type: n.type ?? 'step',
    position: {
      x: Math.round((n.position?.x ?? 0) - baseX),
      y: Math.round((n.position?.y ?? 0) - baseY),
    },
    data: cloneData(n.data),
  }))
  const innerEdges = edges.value
    .filter((e) => idSet.has(e.source) && idSet.has(e.target))
    .map((e) => ({ id: e.id, source: e.source, target: e.target, sourceHandle: e.sourceHandle ?? null }))

  const newId = `n${++nodeSeq}`
  const incoming = edges.value.filter((e) => !idSet.has(e.source) && idSet.has(e.target))
  const outgoing = edges.value.filter((e) => idSet.has(e.source) && !idSet.has(e.target))

  nodes.value = nodes.value.filter((n) => !idSet.has(n.id))
  edges.value = edges.value.filter((e) => !idSet.has(e.source) && !idSet.has(e.target))
  nodes.value.push({
    id: newId,
    type: 'step',
    position: { x: baseX, y: baseY },
    data: {
      nodeType: GROUP_TYPE,
      label: GROUP_META.label,
      params: mergeWithDefaults(GROUP_TYPE, {
        name: GROUP_META.label,
        nodes: innerNodes,
        edges: innerEdges,
        variables: [],
      }),
      once: false,
    },
  } as any)
  for (const e of incoming) {
    edges.value.push({ ...e, id: `e-${e.source}-${newId}`, target: newId })
  }
  for (const e of outgoing) {
    edges.value.push({ ...e, id: `e-${newId}-${e.target}`, source: newId, sourceHandle: null })
  }

  selectedId.value = newId
  refreshSelection()
  message.success(`已把 ${chain.length} 个节点合并成一个「组合节点」（双击可进入编辑）`)
  loadFlowToEngine()
  nextTick(() => fitView())
}

/**
 * 取消组合：把「组合节点」拆回它内部的那串节点（合并节点的逆操作）。
 *
 * 内部节点 id 一律**重新编号**再放回画布：组合节点的内部图可能在别的标签里被编辑过、
 * 加过新节点，直接沿用原 id 有和画布上现有节点撞车的风险。连线按 id 映射同步重写。
 */
function unmergeGroup(node?: any) {
  const grp = node || selectedNode.value
  if (!grp || grp.data?.nodeType !== GROUP_TYPE) return
  const params = grp.data.params || {}
  const innerNodes: any[] = Array.isArray(params.nodes) ? params.nodes : []
  const innerEdges: any[] = Array.isArray(params.edges) ? params.edges : []
  if (!innerNodes.length) {
    message.warning('这个组合节点里还没有节点')
    return
  }

  const base = grp.position || { x: 0, y: 0 }
  const idMap = new Map<string, string>()
  const created = innerNodes.map((n) => {
    const nid = `n${++nodeSeq}`
    idMap.set(n.id, nid)
    return {
      id: nid,
      type: n.type ?? 'step',
      position: {
        x: Math.round(base.x + (n.position?.x ?? 0)),
        y: Math.round(base.y + (n.position?.y ?? 0)),
      },
      data: cloneData(n.data),
    }
  })

  const incoming = edges.value.filter((e) => e.target === grp.id)
  const outgoing = edges.value.filter((e) => e.source === grp.id)
  nodes.value = nodes.value.filter((n) => n.id !== grp.id)
  edges.value = edges.value.filter((e) => e.source !== grp.id && e.target !== grp.id)

  nodes.value.push(...created)
  // 内部连线（id 一并重写，避免和画布上已有边撞 id）
  for (const e of innerEdges) {
    const s = idMap.get(e.source)
    const t = idMap.get(e.target)
    if (s && t) edges.value.push({ id: `e-${s}-${t}`, source: s, target: t, sourceHandle: e.sourceHandle ?? null })
  }
  // 原来连到组合节点上的线，改接到内部图的首个节点 / 末尾节点
  // —— 用「无内部入边 / 无内部出边」判定首尾，不依赖内部图是否是一条直链
  const hasInnerIn = new Set(innerEdges.map((e) => e.target))
  const hasInnerOut = new Set(innerEdges.map((e) => e.source))
  const entryId = idMap.get((innerNodes.find((n) => !hasInnerIn.has(n.id)) || innerNodes[0]).id)!
  const exitId = idMap.get(
    (innerNodes.find((n) => !hasInnerOut.has(n.id)) || innerNodes[innerNodes.length - 1]).id,
  )!
  for (const e of incoming) edges.value.push({ ...e, id: `e-${e.source}-${entryId}`, target: entryId })
  for (const e of outgoing) edges.value.push({ ...e, id: `e-${exitId}-${e.target}`, source: exitId, sourceHandle: null })

  selectedId.value = entryId
  refreshSelection()
  message.success(`已取消组合，拆回 ${created.length} 个节点`)
  loadFlowToEngine()
  nextTick(() => fitView())
}

// 以引擎为唯一事实来源同步运行状态的轮询放在 engine store（eng.syncRunState）：
// 它是全应用一份的状态，多个标签各轮询一次纯属浪费，也容易互相打架。

// ---------- 悬浮框（由引擎创建的原生置顶小窗，显示循环进度与当前节点）----------
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
  [nodes, edges, flowName, repeat, boundWindow, variables],
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
  variables.value = flow.variables
  repeat.value = r.repeat
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
  // 装载触发的那些 watcher 跑完之前，不把这一轮赋值当成"用户改动"
  ready = false
  nextTick(() => {
    ready = true
  })
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
      <!-- 左侧：文件操作 + 脚本名。不再放 Logo/品牌名——桌面窗口的标题栏已经写了 AutoTool，
           顶栏那块位置留给真正高频的操作。 -->
      <n-button size="small" @click="newFlow">＋ 新建</n-button>
      <n-button size="small" @click="triggerLoad">📂 加载</n-button>
      <n-button size="small" @click="saveFlow">💾 保存</n-button>
      <n-button size="small" @click="saveFlowAs">📄 另存为</n-button>
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
        :placeholder="isSub ? '子脚本名称' : isGroup ? '组合节点名称' : '脚本名称'"
      />
      <span v-if="isSub" class="sub-badge">子脚本 · 属于「{{ root?.name }}」</span>
      <span v-else-if="isGroup" class="sub-badge">组合节点 · 属于「{{ root?.name }}」</span>
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
        <n-button :type="project.paused ? 'warning' : 'default'" @click="togglePause">
          {{ project.paused ? '▶ 继续' : '⏸ 暂停' }}
        </n-button>
        <n-button type="error" @click="stop">■ 停止</n-button>
      </template>
    </header>

    <!-- 脚本浏览（标签）栏：由外壳以 #tabs 传进来，位置就在这里 —— 文件操作行的正下方 -->
    <slot name="tabs" />

    <!-- 脚本库有问题的提示：缺失的子脚本 / 循环依赖都属于"早点说清楚"的事 -->
    <n-alert v-if="missingScripts.length" type="warning" class="pane-alert" :show-icon="true">
      有 {{ missingScripts.length }} 个「调用脚本」节点指向的子脚本不存在：{{ missingScripts.join('、') }}。
      请重新选择子脚本，或把它从流程里删掉。
    </n-alert>

    <div class="settings-bar">
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
        <n-button size="small" type="error" :disabled="!selNodes.length" @click="deleteSelected">
          🗑 删除{{ selNodes.length > 1 ? ` (${selNodes.length})` : '' }}
        </n-button>
        <n-button size="small" :disabled="!canUndo" @click="undo">↶ 撤销</n-button>
        <n-button size="small" :disabled="!canRedo" @click="redo">↷ 重做</n-button>
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
      <!-- 拆分（录制 → 节点）与合并（选中 → 组合节点）是两种"整段流程的整理"操作，
           放在同一个不换行容器里，保证它们始终同一行。 -->
      <div class="setting nowrap-group">
        <n-button
          size="small"
          :disabled="!macroNodes.length"
          @click="splitMacroFromToolbar"
        >
          ✂ 拆分节点{{ macroNodes.length > 1 ? ` (${macroNodes.length})` : '' }}
        </n-button>
        <n-button size="small" :disabled="selNodes.length < 2" @click="mergeSelected">
          📦 合并节点{{ selNodes.length >= 2 ? ` (${selNodes.length})` : '' }}
        </n-button>
      </div>
    </div>

    <div class="main">
      <aside class="palette">
        <div class="palette-title">节点</div>
        <!-- 六大类：上方切换类目，下方列出该类目的节点。
             类目按钮在选中时用该类颜色描边，和画布上节点的配色一一对应。 -->
        <div class="cat-tabs">
          <button
            v-for="c in CATEGORY_ORDER"
            :key="c"
            type="button"
            class="cat-tab"
            :class="{ active: paletteCat === c }"
            :style="paletteCat === c ? { borderColor: CATEGORY_META[c].color, color: CATEGORY_META[c].color } : undefined"
            @click="paletteCat = c"
          >
            <span class="cat-tab-icon">{{ CATEGORY_META[c].icon }}</span>
            <span class="cat-tab-label">{{ CATEGORY_META[c].label }}</span>
          </button>
        </div>
        <div class="palette-cat-desc">{{ CATEGORY_META[paletteCat].desc }}</div>
        <div
          v-for="[t, meta] in nodesOfCategory(paletteCat)"
          :key="t"
          class="palette-item"
          @click="addStep(t)"
        >
          <span class="palette-icon" :style="{ background: CATEGORY_META[meta.category].color }">{{ meta.icon }}</span>
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
          <div>从左侧点击节点开始搭建脚本流程</div>
        </div>

        <div class="flow-controls">
          <button class="ctl" @click="zoomIn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="11" y1="8" x2="11" y2="14" /><line x1="8" y1="11" x2="14" y2="11" /></svg></button>
          <button class="ctl" @click="zoomOut"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /><line x1="8" y1="11" x2="14" y2="11" /></svg></button>
          <button class="ctl" @click="fitView"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3" /><path d="M21 8V5a2 2 0 0 0-2-2h-3" /><path d="M3 16v3a2 2 0 0 0 2 2h3" /><path d="M16 21h3a2 2 0 0 0 2-2v-3" /></svg></button>
          <button class="ctl" @click="pan(120, 0)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg></button>
          <button class="ctl" @click="pan(-120, 0)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" /></svg></button>
          <button class="ctl" @click="pan(0, 120)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="19" x2="12" y2="5" /><polyline points="5 12 12 5 19 12" /></svg></button>
          <button class="ctl" @click="pan(0, -120)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19" /><polyline points="19 12 12 19 5 12" /></svg></button>
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
        <!-- 右侧这块区域由两个标签页共用：参数配置 / 变量管理（0.1.4 起） -->
        <div class="insp-tabs">
          <button
            type="button"
            class="insp-tab"
            :class="{ active: inspTab === 'params' }"
            @click="inspTab = 'params'"
          >
            参数
          </button>
          <button
            type="button"
            class="insp-tab"
            :class="{ active: inspTab === 'vars' }"
            @click="inspTab = 'vars'"
          >
            变量
          </button>
        </div>

        <!-- ============ 参数页 ============ -->
        <template v-if="inspTab === 'params'">
        <template v-if="selectedNode">
          <div class="inspector-head">
            <span class="inspector-title">
              {{ metaOf(selectedNode.data.nodeType).icon }}
              {{ metaOf(selectedNode.data.nodeType).label }}
            </span>
            <n-button size="tiny" quaternary type="error" @click="removeSelected">删除</n-button>
          </div>

          <!-- ============ 组合节点（0.1.4）============
               它不属于输入 / 处理 / 输出的任何一类，只是一个"流程容器"：
               单击选中即可在这里改名字等属性，双击进入内部编辑。 -->
          <template v-if="selectedNode.data.nodeType === GROUP_TYPE">
            <div class="field">
              <label>名称</label>
              <n-input v-model:value="selectedNode.data.params.name" :placeholder="GROUP_META.label" />
              <p class="terminate-hint">这个名字只用于显示，不影响执行。</p>
            </div>
            <div class="field">
              <label>内容</label>
              <p class="terminate-hint">
                里面装着 {{ (selectedNode.data.params.nodes || []).length }} 个节点 ·
                {{ (selectedNode.data.params.edges || []).length }} 条连线 ·
                {{ (selectedNode.data.params.variables || []).length }} 个局部变量。
              </p>
            </div>
            <div class="field">
              <n-button size="small" block type="primary" @click="openGroupTab(selectedNode)">
                🧩 进入编辑（也可直接双击画布上的它）
              </n-button>
            </div>
            <div class="field">
              <n-button size="small" block type="warning" @click="unmergeGroup()">
                ↩ 取消组合（拆回原节点）
              </n-button>
            </div>
            <div class="field">
              <p class="terminate-hint">
                组合节点只是个流程容器，运行时会像普通节点一样被就地展开执行，不属于输入 / 处理 / 输出的任何一类。
                它内部有自己的「局部变量」，在顶部切到「变量」页管理。
              </p>
            </div>
          </template>

          <!-- ============ 普通节点 ============ -->
          <template v-else>
          <template v-if="!['judge', 'terminate'].includes(selectedNode.data.nodeType)">
            <div class="field">
              <label>单次执行（仅第一轮循环）</label>
              <n-switch v-model:value="selectedNode.data.once" />
            </div>
          </template>

          <!-- ============ 参数面板 ============
               0.1.3 起不再为每个节点手写一段 v-if，而是由 lib/nodeSchema.ts 的
               参数模式表驱动（字段类型 → 控件）。新增节点只要往模式表里加一条即可，
               默认值 / 面板 / 节点摘要 / 迁移补参全部同源，不会再出现"三处各写一遍"。 -->
          <div v-if="currentSchema?.help" class="schema-help">{{ currentSchema.help }}</div>

          <template v-for="f in visibleFields" :key="f.key">
            <!-- 文本 -->
            <div v-if="f.type === 'text'" class="field">
              <label>{{ f.label }}</label>
              <n-input v-model:value="selectedNode.data.params[f.key]" :placeholder="f.placeholder" />
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 多行文本 -->
            <div v-else-if="f.type === 'textarea'" class="field">
              <label>{{ f.label }}</label>
              <n-input
                v-model:value="selectedNode.data.params[f.key]"
                type="textarea"
                :rows="3"
                :placeholder="f.placeholder"
              />
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 命令行 -->
            <div v-else-if="f.type === 'command'" class="field">
              <label>{{ f.label }}</label>
              <n-input
                v-model:value="selectedNode.data.params[f.key]"
                type="textarea"
                :rows="3"
                class="mono"
                placeholder="要执行的命令，支持 {{变量名}}"
              />
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 数字 -->
            <div v-else-if="f.type === 'number'" class="field">
              <label>{{ f.label }}</label>
              <n-input-number
                v-model:value="selectedNode.data.params[f.key]"
                :min="f.min"
                :max="f.max"
                :step="f.step ?? 1"
              />
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 开关 -->
            <div v-else-if="f.type === 'switch'" class="field">
              <label>{{ f.label }}</label>
              <n-switch v-model:value="selectedNode.data.params[f.key]" />
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 下拉 -->
            <div v-else-if="f.type === 'select'" class="field">
              <label>{{ f.label }}</label>
              <n-select v-model:value="selectedNode.data.params[f.key]" :options="f.options || []" />
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 颜色 -->
            <div v-else-if="f.type === 'color'" class="field">
              <label>{{ f.label }}</label>
              <div class="row">
                <input v-model="selectedNode.data.params[f.key]" type="color" class="color-input" />
                <n-input v-model:value="selectedNode.data.params[f.key]" style="flex: 1" />
              </div>
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 按键（点「录制」后按下组合键录入） -->
            <div v-else-if="f.type === 'keys'" class="field">
              <label>{{ f.label }}</label>
              <div class="row">
                <n-input :value="selectedNode.data.params[f.key]" placeholder="未设置" readonly style="flex: 1" />
                <n-button
                  size="small"
                  :type="keyRecording ? 'error' : 'primary'"
                  @click="keyRecording ? finishKeyRecord() : startKeyRecord(f.key)"
                >
                  {{ keyRecording ? '按下按键…' : '录制' }}
                </n-button>
              </div>
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 条件：左值 / 运算符 / 右值 -->
            <div v-else-if="f.type === 'condition'" class="field">
              <label>{{ f.label }}</label>
              <div class="cond-row">
                <n-input
                  :value="condPart(f.key, 'left')"
                  placeholder="左值（变量名）"
                  @update:value="(v: string) => setCondPart(f.key, 'left', v)"
                />
                <n-select
                  :value="condPart(f.key, 'op')"
                  :options="CONDITION_OPS"
                  class="cond-op"
                  @update:value="(v: string) => setCondPart(f.key, 'op', v)"
                />
                <n-input
                  v-if="!UNARY_OPS.includes(condPart(f.key, 'op'))"
                  :value="condPart(f.key, 'right')"
                  placeholder="右值"
                  @update:value="(v: string) => setCondPart(f.key, 'right', v)"
                />
              </div>
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 识别模板 -->
            <div v-else-if="f.type === 'template'" class="field">
              <label>{{ f.label }}</label>
              <div class="row">
                <n-select
                  v-model:value="selectedNode.data.params[f.key]"
                  :options="eng.templates"
                  placeholder="选择模板"
                  filterable
                  style="flex: 1"
                  @update:value="previewTemplate"
                />
                <n-button size="small" @click="openCapture('region')">截取</n-button>
              </div>
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>

            <!-- 矩形区域 -->
            <div v-else-if="f.type === 'region'" class="field">
              <label>{{ f.label }}</label>
              <div class="row">
                <span class="region-text">{{ regionText(f.key) }}</span>
                <n-button size="small" @click="openRegionPick(f.key)">框选</n-button>
                <n-button size="small" quaternary @click="selectedNode.data.params[f.key] = null">清除</n-button>
              </div>
              <p v-if="f.hint" class="terminate-hint">{{ f.hint }}</p>
            </div>
          </template>

          <!-- 带坐标参数的节点：拾取屏幕坐标 -->
          <div v-if="hasXY(selectedNode)" class="field">
            <n-button size="small" block @click="startPicking">🎯 拾取屏幕坐标</n-button>
            <p class="terminate-hint" style="margin-top: 6px">
              点「拾取」后切到目标画面，按拾取快捷键（默认 alt+F3）再单击左键，坐标会自动填进来。
            </p>
          </div>

          <!-- 带识别模板的节点：预览 / 重命名 / 删除 / 测试识别 -->
          <template v-if="nodeTemplateId(selectedNode)">
            <div v-if="tplPreview" class="field">
              <label>模板预览</label>
              <img :src="tplPreview" class="tpl-preview" alt="模板预览" />
              <div class="row" style="margin-top: 6px">
                <n-button size="tiny" @click="openRename">重命名</n-button>
                <n-button size="tiny" type="error" @click="doDeleteTemplate">删除</n-button>
              </div>
            </div>
            <div class="field">
              <n-button size="small" block @click="testMatch">测试识别</n-button>
            </div>
          </template>

          <template v-else-if="selectedNode.data.nodeType === 'record'">
            <div class="field">
              <label>录制内容</label>
              <p class="terminate-hint">
                共 {{ (selectedNode.data.params.events || []).length }} 个事件（鼠标点击、滚轮、键盘按下/抬起；不记录鼠标轨迹）
              </p>
            </div>
            <div class="field">
              <label>拆分为可编辑节点</label>
              <n-popconfirm @positive-click="splitMacro()">
                <template #trigger>
                  <n-button size="small" block type="warning">✂ 拆分为可编辑节点</n-button>
                </template>
                拆分会把这一步替换成一串「鼠标操作 / 键盘按键 / 延时」节点，原录制节点将被删除（间隔 ≥80ms 会插入延时以保留节奏）。确定？
              </n-popconfirm>
              <p class="terminate-hint">
                顶栏也有常驻入口「✂ 拆分节点」，不必先选中本节点（流程里只有一个录制节点时直接生效）。
                想把一串节点收拢起来：选中它们后点顶栏「📦 合并节点」，会生成一个可双击进去编辑的「组合节点」。
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
                提示：录制会覆盖当前节点内容；录制时请切换到目标窗口操作，再按一次录制快捷键（默认 alt+F2）结束。
                拆分后每个动作都是独立节点，可以单独删除/改坐标/改按键；长按某个键会被化简为单击（如需长按可用「键盘按键」的按下 / 松开两个节点表达）。
              </p>
            </div>
          </template>

          <!-- ============ 调用脚本（子脚本）============ -->
          <template v-else-if="selectedNode.data.nodeType === 'script_call'">
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
                与「组合节点」的运行效果基本相同，差别是子脚本可以单独编辑、单独导出，也能被多个脚本复用。<br />
                子脚本之间不允许循环调用（例如 A 调 B、B 又调回 A），选择时会立刻检测并阻止。
              </p>
            </div>
          </template>

          <!-- 输出变量（0.1.5）：节点只"声明"能产出什么，**不会**自动建变量。
               要哪个就切到「变量」页点一下「添加」——用不到的输出不占变量表。 -->
          <div v-if="selectedOutputs.length" class="field">
            <label>输出变量</label>
            <p class="terminate-hint">
              这个节点能输出：<b>{{ selectedOutputs.map((o) => o.label).join('、') }}</b>。
              变量不会自动创建，需要哪个就到「变量」页点一下添加。
            </p>
            <n-button
              size="small"
              block
              quaternary
              type="primary"
              style="margin-top: 6px"
              @click="inspTab = 'vars'"
            >
              ＋ 去「变量」页添加输出变量
            </n-button>
          </div>
          <!-- 普通节点参数面板结束 -->
          </template>
        </template>
        <div v-else class="inspector-empty">
          <div class="empty-emoji">🖐</div>
          <div>选中画布中的节点以配置参数</div>
        </div>
        </template>

        <!-- ============ 变量页（0.1.4）============
             管理本层的变量声明：主脚本 = 全局变量；子脚本 / 组合节点 = 局部变量。
             变量声明只负责"初始值"，节点运行时用「变量」节点读写。 -->
        <template v-else>
          <div class="inspector-head">
            <span class="inspector-title">🏷 {{ scopeInfo.title }}</span>
          </div>
          <div class="schema-help">{{ scopeInfo.desc }}</div>

          <n-alert
            v-if="duplicateVarNames().length"
            type="warning"
            :show-icon="true"
            class="var-dup-alert"
          >
            变量名重复：{{ duplicateVarNames().join('、') }}。重名的会被后面的覆盖，建议先改掉。
          </n-alert>

          <!-- ============ ① 本层已有变量 ============ -->
          <div class="vars-group-title">本层变量</div>

          <div v-for="(v, i) in variables" :key="i" class="var-row">
            <div class="var-row-top">
              <n-input
                :value="v.name"
                size="small"
                placeholder="变量名"
                @update:value="(val: string) => onVarNameInput(i, val)"
              />
              <n-button size="tiny" quaternary type="error" @click="removeVariable(i)">✕</n-button>
            </div>
            <div class="var-row-bottom">
              <n-select v-model:value="v.type" :options="VAR_TYPES" size="small" style="width: 108px" />
              <n-input v-model:value="v.value" size="small" placeholder="初始值" />
            </div>
            <div v-if="outputBoundNames.has(String(v.name || '').trim())" class="var-src">
              来自节点输出（运行时由该节点写入）
            </div>
          </div>

          <div v-if="!variables.length" class="vars-empty">
            本层还没有变量。可以在下面「＋ 新增变量」自己建一个，也可以直接在「节点输出」里添加。
          </div>

          <div class="field">
            <n-button size="small" block @click="addVariable">＋ 新增变量（自己用）</n-button>
          </div>

          <!-- ============ ② 选中节点的输出变量属性 ============ -->
          <div class="vars-group-title">节点输出</div>

          <template v-if="selectedNode">
            <div v-if="selectedOutputs.length" class="out-list">
              <div v-for="o in selectedOutputs" :key="o.param" class="out-row">
                <div class="out-main">
                  <span class="out-label">{{ o.label }}</span>
                  <span v-if="o.hint" class="out-hint">{{ o.hint }}</span>
                </div>
                <div class="out-side">
                  <template v-if="outputBound(o)">
                    <n-button size="tiny" quaternary @click="removeOutputVar(o)">
                      ✓ {{ outputBound(o) }}
                    </n-button>
                  </template>
                  <n-button v-else size="tiny" type="primary" ghost @click="addOutputVar(o)">
                    ＋ 添加
                  </n-button>
                </div>
              </div>
            </div>
            <div v-else class="vars-empty">
              {{ metaOf(selectedNode.data.nodeType).label }}没有可输出的变量。
            </div>
            <p class="terminate-hint">
              这些是<b>{{ metaOf(selectedNode.data.nodeType).label }}</b>能算出来的数据。
              <b>不添加就不会产生变量</b>——只有你需要时点「添加」，才会建一条同名变量并由该节点写入。
              点已添加的变量名可以取消。
            </p>
          </template>
          <div v-else class="vars-empty">在画布上选中一个节点，这里会列出它能输出的变量。</div>

          <div class="field">
            <p class="terminate-hint">
              这里声明的是本层的变量：主脚本是<b>全局变量</b>（整个工作流可见），
              子脚本 / 组合节点是<b>局部变量</b>（读得到全局，写不外泄）。
              要在子脚本里改全局变量，请用「变量」节点并把作用域选成「全局」。
            </p>
          </div>
        </template>
      </aside>
    </div>

    <ScreenCapture
      :show="capVisible"
      :mode="capMode"
      :initial-window="boundWindow?.hwnd ?? null"
      @captured="onCaptured"
      @picked="onPicked"
      @rect="onRect"
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
/* 组内必须同一行（拆分节点 / 合并节点是两种"整段流程的整理"操作，拆开看会很别扭） */
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
  width: 164px;
  flex: none;
  border-right: 1px solid var(--border);
  background: var(--bg-soft);
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  /* 节点多于可用高度时在**自己内部**滚动，不能溢出去压到画布/日志上 */
  min-height: 0;
  overflow-y: auto;
}
.palette-title {
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 600;
  margin-bottom: 2px;
}
/* ---------- 六大类切换 ----------
   3 × 2 网格。选中态用该类自己的颜色描边 + 淡色底：
   和画布上的节点配色一一对应，扫一眼就知道"当前在挑哪一类的节点"。 */
.cat-tabs {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
}
.cat-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 2px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.1;
  cursor: pointer;
  transition: 0.15s;
  font-family: inherit;
}
.cat-tab:hover {
  background: var(--bg-panel);
}
.cat-tab.active {
  background: var(--bg-panel);
  font-weight: 600;
}
.cat-tab-icon {
  font-size: 14px;
}
.cat-tab-label {
  white-space: nowrap;
}
.palette-cat-desc {
  font-size: 11px;
  color: var(--text-dim);
  line-height: 1.4;
  padding: 0 2px 4px;
  border-bottom: 1px solid var(--border);
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
/* 右侧面板顶部：参数 / 变量 两个标签页共用同一块区域（0.1.4 起） */
.insp-tabs {
  display: flex;
  gap: 2px;
  margin: -14px -14px 12px;
  padding: 6px 10px 0;
  border-bottom: 1px solid var(--border);
}
.insp-tab {
  appearance: none;
  border: none;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-dim);
  font-size: 13px;
  padding: 6px 12px;
  cursor: pointer;
  border-radius: 6px 6px 0 0;
}
.insp-tab:hover {
  color: var(--accent);
  background: var(--accent-soft);
}
.insp-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
  font-weight: 600;
}
/* 变量管理：一条声明一行小卡片（名字 / 类型 / 初始值） */
.var-row {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  padding: 8px;
  margin-bottom: 8px;
}
.var-row-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.var-row-bottom {
  display: flex;
  gap: 6px;
}
.vars-empty {
  color: var(--text-dim);
  font-size: 12px;
  text-align: center;
  padding: 14px 0;
}
.var-dup-alert {
  margin-bottom: 10px;
}
/* 变量页里的分区小标题（本层变量 / 节点输出） */
.vars-group-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-dim);
  margin: 14px 0 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}
/* 变量行底部的来源提示（来自某个节点的输出） */
.var-src {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-dim);
}
/* 节点输出变量属性列表 */
.out-list {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  overflow: hidden;
}
.out-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 8px;
}
.out-row + .out-row {
  border-top: 1px solid var(--border);
}
.out-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.out-label {
  font-size: 13px;
}
.out-hint {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 2px;
}
.out-side {
  flex: none;
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
/* 参数面板顶部的用法说明（来自 NODE_SCHEMA.help） */
.schema-help {
  margin-bottom: 14px;
  padding: 8px 10px;
  background: var(--bg-soft);
  border-left: 3px solid var(--accent);
  border-radius: 4px;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.55;
}
/* 条件编辑：左值弹性、运算符定宽、右值弹性 */
.cond-row {
  display: flex;
  gap: 6px;
  align-items: center;
}
.cond-row > :first-child {
  flex: 1;
  min-width: 0;
}
.cond-row > :last-child {
  flex: 1;
  min-width: 0;
}
.cond-op {
  width: 96px;
  flex: none !important;
}
/* 原生取色器：去掉两侧默认留白，跟输入框等高 */
.color-input {
  width: 34px;
  height: 34px;
  padding: 2px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  flex: none;
}
.region-text {
  flex: 1;
  font-size: 12px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mono :deep(textarea),
.mono :deep(input) {
  font-family: Consolas, 'Cascadia Mono', 'Courier New', monospace;
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
