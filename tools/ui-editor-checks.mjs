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
 *
 * ⚠️ 输入方式：**只用页面内事件派发**（el.click() / new PointerEvent(...) / new MouseEvent('contextmenu')）。
 * 刻意不使用 CDP 的 Input.dispatchMouseEvent —— 那属于向浏览器注入输入事件，会碰到真实鼠标；
 * 而且本机 headless 环境下它本来也不生效（收不到任何事件）。页面内派发走的是与真实操作
 * **完全相同的那套处理函数**（pointerdown on .tab → window 上的 pointermove/pointerup → moveTab），
 * 足以验证业务逻辑是否正确。
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
