/**
 * 编辑器界面回归断言（0.1.2 起）。
 *
 * 模型/CI 看不到画面，所以这里只做**结构断言**：把页面跑在真实浏览器里，
 * 读出 DOM 与计算样式来确认"界面确实改成了该有的样子、而且没有白屏"。
 *
 * 覆盖：
 *   1) 打开应用时运行日志默认收起；点底部「日志」图标能在**下方**展开 / 收起原日志框（不是浮层）
 *   2) 底部按钮只有图标、齿轮字号更大
 *   3) 顶栏不再有「复制 / 剪切 / 粘贴」；改由**画布右键菜单**唤出
 *      （右键节点 = 三项、右键空白 = 只有粘贴、剪贴板空时粘贴置灰、Esc 可关）
 *   4) 标签能通过"按下-移动-抬起"改变顺序（实现是自己按落点算，不是 HTML5 draggable）
 *   5) 【0.1.4】悬停说明全部去掉（无 .n-tooltip、可见按钮无 title 属性）
 *   6) 【0.1.4】顶栏不再有「输入方式」单选；输入方式下移到各输入节点的参数里
 *   7) 【0.1.4】右侧面板「参数 / 变量」两个标签页；变量按容器分（全局 vs 局部）
 *   8) 【0.1.4】组合节点：渲染 / 单击改属性 / 双击进新标签编辑 / 局部变量隔离
 *   9) 【0.1.4】「📦 合并节点」能把选中的一串相邻节点收成一个组合节点
 *
 * ⚠️ 输入方式：**只用页面内事件派发**（el.click() / new PointerEvent(...) / new MouseEvent('contextmenu')）。
 * 刻意不使用 CDP 的 Input.dispatchMouseEvent —— 那属于向浏览器注入输入事件，会碰到真实鼠标；
 * 而且本机 headless 环境下它本来也不生效（收不到任何事件）。页面内派发走的是与真实操作
 * **完全相同的那套处理函数**（pointerdown on .tab → window 上的 pointermove/pointerup → moveTab），
 * 足以验证业务逻辑是否正确。
 *
 * ⚠️ 节点选择：节点根元素 `.vue-flow__node` 上挂了 Vue 的原生 `onClick`（→ onSelectNode），
 * 所以辅助函数 nodeClick() 派发 **MouseEvent**（不是 PointerEvent）的 mousedown → mouseup → click，
 * 且必须带 `view: window`（d3-drag 用 event.view 找 window 挂后续监听）。多选则先
 * keydown('Control') 再点第二个。
 *
 * 前置条件（tools\test_ui_editor.ps1 会自动准备）：
 *   · 引擎已在本机跑着（默认 http://127.0.0.1:8765）
 *   · 有一个带 --remote-debugging-port 的无头 Chrome
 *   · 环境变量 AGT_URL（带 token 的页面地址）
 *
 * 退出码 0 = 全通过；结果同时写到 AGT_OUT。
 */
import { writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const PORT = Number(process.env.AGT_CDP_PORT || 9222)
const BASE = process.env.AGT_URL
const OUT = process.env.AGT_OUT || join(tmpdir(), 'agt-ui-editor-checks.txt')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let msgId = 0
const pending = new Map()
let ws = null

async function connect() {
  let target = null
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
      target = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl)
      if (target) break
    } catch {
      /* 还没起来 */
    }
    await sleep(500)
  }
  if (!target) throw new Error('CDP: 找不到可用的 page target')
  ws = new WebSocket(target.webSocketDebuggerUrl)
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m)
      pending.delete(m.id)
    }
  })
  await new Promise((res, rej) => {
    ws.addEventListener('open', () => res())
    ws.addEventListener('error', () => rej(new Error('CDP: WebSocket 连接失败')))
  })
}

function send(method, params = {}) {
  return new Promise((res) => {
    const i = ++msgId
    pending.set(i, res)
    ws.send(JSON.stringify({ id: i, method, params }))
  })
}

async function js(expr) {
  const r = await send('Runtime.evaluate', {
    expression: expr,
    awaitPromise: true,
    returnByValue: true,
  })
  const ex = r.result && r.result.exceptionDetails
  if (ex) throw new Error('页面脚本报错: ' + JSON.stringify(ex.exception || ex))
  return r.result && r.result.result ? r.result.result.value : undefined
}

const results = []
function check(name, ok, detail) {
  results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' :: ' + detail : ''}`)
}

// 页面上同一时刻只有当前标签的 pane 可见，所有选择器都要按"可见"过滤
const HELPERS = `
  const vis = (el) => el && el.offsetParent !== null;
  const visAll = (s) => Array.from(document.querySelectorAll(s)).filter(vis);
  const strip = () => visAll('.tabstrip')[0];
  const nameInput = () => visAll('.name-input input')[0];
  const tabNames = () => { const s = strip(); return s ? Array.from(s.querySelectorAll('.tab-name')).map(e=>e.textContent.trim()) : []; };
  const tabRects = () => { const s = strip(); return s ? Array.from(s.querySelectorAll('.tab')).map(t => { const b = t.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height }; }) : []; };
  const nodes = () => visAll('.vue-flow__node');
  const ctxItems = () => Array.from(document.querySelectorAll('.ctx-menu .ctx-item')).map(b => {
    const c = b.cloneNode(true);
    const ic = c.querySelector('.ctx-icon'); if (ic) ic.remove();
    return { label: c.textContent.replace(/Ctrl\\+[A-Za-z]/g, '').trim(), disabled: b.disabled };
  });
  const rc = (el, x, y) => el.dispatchEvent(new MouseEvent('contextmenu', {
    bubbles: true, cancelable: true, composed: true,
    clientX: x, clientY: y, button: 2, buttons: 2,
  }));
`

const names = () => js(`(() => { ${HELPERS} return tabNames(); })()`)
const nodeCount = () => js(`(() => { ${HELPERS} return nodes().length; })()`)
const ctxItems = () => js(`(() => { ${HELPERS} return ctxItems(); })()`)
const ctxMenuOpen = () => js(`(() => { ${HELPERS} return !!document.querySelector('.ctx-menu'); })()`)

/** 页面内点一下（原生 button，走 click 事件） */
async function clickInPage(sel) {
  return js(
    `(() => { ${HELPERS} const el = visAll(${JSON.stringify(sel)})[0]; if (!el) return false; el.click(); return true; })()`,
  )
}

/** 右键画布上第 idx 个节点 */
async function rightClickNode(idx = 0) {
  return js(
    `(() => { ${HELPERS} const n = nodes()[${idx}]; if (!n) return false;
      const b = n.getBoundingClientRect();
      rc(n, Math.round(b.x + 24), Math.round(b.y + 14));
      return true; })()`,
  )
}

/** 右键画布空白处 */
async function rightClickPane() {
  return js(
    `(() => { ${HELPERS} const p = visAll('.vue-flow__pane')[0]; if (!p) return false;
      const b = p.getBoundingClientRect();
      rc(p, Math.round(b.x + 30), Math.round(b.y + b.height - 30));
      return true; })()`,
  )
}

/** 点右键菜单里的某一项 */
async function clickCtxItem(label) {
  return js(
    `(() => { ${HELPERS}
      const it = Array.from(document.querySelectorAll('.ctx-menu .ctx-item')).find(b => b.textContent.includes(${JSON.stringify(label)}));
      if (!it) return false; it.click(); return true; })()`,
  )
}

/**
 * 页面内派发一次拖拽：把第 fromIdx 个标签拖到第 toIdx 个标签的左半边（after=false）
 * 或右半边（after=true）；toIdx = -1 表示拖到最后一个标签的右半边（即末尾）。
 */
async function dragInPage(fromIdx, toIdx, after) {
  return js(
    `(() => { ${HELPERS}
      const rs = tabRects(); if (!rs.length) return false;
      const a = rs[${fromIdx}]; const b = rs[${toIdx}] || rs[rs.length - 1];
      const fromX = a.x + a.w / 2, y = a.y + a.h / 2;
      const toX = (${after ? 'true' : 'false'} || ${toIdx} < 0) ? b.x + b.w - 4 : b.x + 4;
      const opts = (x, buttons) => ({ bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, button: 0, buttons, pointerId: 1, pointerType: 'mouse', isPrimary: true });
      const first = strip().querySelectorAll('.tab')[${fromIdx}];
      first.dispatchEvent(new PointerEvent('pointerdown', opts(fromX, 1)));
      for (let i = 1; i <= 8; i++) window.dispatchEvent(new PointerEvent('pointermove', opts(fromX + (toX - fromX) * i / 8, 1)));
      window.dispatchEvent(new PointerEvent('pointerup', opts(toX, 0)));
      return true;
    })()`,
  )
}

async function dragTo(fromIdx, toIdx, expect, after = false) {
  await dragInPage(fromIdx, toIdx, after)
  await sleep(350)
  const got = await names()
  return { ok: got.join(',') === expect, got }
}

// ---------------------------------------------------------------------------
// 0.1.4 专用的页面内辅助
// ---------------------------------------------------------------------------

/** 文件 input 是 display:none（offsetParent 为 null），不能按"可见"来挑；要按所在活动 pane 找。 */
const HELPERS14 = `
  const activeEditor = () => Array.from(document.querySelectorAll('.editor')).filter(e => e.offsetParent !== null)[0];
  const fileInput = () => { const e = activeEditor(); return e ? e.querySelector('.topbar input[type=file]') : null; };
  const inspTabs = () => visAll('.insp-tab');
  const inspText = () => { const e = visAll('.inspector')[0]; return e ? e.textContent.replace(/\\s+/g,' ').trim() : ''; };
  const nodeEls = () => visAll('.vue-flow__node');
  const groupNodes = () => visAll('.step-node.is-group');
`

/** 把一份脚本 JSON 灌进「📂 加载」的隐藏 file input（等价于用户选文件）。 */
async function loadScript(obj, filename = 'check.agflow') {
  return js(
    `(() => { ${HELPERS} ${HELPERS14}
      const inp = fileInput(); if (!inp) return false;
      const f = new File([${JSON.stringify(JSON.stringify(obj))}], ${JSON.stringify(filename)}, { type: 'application/json' });
      const dt = new DataTransfer(); dt.items.add(f);
      inp.files = dt.files;
      inp.dispatchEvent(new Event('change', { bubbles: true }));
      return true; })()`,
  )
}

/**
 * 在画布上"点选"第 idx 个节点。
 *
 * ⚠️ 必须用 **MouseEvent**，不是 PointerEvent。节点根元素 `.vue-flow__node` 上直接挂了
 * Vue 的原生 `onClick`（→ onSelectNode → handleNodeClick），所以**一次真实的 click 才是最稳的入口**。
 * 这里按真实浏览器那套顺序派发 mousedown → mouseup → click（都带 `view: window`，
 * 因为 @vue-flow/core 自带的 d3-drag 用 `select(event.view)` 把 mousemove/mouseup 挂到 window 上）。
 *
 * 刻意**不做位移**：位移 0 时 d3 的 eventEnd 不会触发它自己的 onClick（distance2===0 不算点击），
 * 于是选择只由原生 click 触发一次 —— 否则 ctrl 加选会被 `addSelectedNodes` 跑两遍抵消掉。
 *
 * ctrl=true 时先按下 Control（Vue Flow 的 multiSelectionKeyCode，非 mac 默认 Control；
 * 它用 @vueuse 的 onKeyStroke 监听 window），实现加选而不是替换选择。
 */
async function nodeClick(idx, ctrl = false) {
  // Ctrl 多选：Vue Flow 用 `watch(multiSelectKeyPressed)` 把按键状态同步到 multiSelectionActive，
  // 而 Vue 的 watcher 是**异步刷新**的 —— 必须在 keydown 之后隔一帧再点，否则点击那一刻它还是 false，
  // 于是"加选"退化成"替换选择"，后面依赖多选的断言就全挂了。
  // 另有两个坑：
  //   1) 监听目标是 **document**（不是 window），键盘事件要派发在 document 并冒泡；
  //   2) KeyboardEvent **必须带 `code`**：Vue Flow 用 `useKeyOrCode` 决定读 event.code 还是 event.key，
  //      判据是 `'Control'.includes(event.code)` —— 不带 code 时它是空串，`includes('')` 恒为 true，
  //      于是去比 event.code（空）而不是 event.key，永远匹配不上。带 'ControlLeft' 才会走 key 分支。
  const ctrlKey = ctrl
    ? `(() => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Control', code: 'ControlLeft', bubbles: true })); return true; })()`
    : null
  if (ctrl) {
    await js(ctrlKey)
    await sleep(120)
  }
  const ok = await js(
    `(() => { ${HELPERS} ${HELPERS14}
      const el = nodeEls()[${idx}]; if (!el) return false;
      const b = el.getBoundingClientRect();
      const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
      const mk = (type, buttons) => new MouseEvent(type, { bubbles: true, cancelable: true, composed: true,
        view: window, clientX: cx, clientY: cy, button: 0, buttons });
      el.dispatchEvent(mk('mousedown', 1));
      el.dispatchEvent(mk('mouseup', 0));
      el.dispatchEvent(mk('click', 0));
      return true; })()`,
  )
  if (ctrl) {
    await js(`(() => { document.dispatchEvent(new KeyboardEvent('keyup', { key: 'Control', code: 'ControlLeft', bubbles: true })); return true; })()`)
    await sleep(80)
  }
  return ok
}

/** 双击第 idx 个节点（Vue Flow 的 nodeDoubleClick 绑在 DOM 的 dblclick 上）。 */
async function nodeDblClick(idx) {
  return js(
    `(() => { ${HELPERS} ${HELPERS14}
      const el = nodeEls()[${idx}]; if (!el) return false;
      const b = el.getBoundingClientRect();
      el.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true, composed: true,
        clientX: Math.round(b.x + b.width / 2), clientY: Math.round(b.y + b.height / 2), button: 0 }));
      return true; })()`,
  )
}

/** 画布上某个选择器命中的节点，在 nodeEls() 里的下标（-1 = 没找到）。
 *  不依赖"节点数组顺序 == DOM 顺序"，比硬编码下标稳。 */
const nodeIndexOf = (sel) =>
  js(
    `(() => { ${HELPERS} ${HELPERS14}
      const target = visAll(${JSON.stringify(sel)})[0]; if (!target) return -1;
      const wrap = target.closest('.vue-flow__node');
      return wrap ? nodeEls().indexOf(wrap) : -1; })()`,
  )

/** 点右侧面板的「参数」/「变量」分页 */
async function clickInspTab(label) {
  return js(
    `(() => { ${HELPERS} ${HELPERS14}
      const t = inspTabs().find(b => b.textContent.trim() === ${JSON.stringify(label)});
      if (!t) return false; t.click(); return true; })()`,
  )
}

/** 点可见的某个按钮（按文本包含匹配），用于工具栏按钮、属性面板按钮 */
async function clickButton(text) {
  return js(
    `(() => { ${HELPERS}
      const b = visAll('button').find(x => x.textContent.replace(/\\s+/g,'').includes(${JSON.stringify(text)}));
      if (!b) return false; b.click(); return true; })()`,
  )
}

/** 顶栏设置条 / 右侧面板 / 画布的结构快照 */
const snapshot14 = () =>
  js(
    `(() => { ${HELPERS} ${HELPERS14}
      const sb = visAll('.settings-bar')[0];
      const btnText = Array.from(document.querySelectorAll('button')).filter(vis)
        .map(b => b.textContent.replace(/\\s+/g,' ').trim());
      // Naive UI 的 n-select 会给自己内部的 input/label 挂 title（当前选中项文本），
      // 那不是"我们写的悬停说明"。这里只统计表格里"我们自己加的 title"：排除 select 内部。
      const barTitled = sb ? Array.from(sb.querySelectorAll('[title]')) : [];
      const barTitledOwn = barTitled.filter(el => !el.closest('.n-base-selection, .n-select'));
      return {
        tooltipNodes: document.querySelectorAll('.n-tooltip').length,
        titledInBar: barTitled.length,
        titledOutsideSelect: barTitledOwn.length,
        titledDetail: barTitledOwn.slice(0, 5).map(el => el.tagName + '[' + el.getAttribute('title') + ']'),
        titledButtons: visAll('button[title]').length,
        barText: sb ? sb.textContent.replace(/\\s+/g,' ').trim() : '',
        barRadios: sb ? sb.querySelectorAll('.n-radio').length : -1,
        btnText,
        inspTabs: inspTabs().map(b => b.textContent.trim()),
        groupCount: groupNodes().length,
        groupTitles: groupNodes().map(g => (g.querySelector('.step-title') || {}).textContent.replace(/\\s+/g,' ').trim()),
        groupSummaries: groupNodes().map(g => (g.querySelector('.step-summary') || {}).textContent.trim()),
        nodeCount: nodeEls().length,
      };
    })()`,
  )

/** 右侧面板当前这一页里的字段标签 */
const inspectorLabels = () =>
  js(
    `(() => { ${HELPERS} ${HELPERS14}
      const e = visAll('.inspector')[0]; if (!e) return [];
      return Array.from(e.querySelectorAll('label')).map(l => l.textContent.trim()); })()`,
  )

/** 右侧面板里某个 label 对应控件的当前值（select / input 都尽量读出来） */
const inspectorValue = (labelText) =>
  js(
    `(() => { ${HELPERS} ${HELPERS14}
      const e = visAll('.inspector')[0]; if (!e) return null;
      const lab = Array.from(e.querySelectorAll('label')).find(l => l.textContent.trim() === ${JSON.stringify(labelText)});
      if (!lab) return null;
      const field = lab.closest('.field'); if (!field) return null;
      const sel = field.querySelector('.n-select'); if (sel) return sel.textContent.replace(/\\s+/g,' ').trim();
      const inp = field.querySelector('input, textarea'); return inp ? inp.value : null; })()`,
  )

const varRows = () =>
  js(`(() => { ${HELPERS} ${HELPERS14} return visAll('.var-row').length; })()`)

const varNames = () =>
  js(
    `(() => { ${HELPERS} ${HELPERS14}
      return visAll('.var-row').map(r => { const i = r.querySelector('input'); return i ? i.value : ''; }); })()`,
  )

/** 排空消息条（naive-ui 的 .n-message 是全局浮层，读文本判断是否弹了提示） */
const messages = () =>
  js(`Array.from(document.querySelectorAll('.n-message')).map(m => m.textContent.replace(/\\s+/g,' ').trim())`)
const clearMessages = () =>
  js(`(() => { document.querySelectorAll('.n-message').forEach(m => m.remove()); return true; })()`)

/** 构造一份 0.1.4 的测试脚本：一个组合节点 + 一个带输入方式的鼠标节点，二者相连。 */
function make14Script(name) {
  const mouse = (id, x, y, mode) => ({
    id,
    type: 'step',
    position: { x, y },
    data: {
      nodeType: 'mouse',
      label: '鼠标操作',
      once: false,
      params: { action: 'click', x: 10, y: 20, button: 'left', clicks: 1, input_mode: mode },
    },
  })
  const kb = (id, x, y) => ({
    id,
    type: 'step',
    position: { x, y },
    data: {
      nodeType: 'keyboard',
      label: '键盘按键',
      once: false,
      params: { action: 'press', keys: 'ctrl+a', input_mode: 'real' },
    },
  })
  return {
    format: 'agflow',
    version: 3,
    name,
    repeat: 1,
    window: null,
    screen: null,
    variables: [{ name: 'g1', type: 'number', value: '7' }],
    nodes: [
      {
        id: 'n1',
        type: 'step',
        position: { x: 60, y: 60 },
        data: {
          nodeType: 'group',
          label: '组合节点',
          once: false,
          params: {
            name: '我的组合',
            variables: [{ name: 'inner1', type: 'auto', value: 'x' }],
            nodes: [mouse('i1', 0, 0, 'real'), kb('i2', 220, 0)],
            edges: [{ id: 'ie1', source: 'i1', target: 'i2', sourceHandle: null }],
          },
        },
      },
      mouse('n2', 380, 60, 'simulated'),
    ],
    edges: [{ id: 'e1', source: 'n1', target: 'n2', sourceHandle: null }],
    scripts: {},
  }
}

async function main() {
  if (!BASE) throw new Error('缺少 AGT_URL（带 token 的页面地址）')

  await connect()
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: BASE })

  let ready = false
  for (let i = 0; i < 80; i++) {
    ready = await js(`!!document.querySelector('.tabstrip .tab')`)
    if (ready) break
    await sleep(400)
  }
  if (!ready) throw new Error('页面 32 秒内没有渲染出标签栏')
  await sleep(1200)

  const setFlowName = async (v) =>
    js(
      `(() => { ${HELPERS}
        const inp = nameInput(); if (!inp) return false;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, ${JSON.stringify(v)});
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      })()`,
    )

  // ---------- 静态结构断言（页面刚加载完的原始状态） ----------
  const info = await js(
    `(() => { ${HELPERS}
      const gear = visAll('.bb-gear')[0];
      const btns = visAll('.bb-btn');
      return {
        hasLogpanel: !!visAll('.logpanel')[0],
        hasLogfloat: !!document.querySelector('.logfloat'),
        gearFont: gear ? getComputedStyle(gear).fontSize : '',
        gearW: gear ? Math.round(gear.getBoundingClientRect().width) : 0,
        gearH: gear ? Math.round(gear.getBoundingClientRect().height) : 0,
        btnIcons: btns.map(b => (b.querySelector('.bb-icon') || {}).textContent || ''),
        btnExtraText: btns.map(b => Array.from(b.childNodes).filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent.trim()).join('|')),
        ctxMenuAtLoad: !!document.querySelector('.ctx-menu'),
        copyWords: Array.from(document.querySelectorAll('button'))
          .filter(b => vis(b) && !b.closest('.ctx-menu') && /复制|剪切|粘贴/.test(b.textContent))
          .map(b => b.textContent.replace(/\\s+/g, ' ').trim()),
      };
    })()`,
  )

  check('打开应用时日志默认收起（.logpanel 不存在）', !info.hasLogpanel)
  check('旧的浮层已移除（.logfloat 不存在）', !info.hasLogfloat)
  check('加载时没有残留的右键菜单', !info.ctxMenuAtLoad)
  check('顶栏不再有复制 / 剪切 / 粘贴按钮', info.copyWords.length === 0, '遗留=' + JSON.stringify(info.copyWords))
  check(
    '底部按钮只有图标、没有中文文案',
    info.btnIcons.length === 2 && info.btnExtraText.every((t) => t === ''),
    '图标=' + JSON.stringify(info.btnIcons) + ' 多余文本=' + JSON.stringify(info.btnExtraText),
  )
  check(
    '齿轮图标更大（字号 > 18px）',
    parseFloat(info.gearFont) > 18,
    'font-size=' + info.gearFont + ' 尺寸=' + info.gearW + 'x' + info.gearH,
  )

  // ---------- 日志：在下方展开 / 收起 ----------
  await clickInPage('.bb-btn')
  await sleep(400)
  const logAfterOpen = await js(
    `(() => { ${HELPERS}
      const lp = visAll('.logpanel')[0]; const bb = visAll('.bottombar')[0];
      return { open: !!lp, h: lp ? Math.round(lp.getBoundingClientRect().height) : 0,
        aboveBottombar: lp && bb ? lp.getBoundingClientRect().bottom <= bb.getBoundingClientRect().top + 1 : false,
        aboveCanvas: lp ? (() => { const c = visAll('.canvas')[0]; return c ? lp.getBoundingClientRect().top >= c.getBoundingClientRect().bottom - 1 : false })() : false };
    })()`,
  )
  check('点日志图标可在下方展开日志框', logAfterOpen.open && logAfterOpen.h > 100, '高度 ' + logAfterOpen.h + 'px')
  check('日志框贴在底部控制条上方', logAfterOpen.aboveBottombar)
  check('日志框在画布下方（不覆盖画布）', logAfterOpen.aboveCanvas)

  await clickInPage('.bb-btn')
  await sleep(400)
  check('再点一次收起', !(await js(`(() => { ${HELPERS} return !!visAll('.logpanel')[0]; })()`)))

  // ---------- 画布右键菜单 ----------
  const added = await clickInPage('.palette-item')
  await sleep(500)
  const n1 = await nodeCount()
  check('能从左侧步骤类型添加一个节点', added && n1 === 1, '节点数 = ' + n1)

  await rightClickNode(0)
  await sleep(300)
  const onNode = await ctxItems()
  check(
    '右键节点弹出「复制 / 剪切 / 粘贴」菜单',
    onNode.map((i) => i.label).join(',') === '复制,剪切,粘贴',
    JSON.stringify(onNode),
  )
  check('剪贴板为空时「粘贴」不可用', onNode[2] && onNode[2].disabled === true, JSON.stringify(onNode[2]))

  const copied = await clickCtxItem('复制')
  await sleep(300)
  check('点「复制」后菜单自动关闭', copied && !(await ctxMenuOpen()))

  await rightClickPane()
  await sleep(300)
  const onPane = await ctxItems()
  check(
    '右键空白画布只给「粘贴」且已可用',
    onPane.length === 1 && onPane[0].label === '粘贴' && onPane[0].disabled === false,
    JSON.stringify(onPane),
  )

  await clickCtxItem('粘贴')
  await sleep(500)
  const n2 = await nodeCount()
  check('在空白处右键粘贴能落一个节点', n2 === 2, '节点数 = ' + n2)

  await rightClickNode(0)
  await sleep(250)
  await clickCtxItem('剪切')
  await sleep(500)
  const n3 = await nodeCount()
  check('右键菜单里「剪切」能删掉节点', n3 === 1, '节点数 = ' + n3)

  await rightClickNode(0)
  await sleep(250)
  const opened = await ctxMenuOpen()
  await js(`(() => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); return true; })()`)
  await sleep(300)
  check('按 Esc 能关掉右键菜单', opened && !(await ctxMenuOpen()))

  // ---------- 准备三个可区分的标签 ----------
  await setFlowName('AAA')
  await sleep(200)
  await clickInPage('.tab-add')
  await sleep(400)
  await setFlowName('BBB')
  await sleep(200)
  await clickInPage('.tab-add')
  await sleep(400)
  await setFlowName('CCC')
  await sleep(300)

  const before = await names()
  check('准备三个标签', before.length === 3, '顺序 = ' + JSON.stringify(before))

  // ---------- 标签拖拽排序 ----------
  const d1 = await dragTo(2, 0, 'CCC,AAA,BBB')
  check('拖动标签改变顺序：CCC 拖到最前', d1.ok, '结果 = ' + JSON.stringify(d1.got))

  const d2 = await dragTo(0, -1, 'AAA,BBB,CCC')
  check('反向拖动也生效：CCC 拖到最后', d2.ok, '结果 = ' + JSON.stringify(d2.got))

  const d3 = await dragTo(0, 1, 'BBB,AAA,CCC', true)
  check('相邻拖动：AAA 拖到 BBB 之后', d3.ok, '结果 = ' + JSON.stringify(d3.got))

  // ==========================================================================
  // 0.1.4
  // ==========================================================================
  const s14 = await snapshot14()

  // ---------- ① 悬停说明全部去掉 ----------
  check(
    '页面上没有任何悬停提示气泡（.n-tooltip）',
    s14.tooltipNodes === 0,
    '数量 = ' + s14.tooltipNodes,
  )
  check(
    '设置条 / 可见按钮上都没有我们自己加的 title 悬停说明',
    s14.tooltipNodes === 0 && s14.titledOutsideSelect === 0 && s14.titledButtons === 0,
    `tooltip=${s14.tooltipNodes} 按钮=${s14.titledButtons} 设置条自有=${s14.titledOutsideSelect}` +
      (s14.titledDetail.length ? ' ' + JSON.stringify(s14.titledDetail) : '') +
      `（select 内部 ${s14.titledInBar - s14.titledOutsideSelect} 个不算）`,
  )

  // ---------- ② 顶栏去掉「输入方式」全局单选 + 按钮改名 ----------
  check(
    '顶栏设置条不再有「输入方式」全局单选',
    !/输入方式/.test(s14.barText) && s14.barRadios === 0,
    '文本=' + JSON.stringify(s14.barText) + ' radio=' + s14.barRadios,
  )
  check(
    '工具栏按钮已改名为「✂ 拆分节点 / 📦 合并节点」',
    s14.btnText.some((t) => t.includes('拆分节点')) &&
      s14.btnText.some((t) => t.includes('合并节点')) &&
      !s14.btnText.some((t) => /拆分录制|打包合并/.test(t)),
    JSON.stringify(s14.btnText.filter((t) => /拆分|合并|录制/.test(t))),
  )

  // ---------- ③ 右侧面板「参数 / 变量」分页 ----------
  check(
    '右侧面板有「参数 / 变量」两个标签页',
    s14.inspTabs.join(',') === '参数,变量',
    JSON.stringify(s14.inspTabs),
  )

  // ---------- ④ 加载一份含组合节点的脚本 ----------
  // 先开一个全新标签当落点：0.1.4 起改过名字的"空白脚本"也算有改动，
  // 直接往里加载会弹"要先保存吗"，新标签才是干净可被取代的。
  await clickInPage('.tab-add')
  await sleep(600)
  const tabCountBefore = (await names()).length
  await loadScript(make14Script('GRP'), 'grp.agflow')
  await sleep(1400)
  const loaded = await snapshot14()
  check('能加载含组合节点的脚本（画布 2 个节点）', loaded.nodeCount === 2, '节点数 = ' + loaded.nodeCount)
  check('组合节点按专属外观渲染（.step-node.is-group）', loaded.groupCount === 1, '数量 = ' + loaded.groupCount)
  check(
    '组合节点显示自己的名字与"双击编辑"摘要',
    loaded.groupTitles[0] === '我的组合' && /2 个节点/.test(loaded.groupSummaries[0] || ''),
    JSON.stringify({ title: loaded.groupTitles[0], summary: loaded.groupSummaries[0] }),
  )

  const grpIdx = await nodeIndexOf('.step-node.is-group')
  const mouseIdx = await nodeIndexOf('.step-node:not(.is-group)')
  check('画布上能定位到组合节点与普通节点', grpIdx >= 0 && mouseIdx >= 0, `组合=${grpIdx} 鼠标=${mouseIdx}`)

  // ---------- ⑤ 单击组合节点：属性面板可改名称等属性 ----------
  await nodeClick(grpIdx, false)
  await sleep(400)
  const grpInsp = await inspectorLabels()
  check(
    '单击组合节点出属性面板（名称 / 内容）',
    grpInsp.includes('名称') && grpInsp.includes('内容'),
    JSON.stringify(grpInsp),
  )
  const grpNameVal = await inspectorValue('名称')
  check('组合节点名称在面板里可读可改', grpNameVal === '我的组合', '值 = ' + JSON.stringify(grpNameVal))

  // ---------- ⑥ 单击输入节点：输入方式已下移到节点参数 ----------
  await nodeClick(mouseIdx, false)
  await sleep(400)
  const mouseInsp = await inspectorLabels()
  check('输入节点的参数里有「输入方式」', mouseInsp.includes('输入方式'), JSON.stringify(mouseInsp))
  const modeVal = await inspectorValue('输入方式')
  check(
    '输入方式跟着节点走（读到脚本里存的「后台消息」）',
    /后台消息|模拟/.test(String(modeVal)),
    '当前值 = ' + JSON.stringify(modeVal),
  )

  // ---------- ⑦ 变量分页：根脚本看到的是全局变量 ----------
  await clickInspTab('变量')
  await sleep(350)
  check('切到「变量」分页能管理变量', (await varRows()) === 1, '行数 = ' + (await varRows()))
  check('根脚本这一层列出的是全局变量 g1', (await varNames()).join(',') === 'g1', JSON.stringify(await varNames()))
  await clickButton('新增变量')
  await sleep(300)
  check('「＋ 新增变量」能加一行', (await varRows()) === 2, '行数 = ' + (await varRows()))

  // ---------- ⑧ 双击组合节点 → 新标签里编辑它内部那张图 ----------
  await nodeDblClick(grpIdx)
  await sleep(900)
  const namesAfterGroup = await names()
  check(
    '双击组合节点会新开一个编辑标签',
    namesAfterGroup.length === tabCountBefore + 1 && namesAfterGroup.includes('我的组合'),
    JSON.stringify(namesAfterGroup),
  )
  const grpIcon = await js(
    `(() => { ${HELPERS}
      const t = visAll('.tab').find(x => x.querySelector('.tab-name').textContent.trim() === '我的组合');
      return t ? (t.querySelector('.tab-icon') || {}).textContent : null; })()`,
  )
  check('组合节点标签用 🧩 图标', grpIcon === '🧩', '图标 = ' + JSON.stringify(grpIcon))
  check('组合节点标签里能看到它内部的 2 个节点', (await js(`(() => { ${HELPERS} ${HELPERS14} return nodeEls().length; })()`)) === 2)

  // ---------- ⑨ 组合节点里的变量是"局部变量"，与全局隔离 ----------
  await clickInspTab('变量')
  await sleep(350)
  const innerVars = await varNames()
  check(
    '组合节点编辑页里管理的是它自己的局部变量',
    innerVars.join(',') === 'inner1',
    JSON.stringify(innerVars),
  )
  const scopeText = await js(
    `(() => { ${HELPERS} ${HELPERS14} return inspText(); })()`,
  )
  check('局部变量页明确写了"局部变量"', /局部变量/.test(scopeText), scopeText.slice(0, 60))

  // 切回「GRP」这个根脚本标签 → 变量页仍是全局那些
  // （注意不能点第 0 个标签：此刻标签是 [BBB, AAA, CCC, GRP, 我的组合]，第 0 个是 BBB 那个空脚本）
  await js(
    `(() => { ${HELPERS} ${HELPERS14}
      const t = Array.from(document.querySelectorAll('.tab')).filter(vis)
        .find(x => x.querySelector('.tab-name').textContent.trim() === 'GRP');
      if (!t) return false; t.click(); return true; })()`,
  )
  await sleep(700)
  await clickInspTab('变量')
  await sleep(350)
  const rootVars = await varNames()
  check(
    '根脚本与组合节点的变量互不干扰（全局 g1 / 局部 inner1）',
    rootVars.includes('g1') && !rootVars.includes('inner1'),
    JSON.stringify(rootVars),
  )

  // ---------- ⑩ 「📦 合并节点」：把选中的相邻节点收成一个组合节点 ----------
  await clearMessages()
  await js(
    `(() => { ${HELPERS} ${HELPERS14}
      const t = Array.from(document.querySelectorAll('.tab')).filter(vis).find(x => x.querySelector('.tab-name').textContent.trim() === 'GRP');
      if (!t) return false; t.click(); return true; })()`,
  )
  await sleep(800)
  await clickInspTab('参数')
  await nodeClick(0, false)
  await sleep(300)
  await nodeClick(1, true)
  await sleep(400)
  const selCount = await js(
    `(() => { ${HELPERS} ${HELPERS14} return nodeEls().filter(e => e.classList.contains('selected')).length; })()`,
  )
  const mergeBtn = await js(
    `(() => { ${HELPERS}
      const b = visAll('button').find(x => x.textContent.includes('合并节点'));
      return b ? { disabled: b.disabled, text: b.textContent.replace(/\\s+/g,' ').trim() } : null; })()`,
  )
  check(
    '选中 2 个相邻节点后「📦 合并节点」可用并显示数量',
    !!mergeBtn && mergeBtn.disabled === false && /\(2\)/.test(mergeBtn.text),
    JSON.stringify(mergeBtn) + ` 画布已选中=${selCount}`,
  )

  await clickButton('合并节点')
  await sleep(900)
  const merged = await snapshot14()
  const mergedMsgs = await messages()
  check(
    '合并后画布上出现一个组合节点（2 → 1）',
    merged.nodeCount === 1 && merged.groupCount === 1,
    `节点数=${merged.nodeCount} 组合=${merged.groupCount} 提示=${JSON.stringify(mergedMsgs)}`,
  )

  await nodeDblClick(0)
  await sleep(900)
  const nested = await js(`(() => { ${HELPERS} ${HELPERS14} return nodeEls().length; })()`)
  check('合并出来的组合节点可以双击进去，看到被收进去的 2 个节点', nested === 2, '内部节点数 = ' + nested)

  const failed = results.filter((r) => r.startsWith('FAIL')).length
  const text =
    `编辑器界面回归（纯页面内事件，不使用真实鼠标）@ ${new Date().toISOString()}\n` +
    `URL: ${BASE}\n\n` +
    results.join('\n') +
    `\n\n合计 ${results.length} 项，失败 ${failed} 项\n`
  writeFileSync(OUT, text, 'utf8')
  console.log(text)
  process.exit(failed === 0 ? 0 : 1)
}

main().catch((e) => {
  const text = `界面验证出错：${e && e.message}\n${(e && e.stack) || ''}\n`
  try {
    writeFileSync(OUT, text, 'utf8')
  } catch {
    /* ignore */
  }
  console.log(text)
  process.exit(1)
})
