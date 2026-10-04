/**
 * 跨编辑器复制/剪切/粘贴的纯逻辑。
 *
 * 复制的是「片段」：一批节点 + 它们**内部**的连线（只有两端都在选区里的连线才带走，
 * 否则粘出来的节点会挂着指向原文档节点的悬空边）。
 *
 * 坐标记的是相对片段左上角的偏移，粘贴时再落到目标位置——这样"复制一段流程，
 * 切到另一个编辑器，在鼠标处粘贴"就能得到位置合理的副本，而不是跑到画布外的老坐标。
 */
export interface ClipNode {
  dx: number
  dy: number
  type: string
  data: any
}

export interface ClipFragment {
  nodes: ClipNode[]
  edges: { from: number; to: number; sourceHandle: string | null }[]
}

export function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v ?? null)) as T
}

/** 从当前文档里抽出选中节点构成的片段；没有选中节点时返回 null。 */
export function extractFragment(nodes: any[], edges: any[], ids: string[]): ClipFragment | null {
  const idSet = new Set(ids)
  const picked = (nodes || []).filter((n) => idSet.has(n.id))
  if (!picked.length) return null

  const originX = Math.min(...picked.map((n) => Number(n?.position?.x) || 0))
  const originY = Math.min(...picked.map((n) => Number(n?.position?.y) || 0))
  const index = new Map<string, number>()
  picked.forEach((n, i) => index.set(n.id, i))

  const inner = (edges || [])
    .filter((e) => idSet.has(e.source) && idSet.has(e.target) && index.has(e.source) && index.has(e.target))
    .map((e) => ({
      from: index.get(e.source) as number,
      to: index.get(e.target) as number,
      sourceHandle: e.sourceHandle ?? null,
    }))

  return {
    nodes: picked.map((n) => ({
      dx: (Number(n?.position?.x) || 0) - originX,
      dy: (Number(n?.position?.y) || 0) - originY,
      type: n?.type ?? 'step',
      data: clone(n?.data ?? {}),
    })),
    edges: inner,
  }
}

/**
 * 把片段实体化成目标文档里的节点与连线。
 * `genId` 由调用方提供（文档自己的 id 计数器），保证粘贴两次不会撞 id。
 */
export function materializeFragment(
  frag: ClipFragment,
  at: { x: number; y: number },
  genId: () => string,
): { nodes: any[]; edges: any[] } {
  const ids = frag.nodes.map(() => genId())
  const nodes = frag.nodes.map((n, i) => ({
    id: ids[i],
    type: n.type || 'step',
    position: { x: Math.round(at.x + n.dx), y: Math.round(at.y + n.dy) },
    data: clone(n.data),
  }))
  const edges = frag.edges.map((e) => ({
    id: `e-${ids[e.from]}-${ids[e.to]}`,
    source: ids[e.from],
    target: ids[e.to],
    sourceHandle: e.sourceHandle,
  }))
  return { nodes, edges }
}
