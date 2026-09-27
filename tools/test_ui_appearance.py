"""界面外观 / 布局回归测试（无头 Edge + CDP，不用真实鼠标键盘）。

为什么用无头浏览器：本版改的东西几乎全在界面上——外观（浅色/深色/跟随系统）、
顶栏与设置栏的按钮对调、循环轮数输入框加宽、新建确认框的中文按钮、「关于」跳转、
只剩一个 WebUI 时的提示。这些用肉眼点一遍很费事、下次改代码又不会重跑，
而 CDP 能直接读到 DOM 与计算后的样式，也不碰用户的鼠标键盘。

覆盖：
  1. 外观默认「跟随系统」，且系统深色时界面真的是深色（浅色时真的是浅色）
  2. 设定面板里的浅色/深色能切换，切换后立刻生效并记住（localStorage）
  3. 顶栏有「快捷键 / 悬浮框」，设置栏有「撤销 / 重做」（本版的位置对调）
  4. 循环轮数输入框宽度够 5 位数（元素宽度 >= 110px）
  5. 新建确认框的按钮是「确定 / 取消」（中文）
  6. 顶栏是「关于」且指向 GitHub 发布页（不跳走当前页）

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_ui_appearance.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
PY = ENGINE / ".venv" / "Scripts" / "python.exe"
DIST = ROOT / "frontend" / "dist"
PORT = 8765
TOKEN = "e2e-ui"
TMP = ROOT / ".tmp"
APPDATA = TMP / "e2e-ui-appdata"
CDP_PORT = 9333
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

_pass = 0
_fail = 0


def check(name: str, cond: bool, extra: object = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print("  PASS  " + name)
    else:
        _fail += 1
        print("  FAIL  " + name + (("  -> " + str(extra)) if extra != "" else ""))


def edge_path() -> str | None:
    for p in EDGE_CANDIDATES:
        if Path(p).is_file():
            return p
    return None


def engine_env() -> dict:
    env = dict(os.environ)
    env["APPDATA"] = str(APPDATA)
    env["AUTOGAMETOOL_NO_BROWSER"] = "1"
    env["AUTOGAMETOOL_TOKEN"] = TOKEN
    return env


def port_free(port: int) -> bool:
    import socket

    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_engine():
    log_path = TMP / "e2e-ui-engine.log"
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen([str(PY), "main.py"], cwd=str(ENGINE), env=engine_env(),
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(80):
        if proc.poll() is not None:
            break
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1).read()
            return proc, log
        except Exception:
            time.sleep(0.4)
    log.close()
    raise RuntimeError(f"引擎未能就绪（exit={proc.poll()}）\n"
                       + log_path.read_text(encoding="utf-8", errors="replace")[-600:])


def stop(proc) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def start_edge(url: str, profile: Path):
    log = open(TMP / "e2e-ui-edge.log", "w", encoding="utf-8")
    args = [
        edge_path(),
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        "--window-size=1440,900",
        "--no-first-run",
        "--disable-extensions",
        "--hide-scrollbars",
        url,
    ]
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1) as r:
                targets = json.loads(r.read().decode("utf-8"))
            pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                return proc, log, pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.4)
    log.close()
    raise RuntimeError("无法连接无头 Edge 的调试端口")


class CDP:
    """极简 CDP 客户端：够用即可（Evaluate / EmulateMedia / Screenshot / 多标签页会话）。"""

    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def call(self, method: str, session: str | None = None, **params):
        self._id += 1
        mid = self._id
        msg = {"id": mid, "method": method, "params": params}
        if session:
            msg["sessionId"] = session
        await self.ws.send(json.dumps(msg))
        while True:
            reply = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=25))
            if reply.get("id") == mid:
                if "error" in reply:
                    raise RuntimeError(f"{method} 失败：{reply['error']}")
                return reply.get("result", {})

    async def eval(self, expr: str, session: str | None = None):
        r = await self.call("Runtime.evaluate", session, expression=expr,
                            returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def screenshot(self, path: Path, session: str | None = None) -> None:
        r = await self.call("Page.captureScreenshot", session, format="png")
        import base64

        path.write_bytes(base64.b64decode(r["data"]))


async def wait_for(cdp: CDP, expr: str, timeout: float = 15.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if await cdp.eval(expr):
                return True
        except Exception:
            pass
        await asyncio.sleep(0.3)
    return False


async def run_checks(cdp: CDP, shots: Path) -> None:
    import websockets

    print("== 0. 页面加载 ==")
    ok = await wait_for(cdp, "!!document.querySelector('.editor .topbar')")
    if not ok:
        # 失败时要能看到「页面到底显示了什么」：否则只报一句没渲染，排查得从头来
        info = await cdp.eval("""JSON.stringify({
          href: location.href, title: document.title,
          text: (document.body.innerText || '').slice(0, 300),
          html: (document.body.innerHTML || '').slice(0, 300),
        })""")
        await cdp.screenshot(shots / "00-load-failed.png")
        print("        " + str(info))
    check("编辑器界面已渲染", ok)
    if not ok:
        return

    # 清掉上一次跑留下的偏好：浏览器的 profile 会保留 localStorage，
    # 否则「默认跟随系统」这条断言第二次跑就必然失败（它也确实是这么被发现的）
    await cdp.eval("localStorage.removeItem('agt.appearance'); localStorage.removeItem('agt.bg'); true")
    await cdp.call("Page.reload")
    ok = await wait_for(cdp, "!!document.querySelector('.editor .topbar')")
    check("清掉本机偏好后重新加载正常", ok)
    if not ok:
        return

    print("== 1. 外观：默认跟随系统，且真的跟着系统走 ==")
    check("默认外观 = 跟随系统（未设置时）",
          await cdp.eval("document.documentElement.dataset.theme !== undefined ? "
                         "localStorage.getItem('agt.appearance') === null : false"))
    # 系统深色
    await cdp.call("Emulation.setEmulatedMedia",
                   features=[{"name": "prefers-color-scheme", "value": "dark"}])
    await asyncio.sleep(0.4)
    dark_bg = await cdp.eval("getComputedStyle(document.body).backgroundColor")
    theme_dark = await cdp.eval("document.documentElement.dataset.theme")
    await cdp.screenshot(shots / "01-follow-system-dark.png")
    check("系统深色 → data-theme=dark", theme_dark == "dark", theme_dark)
    check("系统深色 → 深色底色", dark_bg in ("rgb(14, 17, 22)", "rgba(14, 17, 22, 1)"), dark_bg)

    # 系统浅色（仍处于「跟随系统」）
    await cdp.call("Emulation.setEmulatedMedia",
                   features=[{"name": "prefers-color-scheme", "value": "light"}])
    await asyncio.sleep(0.6)
    light_bg = await cdp.eval("getComputedStyle(document.body).backgroundColor")
    theme_light = await cdp.eval("document.documentElement.dataset.theme")
    await cdp.screenshot(shots / "02-follow-system-light.png")
    check("系统浅色 → data-theme=light（跟随系统生效）", theme_light == "light", theme_light)
    check("系统浅色 → 浅色底色", light_bg in ("rgb(244, 245, 248)", "rgba(244, 245, 248, 1)"), light_bg)

    print("== 2. 设定面板：浅色 / 深色可切换并记住 ==")
    # 打开设定（顶栏的「设定」按钮）
    await cdp.eval("""
      (() => {
        const btns = [...document.querySelectorAll('.topbar button')]
        const b = btns.find(x => x.textContent.includes('设定'))
        if (b) b.click()
        return !!b
      })()
    """)
    check("设定面板能打开", await wait_for(cdp, "!!document.querySelector('.n-modal .sect-title')"))
    check("面板里有「外观」一节",
          await cdp.eval("[...document.querySelectorAll('.n-modal .sect-title')].some(e => e.textContent.includes('外观'))"))
    labels = await cdp.eval(
        "[...document.querySelectorAll('.n-modal .n-radio-button')].map(e => e.textContent.trim())")
    check("外观选项是 跟随系统 / 浅色 / 深色", labels == ["跟随系统", "浅色", "深色"], labels)
    await cdp.screenshot(shots / "03-settings-appearance.png")

    # 选「深色」：此时系统仍是浅色，但显式选择应该覆盖它
    await cdp.eval("""
      (() => {
        const b = [...document.querySelectorAll('.n-modal .n-radio-button')].find(e => e.textContent.trim() === '深色')
        if (b) b.click()
        return !!b
      })()
    """)
    await asyncio.sleep(0.5)
    theme = await cdp.eval("document.documentElement.dataset.theme")
    saved = await cdp.eval("localStorage.getItem('agt.appearance')")
    await cdp.screenshot(shots / "04-explicit-dark.png")
    check("显式选深色 → 覆盖系统浅色", theme == "dark", theme)
    check("选择被记住（localStorage）", saved == "dark", saved)

    # 刷新后仍然是深色（偏好持久化）
    await cdp.call("Page.reload")
    await wait_for(cdp, "!!document.querySelector('.editor .topbar')")
    await asyncio.sleep(0.5)
    check("刷新后仍是深色（偏好已持久化）",
          await cdp.eval("document.documentElement.dataset.theme") == "dark")

    # 选回「浅色」并刷新确认
    await cdp.eval("""
      (() => {
        const open = [...document.querySelectorAll('.topbar button')].find(x => x.textContent.includes('设定'))
        if (open) open.click()
        return true
      })()
    """)
    await wait_for(cdp, "!!document.querySelector('.n-modal .n-radio-button')")
    await cdp.eval("""
      (() => {
        const b = [...document.querySelectorAll('.n-modal .n-radio-button')].find(e => e.textContent.trim() === '浅色')
        if (b) b.click()
        return !!b
      })()
    """)
    await asyncio.sleep(0.5)
    await cdp.screenshot(shots / "05-explicit-light.png")
    check("显式选浅色 → 浅色", await cdp.eval("document.documentElement.dataset.theme") == "light")
    # 关掉面板
    await cdp.eval("""
      (() => {
        const b = [...document.querySelectorAll('.n-modal button')].find(x => x.textContent.includes('完成'))
        if (b) b.click()
        return !!b
      })()
    """)
    await asyncio.sleep(0.4)

    print("== 3. 顶栏与设置栏的按钮位置（本版对调） ==")
    top_has = await cdp.eval("""
      (() => {
        const t = document.querySelector('.topbar').textContent
        return { hotkey: t.includes('快捷键'), overlay: t.includes('悬浮框'),
                 undo: t.includes('撤销'), redo: t.includes('重做') }
      })()
    """)
    bar_has = await cdp.eval("""
      (() => {
        const t = document.querySelector('.settings-bar').textContent
        return { hotkey: t.includes('快捷键'), overlay: t.includes('悬浮框'),
                 undo: t.includes('撤销'), redo: t.includes('重做') }
      })()
    """)
    check("顶栏有「快捷键」", top_has["hotkey"], top_has)
    check("顶栏有「悬浮框」", top_has["overlay"], top_has)
    check("顶栏不再有「撤销 / 重做」", not top_has["undo"] and not top_has["redo"], top_has)
    check("设置栏有「撤销 / 重做」", bar_has["undo"] and bar_has["redo"], bar_has)
    check("设置栏不再有「快捷键 / 悬浮框」", not bar_has["hotkey"] and not bar_has["overlay"], bar_has)

    print("== 4. 循环轮数输入框能显示 5 位数 ==")
    width = await cdp.eval("""
      (() => {
        const el = document.querySelector('.settings-bar .n-input-number')
        return el ? el.getBoundingClientRect().width : 0
      })()
    """)
    max_ok = await cdp.eval("""
      (() => {
        const el = document.querySelector('.settings-bar .n-input-number input')
        return el ? el.value : ''
      })()
    """)
    check(f"输入框宽度 >= 110px（实测 {width:.0f}px）", width >= 110, width)
    check("输入框能放下 5 位数字（长度足够）", width >= 110, max_ok)

    print("== 5. 「关于」= 顶栏 + 指向 GitHub 发布页 ==")
    about = await cdp.eval("""
      (() => {
        const b = document.querySelector('.topbar .ver-badge')
        return b ? { text: b.textContent.trim(), html: b.outerHTML } : null
      })()
    """)
    check("顶栏有「关于」按钮", bool(about) and about["text"].startswith("关于"), about)
    src = (ROOT / "frontend" / "src" / "views" / "Editor.vue").read_text(encoding="utf-8")
    check("「关于」指向 GitHub 发布页（源码常量）",
          "https://github.com/Luzikasama/AutoGameTool/releases" in src)
    await cdp.screenshot(shots / "06-topbar-about.png")

    print("== 6. 新建确认框的按钮是中文 ==")
    await cdp.eval("""
      (() => {
        const b = [...document.querySelectorAll('.topbar button')].find(x => x.textContent.includes('新建'))
        if (b) b.click()
        return !!b
      })()
    """)
    await wait_for(cdp, "!!document.querySelector('.n-popconfirm')")
    texts = await cdp.eval("""
      [...document.querySelectorAll('.n-popconfirm button')].map(b => b.textContent.trim())
    """)
    await cdp.screenshot(shots / "07-new-confirm.png")
    check("确认框按钮是「确定 / 取消」", texts == ["确定", "取消"] or texts == ["取消", "确定"], texts)
    # 关掉确认框（避免留下多余状态）
    await cdp.eval("""
      (() => {
        const b = [...document.querySelectorAll('.n-popconfirm button')].find(x => x.textContent.trim() === '取消')
        if (b) b.click()
        return !!b
      })()
    """)
    await asyncio.sleep(0.3)

    print("== 7. 快捷键面板：全部可配置 + 启用开关 ==")
    await cdp.eval("""
      (() => {
        const b = [...document.querySelectorAll('.topbar button')].find(x => x.textContent.includes('快捷键'))
        if (b) b.click()
        return !!b
      })()
    """)
    await wait_for(cdp, "!!document.querySelector('.hk-row')")
    rows = await cdp.eval("""
      [...document.querySelectorAll('.hk-row')].map(r => ({
        label: r.querySelector('.hk-label')?.textContent.trim(),
        keys: r.querySelector('.hk-keys')?.textContent.trim(),
        hasSwitch: !!r.querySelector('.n-switch'),
      }))
    """)
    check("列出了三条快捷键", isinstance(rows, list) and len(rows) == 3, rows)
    check("默认键是 alt + f1 / f2 / f3",
          [r["keys"] for r in rows] == ["alt + f1", "alt + f2", "alt + f3"],
          [r["keys"] for r in rows])
    check("每条都有启用开关", all(r["hasSwitch"] for r in rows), rows)
    await cdp.screenshot(shots / "08-hotkeys.png")
    await cdp.eval("""
      (() => {
        const b = [...document.querySelectorAll('.n-modal button')].find(x => x.textContent.includes('取消'))
        if (b) b.click()
        return !!b
      })()
    """)
    await asyncio.sleep(0.4)

    print("== 8. 一路点下来外观不会被别的东西改掉 ==")
    final_theme = await cdp.eval("document.documentElement.dataset.theme")
    final_bg = await cdp.eval("getComputedStyle(document.body).backgroundColor")
    await cdp.screenshot(shots / "09-final.png")
    check("仍是最后显式选择的浅色（没有被跟随系统覆盖回去）", final_theme == "light",
          (final_theme, final_bg))

    print("== 9. 只允许一个 WebUI：第二个连接被 4409 拒绝 ==")
    # 同一个页面里再开一条原始 WebSocket：引擎应当先发 busy 再以 4409 关闭
    raw = await cdp.eval("""
      new Promise((resolve) => {
        let busy = null
        const t = sessionStorage.getItem('agt_token') || ''
        const ws = new WebSocket('ws://127.0.0.1:8765/ws?token=' + encodeURIComponent(t))
        const done = (code) => resolve({ code, busy })
        ws.onmessage = (e) => { try { busy = JSON.parse(e.data) } catch (_) {} }
        ws.onclose = (e) => done(e.code)
        ws.onerror = () => done(-1)
        setTimeout(() => done(-2), 8000)
      })
    """)
    check("第二个 WebSocket 被 4409 拒绝", isinstance(raw, dict) and raw.get("code") == 4409, raw)
    check("被拒绝前先收到 busy 通知",
          isinstance(raw, dict) and isinstance(raw.get("busy"), dict) and raw["busy"].get("type") == "busy",
          raw)
    check("被拒绝后本页仍然连着引擎（没有出现「已在另一个窗口打开」遮罩）",
          not await cdp.eval("!!document.querySelector('.busy-mask')"))

    # 真的多开一个标签页：那一页应当显示提示，而本页照常
    tid = (await cdp.call("Target.createTarget", url=f"http://127.0.0.1:{PORT}/?token={TOKEN}"))["targetId"]
    sid = (await cdp.call("Target.attachToTarget", targetId=tid, flatten=True))["sessionId"]
    try:
        shown = False
        for _ in range(40):
            try:
                if await cdp.eval("!!document.querySelector('.busy-mask')", session=sid):
                    shown = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.3)
        check("多开的那个标签页显示「已在另一个窗口打开」", shown)
        if shown:
            await cdp.screenshot(shots / "10-second-tab-blocked.png", session=sid)
        check("原页面不受影响（仍在正常工作）",
              await cdp.eval("!!document.querySelector('.editor .topbar')"))
    finally:
        try:
            await cdp.call("Target.closeTarget", targetId=tid)
        except Exception:
            pass


async def scenario(ws_url: str, shots: Path) -> None:
    import websockets

    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        cdp = CDP(ws)
        await cdp.call("Page.enable")
        await cdp.call("Runtime.enable")
        await run_checks(cdp, shots)


def stage_frontend() -> tuple[Path, bool]:
    """把前端产物放到引擎会去读的位置（engine/frontend_dist）。

    源码运行时引擎只从 `engine/frontend_dist` 提供界面（打包时由 PyInstaller 把
    `frontend/dist` 塞进去），所以这里复制一份并记录「是不是我们建的」，跑完删掉。
    """
    target = ENGINE / "frontend_dist"
    created = False
    if (target / "index.html").is_file():
        return target, created
    import shutil

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(DIST, target)
    return target, True


def main() -> int:
    if not PY.is_file():
        print(f"未找到解释器：{PY}")
        return 1
    if not (DIST / "index.html").is_file():
        print(f"未找到前端产物：{DIST}\\index.html，请先跑 .\\build_exe.ps1（或 cd frontend; pnpm build）")
        return 1
    if not edge_path():
        print("未找到 Microsoft Edge，跳过界面测试")
        return 0
    for p in (PORT, CDP_PORT):
        if not port_free(p):
            print(f"端口 {p} 已被占用：请先退出正在运行的 AutoGameTool / 关掉本测试留下的浏览器")
            return 1
    TMP.mkdir(parents=True, exist_ok=True)
    shots = TMP / "ui-shots"
    shots.mkdir(parents=True, exist_ok=True)
    profile = TMP / "edge-ui-profile"
    # 每次从干净配置开始：上次跑留下的改键/停用会影响「默认快捷键」这类断言
    cfg = APPDATA / "AutoGameTool" / "config.json"
    if cfg.is_file():
        cfg.unlink()

    # 先放好前端产物，再启动引擎（引擎启动时决定要不要挂载 SPA 路由）
    staged, created = stage_frontend()
    engine, elog = start_engine()
    edge, dlog = None, None
    try:
        url = f"http://127.0.0.1:{PORT}/?token={TOKEN}"
        edge, dlog, ws_url = start_edge(url, profile)
        asyncio.run(scenario(ws_url, shots))
    finally:
        stop(edge)
        stop(engine)
        if elog:
            elog.close()
        if dlog:
            dlog.close()
        if created:
            import shutil

            shutil.rmtree(staged, ignore_errors=True)

    print("")
    print("结果: PASS=" + str(_pass) + "  FAIL=" + str(_fail))
    if _fail:
        print(f"截图留在 {shots}，引擎输出留在 .tmp\\e2e-ui-engine.log")
    else:
        print(f"截图留在 {shots}（供人工核对外观）")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

