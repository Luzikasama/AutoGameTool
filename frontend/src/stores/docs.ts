/**
 * 多标签文档（标签页 = 一个脚本编辑器）。
 *
 * 为什么需要这一层：0.1.2 起「同时打开多个脚本 + 子脚本」成为常态，
 * 原先 Editor.vue 里那一堆 `nodes/edges/flowName/历史` 全局 ref 只够一个文档用。
 *
 * 状态怎么分：
 *  - **文档数据**（nodes / edges / scripts / 各种元信息）由各标签对应的编辑器实例
 *    持有并实时镜像到这里的 `roots`（普通 Map，刻意 markRaw 掉，避免整棵流程图
 *    被 Vue 深度代理 —— 上万节点时那是纯浪费）；
 *  - **标签元信息**（标题、是否改动、指向哪个子脚本）放在这里，标签栏与「保存全部」
 *    需要一个能观察的小数据面。
 *
 * 子脚本的 id（`s1` / `s2` …）由这里统一发放，保证同一父脚本内不重复。
 */
import { defineStore } from 'pinia'
import { markRaw, ref } from 'vue'
import type { SubScript } from '../types'
import { normalizeScripts } from '../lib/scriptGraph'

export interface DocMeta {
  /** 标签 id（与脚本 id 无关；子脚本标签可以关掉再打开，标签 id 会换） */
  id: string
  kind: 'root' | 'sub'
  /** 所属根文档的标签 id（root 文档就是它自己） */
  rootId: string
  /** 子脚本 id；root 为空串 */
  scriptId: string
  /** 标签上显示的名字 */
  name: string
  /** 有未保存的改动 */
  dirty: boolean
}

export interface RootData {
  name: string
  repeat: number
  inputMode: 'real' | 'simulated'
  boundWindow: { hwnd: number; title: string } | null
  screen: { width: number; height: number } | null
  windowRect: any | null
  nodes: any[]
  edges: any[]
  /** 内嵌在本脚本下的子脚本库 */
  scripts: Record<string, SubScript>
}

function emptyRoot(name = '未命名脚本'): RootData {
  return {
    name,
    repeat: 1,
    inputMode: 'real',
    boundWindow: null,
    screen: null,
    windowRect: null,
    nodes: [],
    edges: [],
    scripts: {},
  }
}

export const useDocsStore = defineStore('docs', () => {
  const tabs = ref<DocMeta[]>([])
  const activeId = ref('')
  /** rootId → [{id, name}]，供「调用脚本」下拉框使用（必须是响应式的，否则改名不刷新） */
  const scriptIndex = ref<Record<string, { id: string; name: string }[]>>({})
  /**
   * tabId → 内容被"就地替换"的次数。
   *
   * 文档数据是 markRaw 的普通对象，就地改写它**不会**触发任何响应式更新，
   * 所以「加载」取代当前空白脚本后，编辑器实例要靠这个计数才知道该重新读一遍存储。
   */
  const rev = ref<Record<string, number>>({})

  function bumpRev(tabId: string) {
    rev.value = { ...rev.value, [tabId]: (rev.value[tabId] || 0) + 1 }
  }

  // 文档数据本体。markRaw：这是一份"数据库"，不需要 Vue 去追踪里面每个节点。
  const roots = markRaw(new Map<string, RootData>())
  let seq = 0

  function nextId(prefix: string) {
    seq += 1
    return `${prefix}${seq}`
  }

  function getRoot(rootId: string): RootData | undefined {
    return roots.get(rootId)
  }

  function refreshScriptIndex(rootId: string) {
    const r = roots.get(rootId)
    scriptIndex.value = {
      ...scriptIndex.value,
      [rootId]: r
        ? Object.values(r.scripts).map((s) => ({ id: s.id, name: s.name }))
        : [],
    }
  }

  /** 新建一个根文档（脚本）并激活。 */
  function openRoot(init?: Partial<RootData>, tabName?: string): string {
    const id = nextId('doc')
    const data: RootData = { ...emptyRoot(tabName || '未命名脚本'), ...(init || {}) }
    data.scripts = normalizeScripts(data.scripts)
    roots.set(id, data)
    const tab: DocMeta = {
      id,
      kind: 'root',
      rootId: id,
      scriptId: '',
      name: data.name,
      dirty: false,
    }
    tabs.value.push(tab)
    activeId.value = id
    refreshScriptIndex(id)
    return id
  }

  /** 打开（或聚焦）某个子脚本的编辑器标签。 */
  function openSub(rootId: string, scriptId: string): string {
    const exist = tabs.value.find((t) => t.kind === 'sub' && t.rootId === rootId && t.scriptId === scriptId)
    if (exist) {
      activeId.value = exist.id
      return exist.id
    }
    const root = roots.get(rootId)
    const script = root?.scripts?.[scriptId]
    if (!root || !script) return ''
    const id = nextId('sub')
    tabs.value.push({
      id,
      kind: 'sub',
      rootId,
      scriptId,
      name: script.name || scriptId,
      dirty: false,
    })
    activeId.value = id
    return id
  }

  function activate(id: string) {
    if (tabs.value.some((t) => t.id === id)) activeId.value = id
  }

  /** 拖拽调整标签顺序（浏览器式）。from/to 都是当前下标。 */
  function moveTab(from: number, to: number) {
    const arr = tabs.value
    if (from === to || from < 0 || to < 0 || from >= arr.length || to >= arr.length) return
    const [item] = arr.splice(from, 1)
    arr.splice(to, 0, item)
  }

  /**
   * 把一份**已存在的根文档**就地换成另一份内容，标签位置与 id 都不变。
   *
   * 用途：「加载」遇到当前空白脚本时用它取代，而不是再开一个标签 ——
   * 否则每加载一次就多留一个空白页，浏览器式标签的意义就没了。
   */
  function replaceRoot(rootId: string, init: Partial<RootData>, tabName?: string): boolean {
    const r = roots.get(rootId)
    if (!r) return false
    const data: RootData = { ...emptyRoot(tabName || '未命名脚本'), ...init }
    data.scripts = normalizeScripts(data.scripts)
    Object.assign(r, data)
    const t = tabs.value.find((x) => x.id === rootId)
    if (t) {
      t.name = data.name
      t.dirty = false
    }
    refreshScriptIndex(rootId)
    bumpRev(rootId)
    return true
  }

  /** 关闭标签。最后一个标签不允许关闭（留着"当前没有脚本"的空白态会很怪）。 */
  function closeTab(id: string): boolean {
    const idx = tabs.value.findIndex((t) => t.id === id)
    if (idx < 0) return false
    if (tabs.value.length <= 1) return false
    const wasSub = tabs.value[idx]
    if (wasSub.kind === 'root') roots.delete(wasSub.rootId)
    tabs.value.splice(idx, 1)
    if (activeId.value === id) {
      const next = tabs.value[Math.min(idx, tabs.value.length - 1)]
      activeId.value = next ? next.id : ''
    }
    return true
  }

  function patchTab(id: string, patch: Partial<DocMeta>) {
    const t = tabs.value.find((x) => x.id === id)
    if (t) Object.assign(t, patch)
  }

  /** 子脚本被改动时，父脚本标签也要显示"有改动"。 */
  function markDirty(rootId: string) {
    const t = tabs.value.find((x) => x.kind === 'root' && x.rootId === rootId)
    if (t) t.dirty = true
  }

  /** 关闭根文档时，把它名下打开着的子脚本标签一起收掉。 */
  function closeSubTabsOf(rootId: string) {
    tabs.value = tabs.value.filter((t) => !(t.kind === 'sub' && t.rootId === rootId))
  }

  function newScriptId(rootId: string): string {
    const root = roots.get(rootId)
    let n = 1
    while (root && root.scripts[`s${n}`]) n += 1
    return `s${n}`
  }

  /** 往父脚本里登记一个子脚本（id 已存在则覆盖内容）。 */
  function putScript(rootId: string, script: SubScript) {
    const root = roots.get(rootId)
    if (!root) return
    root.scripts[script.id] = script
    refreshScriptIndex(rootId)
  }

  function removeScript(rootId: string, scriptId: string) {
    const root = roots.get(rootId)
    if (!root) return
    delete root.scripts[scriptId]
    tabs.value = tabs.value.filter((t) => !(t.kind === 'sub' && t.rootId === rootId && t.scriptId === scriptId))
    refreshScriptIndex(rootId)
    if (!tabs.value.some((t) => t.id === activeId.value)) {
      const fallback = tabs.value.find((t) => t.kind === 'root' && t.rootId === rootId) || tabs.value[0]
      activeId.value = fallback ? fallback.id : ''
    }
  }

  function scriptsOf(rootId: string): SubScript[] {
    const root = roots.get(rootId)
    return root ? Object.values(root.scripts) : []
  }

  return {
    tabs,
    activeId,
    scriptIndex,
    rev,
    getRoot,
    refreshScriptIndex,
    openRoot,
    openSub,
    activate,
    moveTab,
    replaceRoot,
    closeTab,
    closeSubTabsOf,
    patchTab,
    markDirty,
    newScriptId,
    putScript,
    removeScript,
    scriptsOf,
  }
})
