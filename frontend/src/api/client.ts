import type { WindowInfo } from '../types'

const ENGINE_PORT = '8765'
// 打包后前端由引擎同源提供（端口=8765）时用相对路径；开发时（vite 1420）指向引擎端口
const BASE = window.location.port === ENGINE_PORT ? '' : `http://127.0.0.1:${ENGINE_PORT}`

export async function apiGet<T = any>(path: string): Promise<T> {
  const r = await fetch(BASE + path)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function apiPost<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function engineWsUrl(): string {
  if (BASE) return BASE.replace('http', 'ws') + '/ws'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}

export const engine = {
  health: () => apiGet('/health'),
  listWindows: () => apiGet<{ windows: WindowInfo[] }>('/windows/list'),
  screenshot: (win?: number | null) =>
    apiGet<{ image: string; width: number; height: number }>(
      `/screen/screenshot${win ? `?window=${win}` : ''}`,
    ),
  listTemplates: () => apiGet<{ templates: { id: string; file: string }[] }>('/vision/templates'),
  templateImage: (id: string) => apiGet<{ image: string }>(`/vision/template/${id}/image`),
  renameTemplate: (id: string, newName: string) =>
    apiPost<{ id: string }>('/vision/template/rename', { id, new_name: newName }),
  deleteTemplate: (id: string) => apiPost('/vision/template/delete', { id }),
  captureTemplate: (image: string, name?: string) =>
    apiPost<{ id: string }>('/vision/capture_template', { image, name }),
  match: (template: string, threshold: number, win?: number | null) =>
    apiPost<{ found: boolean; x: number; y: number; score: number; annotated?: string }>(
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
  stop: () => apiPost('/run/stop'),
  getHotkey: () => apiGet<{ hotkey: string[] }>('/config/hotkey'),
  setHotkey: (hotkey: string[]) => apiPost('/config/hotkey', { hotkey }),
  startPick: () => apiPost('/pick/start'),
  cancelPick: () => apiPost('/pick/cancel'),
  recordStart: () => apiPost<{ ok: boolean; recording: boolean }>('/record/start'),
  recordStop: () => apiPost('/record/stop'),
}
