import type { WindowInfo } from '../types'

const ENGINE_PORT = '8765'
// 打包后前端由引擎同源提供（端口=8765）时用相对路径；开发时（vite 1420）指向引擎端口
const BASE = window.location.port === ENGINE_PORT ? '' : `http://127.0.0.1:${ENGINE_PORT}`

// 访问令牌：引擎自动打开浏览器时通过 ?token= 传入；存入 sessionStorage 后从地址栏抹除，
// 防止令牌随书签/截图泄露。开发模式（AUTOGAMETOOL_DEV=1）下引擎不校验，可为空。
function initToken(): string {
  const url = new URL(window.location.href)
  const fromUrl = url.searchParams.get('token')
  if (fromUrl) {
    sessionStorage.setItem('agt_token', fromUrl)
    url.searchParams.delete('token')
    window.history.replaceState(null, '', url.pathname + url.search + url.hash)
    return fromUrl
  }
  return sessionStorage.getItem('agt_token') || ''
}
const TOKEN = initToken()

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  return { ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}), ...(extra || {}) }
}

// 把 FastAPI 的 {"detail": "..."} 错误体解析成可读消息，不再向用户展示原始 JSON
async function toError(r: Response): Promise<Error> {
  const text = await r.text()
  try {
    const j = JSON.parse(text)
    if (j && j.detail) {
      return new Error(typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail))
    }
  } catch {
    /* 非 JSON */
  }
  return new Error(text || `HTTP ${r.status}`)
}

export async function apiGet<T = any>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { headers: authHeaders() })
  if (!r.ok) throw await toError(r)
  return r.json()
}

export async function apiPost<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw await toError(r)
  return r.json()
}

export function engineWsUrl(): string {
  const suffix = TOKEN ? `?token=${encodeURIComponent(TOKEN)}` : ''
  if (BASE) return BASE.replace('http', 'ws') + '/ws' + suffix
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws${suffix}`
}

export const engine = {
  health: () => apiGet('/health'),
  listWindows: () => apiGet<{ windows: WindowInfo[] }>('/windows/list'),
  screenshot: (win?: number | null) =>
    apiGet<{ image: string; width: number; height: number }>(
      `/screen/screenshot${win ? `?window=${win}` : ''}`,
    ),
  listTemplates: () => apiGet<{ templates: { id: string; file: string }[] }>('/vision/templates'),
  templateImage: (id: string) => apiGet<{ image: string }>(`/vision/template/${encodeURIComponent(id)}/image`),
  renameTemplate: (id: string, newName: string) =>
    apiPost<{ id: string }>('/vision/template/rename', { id, new_name: newName }),
  deleteTemplate: (id: string) => apiPost('/vision/template/delete', { id }),
  captureTemplate: (image: string, name?: string, meta?: Record<string, unknown>) =>
    apiPost<{ id: string }>('/vision/capture_template', { image, name, meta }),
  match: (template: string, threshold: number, win?: number | null) =>
    apiPost<{ found: boolean; x: number; y: number; score: number; scale?: number; annotated?: string }>(
      '/vision/match',
      { template, threshold, window: win },
    ),
  click: (x: number, y: number, button = 'left', clicks = 1, mode = 'real', win?: number | null) =>
    apiPost('/input/click', { x, y, button, clicks, mode, window: win }),
  key: (key: string, mode = 'real', win?: number | null) =>
    apiPost('/input/key', { key, mode, window: win }),
  text: (text: string, mode = 'real', win?: number | null) =>
    apiPost('/input/text', { text, mode, window: win }),
  run: (flow: unknown) => apiPost('/run', { flow }),
  loadFlow: (flow: unknown) => apiPost('/flow/load', { flow }),
  stop: () => apiPost<{ ok: boolean; running: boolean }>('/run/stop'),
  runState: () => apiGet<{ running: boolean }>('/run/state'),
  getHotkey: () => apiGet<{ hotkey: string[] }>('/config/hotkey'),
  setHotkey: (hotkey: string[]) => apiPost('/config/hotkey', { hotkey }),
  startPick: () => apiPost('/pick/start'),
  cancelPick: () => apiPost('/pick/cancel'),
  recordStart: () => apiPost<{ ok: boolean; recording: boolean }>('/record/start'),
  recordStop: () => apiPost('/record/stop'),
}
