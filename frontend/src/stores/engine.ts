/**
 * 引擎连接与「全局（不属于某个脚本）」的状态。
 *
 * 为什么必须集中：引擎只允许**一个**编辑器页面连接（多开会互相覆盖流程同步，
 * 见 main.py 的 4409），所以 WebSocket 必须是全应用一条。0.1.2 起界面里可以同时
 * 开着多个脚本标签，如果每个标签各连一次，第二个标签会立刻被引擎拒掉。
 *
 * 这里还收拢了所有「跟哪个脚本无关」的状态：引擎版本、桌面/浏览器形态、
 * 悬浮框开关、模板与窗口列表、录制状态。真正跟脚本有关的（节点、历史、脚本名）
 * 留在各自的文档里。
 *
 * 页面事件（拾取坐标 / 录制完成 / 引擎请求启动）必须交给**当前活动标签**处理，
 * 因此走 `setHandlers` 注册：谁在前台谁接管，切标签时重新注册。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { engine, engineWsUrl } from '../api/client'
import { useProjectStore } from './project'
import type { WindowInfo } from '../types'

export interface EngineHandlers {
  /** 引擎要求启动流程（全局快捷键 / 悬浮框按钮） */
  onRunRequest?: () => void
  /** 拾取到屏幕坐标 */
  onPicked?: (x: number, y: number) => void
  /** 悬浮框改了循环轮数 */
  onRepeat?: (value: number) => void
  /** 一段键鼠录制结束 */
  onRecorded?: (events: any[]) => void
  /** 请求当前文档的流程负载（引擎连上来时同步用） */
  payload?: () => any
}

export const useEngineStore = defineStore('engine', () => {
  const project = useProjectStore()

  const version = ref('')
  const desktop = ref(false)
  const connected = ref(false)
  /** 被引擎拒绝（已有另一个编辑器窗口在运行） */
  const busy = ref(false)

  const templates = ref<{ label: string; value: string }[]>([])
  const windows = ref<WindowInfo[]>([])

  const overlayEnabled = ref(false)
  const overlayAvailable = ref(true)

  const macroRecording = ref(false)

  let ws: WebSocket | null = null
  let wsRetry: ReturnType<typeof setTimeout> | null = null
  let wsFailCount = 0
  let destroyed = false
  let handlers: EngineHandlers = {}
  let started = false

  function setHandlers(h: EngineHandlers) {
    handlers = h
  }

  function retryWs(delay: number) {
    if (wsRetry) clearTimeout(wsRetry)
    wsRetry = setTimeout(connect, delay)
  }

  function retryNow() {
    if (wsRetry) {
      clearTimeout(wsRetry)
      wsRetry = null
    }
    connect()
  }

  function connect() {
    if (destroyed) return
    // 先收掉上一条（可能是 CONNECTING 状态的），否则手动重试会和定时重试撞在一起，
    // 同一页面开出两条连接 → 其中一条必然被引擎以 4409 拒掉
    try {
      ws?.close()
    } catch {
      /* 已经关掉了 */
    }
    ws = new WebSocket(engineWsUrl())
    ws.onopen = () => {
      busy.value = false
      connected.value = true
      wsFailCount = 0
      syncRunState()
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'log') project.addLog(msg)
        else if (msg.type === 'state') {
          project.running = msg.state === 'running'
          if (typeof msg.paused === 'boolean') project.paused = msg.paused
        } else if (msg.type === 'overlay') overlayEnabled.value = !!msg.enabled
        else if (msg.type === 'repeat') handlers.onRepeat?.(Number(msg.value) || 1)
        else if (msg.type === 'picked') handlers.onPicked?.(msg.x, msg.y)
        else if (msg.type === 'run_request') handlers.onRunRequest?.()
        else if (msg.type === 'recording') macroRecording.value = !!msg.recording
        else if (msg.type === 'recorded') handlers.onRecorded?.(msg.events || [])
        else if (msg.type === 'busy') busy.value = true
      } catch {
        /* 非 JSON 广播，忽略 */
      }
    }
    ws.onclose = (ev) => {
      connected.value = false
      project.running = false
      project.paused = false
      if (destroyed) return
      // 4409：引擎只允许一个 WebUI，而这个页面不是那一个。
      // 不停重试是为了「刷新页面」——刷新时旧连接会先断开，通常第一次重试就能连上；
      // 真正多开的那个页面则会一直看到提示，不会去干扰正在工作的那个窗口。
      if (ev.code === 4409) {
        busy.value = true
        retryWs(1500)
        return
      }
      // 自动重连：断线期间日志/状态会丢，重连后立即同步真实状态
      wsFailCount += 1
      retryWs(2000)
    }
  }

  function start() {
    if (started) return
    started = true
    destroyed = false
    connect()
    engine
      .health()
      .then((h) => {
        version.value = String(h?.version || '')
        desktop.value = !!h?.desktop
      })
      .catch(() => {
        /* 引擎不可达时留空 */
      })
  }

  function stop() {
    destroyed = true
    if (wsRetry) clearTimeout(wsRetry)
    try {
      ws?.close()
    } catch {
      /* 忽略 */
    }
  }

  async function syncRunState() {
    try {
      const r = await engine.runState()
      project.running = !!r.running
      project.paused = !!r.paused
    } catch {
      /* 引擎不可达时下个周期再试 */
    }
  }

  async function refreshTemplates(quiet = false) {
    try {
      const r = await engine.listTemplates()
      templates.value = r.templates.map((t) => ({ label: t.id, value: t.id }))
    } catch (e: any) {
      if (!quiet) project.addLog({ level: 'error', message: '获取模板失败：' + e.message, ts: Date.now() / 1000 })
    }
  }

  async function refreshWindows(quiet = false) {
    try {
      const r = await engine.listWindows()
      windows.value = r.windows
    } catch (e: any) {
      if (!quiet) project.addLog({ level: 'error', message: '获取窗口列表失败：' + e.message, ts: Date.now() / 1000 })
    }
  }

  async function syncOverlay() {
    try {
      const s = await engine.overlayState()
      overlayEnabled.value = !!s.enabled
      overlayAvailable.value = s.available !== false
    } catch {
      /* 引擎不可达时下个周期再试 */
    }
  }

  async function toggleOverlay(): Promise<boolean> {
    const s = await engine.setOverlay(!overlayEnabled.value)
    overlayEnabled.value = !!s.enabled
    overlayAvailable.value = s.available !== false
    return overlayEnabled.value
  }

  async function startRecording() {
    macroRecording.value = true
    try {
      await engine.recordStart()
    } catch (e: any) {
      macroRecording.value = false
      throw e
    }
  }

  async function stopRecording() {
    await engine.recordStop()
  }

  return {
    version,
    desktop,
    connected,
    busy,
    templates,
    windows,
    overlayEnabled,
    overlayAvailable,
    macroRecording,
    setHandlers,
    start,
    stop,
    retryNow,
    syncRunState,
    refreshTemplates,
    refreshWindows,
    syncOverlay,
    toggleOverlay,
    startRecording,
    stopRecording,
  }
})
