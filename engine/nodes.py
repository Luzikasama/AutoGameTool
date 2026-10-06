"""25 个核心节点的执行实现（《节点设计规范 V1》第 17 节）。

分工：
  · 需要**控制流**的节点（判断 / 循环 / 终止 / 调用脚本）由 executor 直接处理 ——
    它们要改"下一步走哪条边"，不是单纯做一件事。
  · 其余节点在这里实现，统一签名 `async def handler(ex, params) -> None`。
    `ex` 是 Executor 实例，提供日志、变量表、停止/暂停检查、截图与坐标换算。

统一约定：
  · 参数里的文本一律过 `vars.resolve` / `vars.interpolate`，所以任何地方都能写 {{变量名}}。
  · 要输出数据的节点把结果写进 `ex.vars`（键名由节点的 save_* 参数决定）。
  · 任何单步异常都由 executor 捕获并记日志，**不中断整个流程**（挂机场景的取舍）；
    但"终止整个工作流"是例外，它由 terminate 节点显式表达。
"""
from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import inputctl
import vision
import window as winmod
from runvars import VarScope, coerce, eval_conditions, eval_expr, interpolate, resolve, to_number

# 终端里跑命令时用的解码顺序（Windows 中文环境下 cmd 的输出通常是 GBK）
_ENCODINGS = ('utf-8', 'gbk', 'cp936', 'latin-1')


def _decode(raw: bytes) -> str:
    if not raw:
        return ''
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


# 公开别名：executor 执行「命令」节点时要按同一套编码规则解码输出
decode_output = _decode


def _num(raw, scope: VarScope, default: float = 0) -> float:
    v = resolve(raw, scope)
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return float(default)


def _int(raw, scope: VarScope, default: int = 0) -> int:
    return int(round(_num(raw, scope, default)))


def _str(raw, scope: VarScope, default: str = '') -> str:
    v = resolve(raw, scope)
    if v is None:
        return default
    return str(v)


def _save(ex, key_name: str, value) -> None:
    """把结果写进变量表。键名为空表示用户没要这个输出，直接跳过。"""
    name = str(key_name or '').strip()
    if name:
        ex.vars.set(name, value)


def _resolve_save_key(raw, scope: VarScope) -> str:
    """输出变量名本身也允许写 {{}} —— 例如循环里按轮次写不同变量。"""
    return interpolate(raw, scope).strip()


# ===========================================================================
# ① 输入
# ===========================================================================

async def mouse(ex, p) -> None:
    scope = ex.vars
    action = str(p.get('action') or 'click')
    x = _int(p.get('x'), scope)
    y = _int(p.get('y'), scope)
    button = str(p.get('button') or 'left')
    if ex.scale:
        x, y = ex.scale(x, y)

    if action == 'move':
        duration = max(0, _int(p.get('duration_ms'), scope))
        if duration <= 0:
            await asyncio.to_thread(inputctl.move, x, y, ex.input_mode, ex.window_hwnd)
        else:
            # 平滑移动：分成 ~24 帧，每帧都查一次停止标志（长距离拖拽时"停止"要能立刻生效）
            start = await asyncio.to_thread(inputctl.probe_position) if hasattr(inputctl, 'probe_position') else None
            sx, sy = start if start else (x, y)
            steps = max(2, min(60, duration // 16))
            for i in range(1, steps + 1):
                if ex.stopped:
                    return
                await ex.wait_if_paused()
                t = i / steps
                cx = int(round(sx + (x - sx) * t))
                cy = int(round(sy + (y - sy) * t))
                await asyncio.to_thread(inputctl.move, cx, cy, ex.input_mode, ex.window_hwnd)
                await asyncio.sleep(duration / 1000.0 / steps)
        await ex.log('debug', f'鼠标移动到 ({x}, {y})')
        return

    if action == 'wheel':
        dx = _int(p.get('dx'), scope)
        dy = _int(p.get('dy'), scope)
        await asyncio.to_thread(inputctl.scroll, dx, dy, ex.input_mode, ex.window_hwnd, x, y)
        await ex.log('debug', f'滚轮 ({dx}, {dy}) @ ({x}, {y})')
        return

    if action == 'down':
        await asyncio.to_thread(inputctl.mouse_down, x, y, button, ex.input_mode, ex.window_hwnd)
        await ex.log('debug', f'鼠标按下 {button} @ ({x}, {y})')
        return
    if action == 'up':
        await asyncio.to_thread(inputctl.mouse_up, x, y, button, ex.input_mode, ex.window_hwnd)
        await ex.log('debug', f'鼠标松开 {button} @ ({x}, {y})')
        return

    btn = 'right' if action == 'right_click' else ('middle' if action == 'middle_click' else button)
    clicks = 2 if action == 'double_click' else max(1, min(10, _int(p.get('clicks'), scope, 1)))
    await asyncio.to_thread(inputctl.click, x, y, btn, clicks, ex.input_mode, ex.window_hwnd)
    await ex.log('debug', f'鼠标{"双击" if clicks == 2 else "点击"} {btn} x{clicks} @ ({x}, {y})')


async def keyboard(ex, p) -> None:
    scope = ex.vars
    action = str(p.get('action') or 'press')
    keys = _str(p.get('keys') or p.get('key'), scope).strip()
    if not keys:
        await ex.log('warn', '键盘节点没有设置按键，已跳过')
        return
    hold = max(0, _int(p.get('hold_ms'), scope, 30))
    if action == 'down':
        await asyncio.to_thread(inputctl.key_down, keys, ex.input_mode, ex.window_hwnd)
        await ex.log('debug', f'按键按下 {keys}')
        return
    if action == 'up':
        await asyncio.to_thread(inputctl.key_up, keys, ex.input_mode, ex.window_hwnd)
        await ex.log('debug', f'按键松开 {keys}')
        return
    await asyncio.to_thread(inputctl.key_down, keys, ex.input_mode, ex.window_hwnd)
    if hold > 0:
        await ex.sleep(hold / 1000.0)
    await asyncio.to_thread(inputctl.key_up, keys, ex.input_mode, ex.window_hwnd)
    await ex.log('debug', f'按键 {keys}')


# ---- 剪贴板（文本输入 / 剪贴板两个节点共用）----

def _clipboard_get() -> str:
    try:
        import win32clipboard  # type: ignore

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or '')
            return ''
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return ''


def _clipboard_set(text: str) -> bool:
    try:
        import win32clipboard  # type: ignore

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, str(text))
            return True
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return False


async def text_input(ex, p) -> None:
    scope = ex.vars
    text = interpolate(p.get('text') or '', scope)
    if not text:
        await ex.log('warn', '文本输入节点内容为空，已跳过')
        return
    method = str(p.get('method') or 'direct')
    if method == 'clipboard':
        previous = _clipboard_get()
        if not _clipboard_set(text):
            await ex.log('warn', '写入剪贴板失败，退回逐字符输入')
            method = 'direct'
        else:
            await asyncio.to_thread(inputctl.press_key, 'ctrl+v', ex.input_mode, ex.window_hwnd)
            await asyncio.sleep(0.15)
            if bool(p.get('restore_clipboard', True)) and previous:
                _clipboard_set(previous)
            await ex.log('debug', f'已通过剪贴板输入 {len(text)} 个字符')
            return
    interval = max(0, _int(p.get('interval_ms'), scope, 10))
    if interval <= 0:
        await asyncio.to_thread(inputctl.type_text, text, ex.input_mode, ex.window_hwnd)
    else:
        # 逐字符输入并留间隔：部分程序（老式输入框、游戏）吃不下瞬时连发
        for ch in text:
            if ex.stopped:
                return
            await asyncio.to_thread(inputctl.type_text, ch, ex.input_mode, ex.window_hwnd)
            await ex.sleep(interval / 1000.0)
    await ex.log('debug', f'已输入文本 {text[:20]!r}{"…" if len(text) > 20 else ""}')


async def clipboard(ex, p) -> None:
    scope = ex.vars
    action = str(p.get('action') or 'set')
    if action == 'set':
        text = interpolate(p.get('text') or '', scope)
        ok = _clipboard_set(text)
        await ex.log('debug' if ok else 'warn', ('已写入剪贴板' if ok else '写入剪贴板失败'))
        return
    if action == 'clear':
        ok = _clipboard_set('')
        await ex.log('debug' if ok else 'warn', ('已清空剪贴板' if ok else '清空剪贴板失败'))
        return
    text = _clipboard_get()
    key = _resolve_save_key(p.get('var'), scope) or 'clip'
    ex.vars.set(key, text)
    await ex.log('debug', f'已读取剪贴板 {len(text)} 个字符 → {key}')


# ===========================================================================
# ② 视觉
# ===========================================================================

async def find_image(ex, p) -> None:
    scope = ex.vars
    tpl_id = _str(p.get('template'), scope).strip()
    key_found = _resolve_save_key(p.get('save_found'), scope)
    key_x = _resolve_save_key(p.get('save_x'), scope)
    key_y = _resolve_save_key(p.get('save_y'), scope)
    key_score = _resolve_save_key(p.get('save_score'), scope)

    def fail(msg: str) -> None:
        if key_found:
            ex.vars.set(key_found, 'no')
        if key_x:
            ex.vars.set(key_x, -1)
        if key_y:
            ex.vars.set(key_y, -1)
        if key_score:
            ex.vars.set(key_score, 0)
        ex.last_message = msg

    if not tpl_id:
        await ex.log('error', '图像识别：还没有选择模板')
        fail('未选择模板')
        return
    try:
        template = await asyncio.to_thread(vision.load_template, tpl_id)
    except (FileNotFoundError, ValueError) as e:
        await ex.log('error', f'图像识别：模板不可用（{e}）')
        fail('模板不可用')
        return

    meta = await asyncio.to_thread(vision.load_template_meta, tpl_id)
    threshold = _num(p.get('threshold'), scope, 0.85)
    timeout_ms = max(0, _int(p.get('timeout_ms'), scope, 5000))
    scope_mode = str(p.get('scope') or 'auto')
    deadline = time.time() + timeout_ms / 1000.0

    while not ex.stopped:
        try:
            frame, ox, oy = await asyncio.to_thread(ex.grab, scope_mode)
        except Exception as e:
            await ex.log('error', f'图像识别：截图失败（{e}）')
            fail('截图失败')
            return
        found, mx, my, score, scale = await asyncio.to_thread(
            vision.match_template_auto, frame, template, meta, threshold
        )
        if found:
            sx, sy = mx + ox, my + oy
            if key_found:
                ex.vars.set(key_found, 'yes')
            if key_x:
                ex.vars.set(key_x, sx)
            if key_y:
                ex.vars.set(key_y, sy)
            if key_score:
                ex.vars.set(key_score, round(score, 4))
            extra = f'，缩放 x{scale:.2f}' if abs(scale - 1) > 0.01 else ''
            ex.last_message = f'找到「{tpl_id}」@ ({sx}, {sy})'
            await ex.log('info', f'图像识别：找到「{tpl_id}」位置 ({sx}, {sy})，相似度 {score:.3f}{extra}')
            return
        if time.time() >= deadline:
            await ex.log('info', f'图像识别：超时未找到「{tpl_id}」（最高相似度 {score:.3f}）')
            fail('未找到')
            return
        await ex.sleep(0.2)
    fail('已停止')


async def ocr(ex, p) -> None:
    scope = ex.vars
    source = str(p.get('source') or 'auto')
    key_text = _resolve_save_key(p.get('save_text'), scope)
    key_found = _resolve_save_key(p.get('save_found'), scope)
    region = p.get('region') if isinstance(p.get('region'), dict) else None

    try:
        if source == 'region' and region:
            frame, ox, oy = await asyncio.to_thread(ex.grab_region, region)
        else:
            frame, ox, oy = await asyncio.to_thread(ex.grab, source)
    except Exception as e:
        await ex.log('error', f'文字识别：截图失败（{e}）')
        if key_found:
            ex.vars.set(key_found, 'no')
        return

    try:
        items = await asyncio.to_thread(vision.ocr_frame, frame)
    except Exception as e:
        await ex.log('error', f'文字识别失败：{e}')
        if key_found:
            ex.vars.set(key_found, 'no')
        return

    joiner = {'newline': '\n', 'space': ' ', 'none': ''}.get(str(p.get('join') or 'newline'), '\n')
    text = joiner.join(it['text'] for it in items)
    if key_text:
        ex.vars.set(key_text, text)
    if key_found:
        ex.vars.set(key_found, 'yes' if items else 'no')
    ex.last_message = f'识别到 {len(items)} 段文字'
    preview = text.replace('\n', ' / ')[:60]
    await ex.log('info', f'文字识别：{len(items)} 段 · {preview!r}' if items else '文字识别：区域内没有文字')


async def color_check(ex, p) -> None:
    scope = ex.vars
    key_found = _resolve_save_key(p.get('save_found'), scope)
    key_x = _resolve_save_key(p.get('save_x'), scope)
    key_y = _resolve_save_key(p.get('save_y'), scope)
    try:
        target = vision.parse_hex_color(_str(p.get('color'), scope, '#ff0000'))
    except ValueError as e:
        await ex.log('error', f'颜色检测：{e}')
        if key_found:
            ex.vars.set(key_found, 'no')
        return
    tolerance = max(0, _int(p.get('tolerance'), scope, 12))
    min_pixels = max(1, _int(p.get('min_pixels'), scope, 1))
    source = str(p.get('source') or 'auto')
    region = p.get('region') if isinstance(p.get('region'), dict) else None

    try:
        if source == 'region' and region:
            frame, ox, oy = await asyncio.to_thread(ex.grab_region, region)
        else:
            frame, ox, oy = await asyncio.to_thread(ex.grab, source)
    except Exception as e:
        await ex.log('error', f'颜色检测：截图失败（{e}）')
        if key_found:
            ex.vars.set(key_found, 'no')
        return

    count, fx, fy = await asyncio.to_thread(vision.count_color, frame, target, tolerance)
    hit = count >= min_pixels
    if key_found:
        ex.vars.set(key_found, 'yes' if hit else 'no')
    if key_x:
        ex.vars.set(key_x, (fx + ox) if hit else -1)
    if key_y:
        ex.vars.set(key_y, (fy + oy) if hit else -1)
    ex.last_message = f'颜色命中 {count} 像素'
    await ex.log(
        'info',
        f'颜色检测：{"命中" if hit else "未命中"} {_str(p.get("color"), scope)}（{count} 像素，阈值 {min_pixels}）',
    )


async def pixel_check(ex, p) -> None:
    scope = ex.vars
    key_found = _resolve_save_key(p.get('save_found'), scope)
    key_color = _resolve_save_key(p.get('save_color'), scope)
    x = _int(p.get('x'), scope)
    y = _int(p.get('y'), scope)
    size = max(1, min(31, _int(p.get('size'), scope, 1)))
    try:
        target = vision.parse_hex_color(_str(p.get('color'), scope, '#00ff00'))
    except ValueError as e:
        await ex.log('error', f'像素检测：{e}')
        if key_found:
            ex.vars.set(key_found, 'no')
        return
    tolerance = max(0, _int(p.get('tolerance'), scope, 12))

    try:
        frame, ox, oy = await asyncio.to_thread(ex.grab, 'auto')
    except Exception as e:
        await ex.log('error', f'像素检测：截图失败（{e}）')
        if key_found:
            ex.vars.set(key_found, 'no')
        return

    local = await asyncio.to_thread(vision.pixel_bgr, frame, x - ox, y - oy, size)
    if local is None:
        await ex.log('warn', f'像素检测：坐标 ({x}, {y}) 超出画面范围')
        if key_found:
            ex.vars.set(key_found, 'no')
        return
    hit = vision.color_within(local, target, tolerance)
    if key_found:
        ex.vars.set(key_found, 'yes' if hit else 'no')
    hex_color = vision.to_hex_color(local)
    if key_color:
        ex.vars.set(key_color, hex_color)
    ex.last_message = f'像素 {hex_color}'
    await ex.log('info', f'像素检测 ({x}, {y})：实际 {hex_color} {"匹配" if hit else "不匹配"}')


async def region_analysis(ex, p) -> None:
    scope = ex.vars
    mode = str(p.get('mode') or 'changed')
    key = _resolve_save_key(p.get('save_value'), scope)
    source = str(p.get('source') or 'auto')
    region = p.get('region') if isinstance(p.get('region'), dict) else None

    try:
        if source == 'region' and region:
            frame, _ox, _oy = await asyncio.to_thread(ex.grab_region, region)
        else:
            frame, _ox, _oy = await asyncio.to_thread(ex.grab, source)
    except Exception as e:
        await ex.log('error', f'区域分析：截图失败（{e}）')
        return

    if mode == 'average_color':
        bgr = await asyncio.to_thread(vision.region_average_color, frame)
        hex_color = vision.to_hex_color(bgr)
        if key:
            ex.vars.set(key, hex_color)
        ex.last_message = f'平均颜色 {hex_color}'
        await ex.log('info', f'区域分析：平均颜色 {hex_color}')
        return

    if mode == 'screenshot':
        path = interpolate(p.get('save_path') or '', scope).strip()
        if not path:
            await ex.log('warn', '区域分析：没有设置截图保存路径')
            return
        out = Path(path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            ok = await asyncio.to_thread(vision._imwrite_unicode, out, frame)
        except Exception as e:
            await ex.log('error', f'区域分析：截图保存失败（{e}）')
            return
        if key:
            ex.vars.set(key, str(out) if ok else '')
        ex.last_message = f'已保存 {out.name}'
        await ex.log('info' if ok else 'error', f'区域分析：截图{"已保存到 " + str(out) if ok else "保存失败"}')
        return

    # changed：与参考图对比
    ref_id = _str(p.get('reference'), scope).strip()
    if not ref_id:
        await ex.log('warn', '区域分析：没有设置参考图，无法判断是否变化')
        if key:
            ex.vars.set(key, 'no')
        return
    try:
        ref = await asyncio.to_thread(vision.load_template, ref_id)
    except (FileNotFoundError, ValueError) as e:
        await ex.log('error', f'区域分析：参考图不可用（{e}）')
        if key:
            ex.vars.set(key, 'no')
        return
    ratio = await asyncio.to_thread(vision.region_diff_ratio, frame, ref)
    limit = _num(p.get('diff_threshold'), scope, 0.02)
    changed = ratio >= limit
    if key:
        ex.vars.set(key, 'yes' if changed else 'no')
    ex.last_message = f'变化率 {ratio:.2%}'
    await ex.log('info', f'区域分析：变化率 {ratio:.2%}（阈值 {limit:.2%}）→ {"有变化" if changed else "无变化"}')


# ===========================================================================
# ③ 流程（judge / loop / terminate 由 executor 处理）
# ===========================================================================

async def delay(ex, p) -> None:
    total_ms = max(0, _int(p.get('ms'), ex.vars, 1000))
    if total_ms <= 0:
        await ex.log('warn', '延时为 0ms，跳过')
        return
    remaining = total_ms
    while remaining > 0:
        if ex.stopped:
            await ex.log('warn', f'延时被中断（剩余 {remaining}ms）')
            return
        # 分段睡：挂机脚本的单个延时动辄几十秒，整段睡死会让「停止」迟迟不生效
        take = min(250, remaining)
        await ex.sleep(take / 1000.0)
        remaining -= take


async def wait(ex, p) -> None:
    """等待条件满足：图片出现 / 颜色出现 / 像素匹配 / 变量条件 / 窗口出现。

    统一按 200ms 轮询；超时后按 on_timeout 决定"继续"还是"终止整个工作流"。
    暂停**不**停表（与旧版一致）：否则暂停时长会被算进超时，恢复后立刻误判超时。
    """
    scope = ex.vars
    mode = str(p.get('mode') or 'image')
    timeout_ms = max(0, _int(p.get('timeout_ms'), scope, 15000))
    key = _resolve_save_key(p.get('save_found'), scope)
    deadline = time.time() + timeout_ms / 1000.0
    on_timeout = str(p.get('on_timeout') or 'continue')

    # 预加载要用的东西（模板 / 目标色），避免在轮询里反复读盘
    template = None
    meta: dict = {}
    target_color = None
    if mode == 'image':
        tpl_id = _str(p.get('template'), scope).strip()
        if not tpl_id:
            await ex.log('error', '等待：没有选择识别模板')
            return
        try:
            template = await asyncio.to_thread(vision.load_template, tpl_id)
            meta = await asyncio.to_thread(vision.load_template_meta, tpl_id)
        except (FileNotFoundError, ValueError) as e:
            await ex.log('error', f'等待：模板不可用（{e}）')
            return
    elif mode in ('color', 'pixel'):
        try:
            target_color = vision.parse_hex_color(_str(p.get('color'), scope, '#ff0000'))
        except ValueError as e:
            await ex.log('error', f'等待：{e}')
            return

    def satisfied() -> tuple[bool, str]:
        """返回值 = (是否满足, 说明)。截图类失败由外层捕获。"""
        if mode == 'variable':
            ok = eval_conditions(p, scope)
            return ok, ''
        if mode == 'window':
            kw = _str(p.get('title'), scope).strip()
            found = winmod.find_window_by_title(kw)
            if found:
                ex.vars.set('wait_hwnd', found['hwnd'])
            return bool(found), ''
        if mode == 'image':
            frame, _ox, _oy = ex.grab('auto')
            found, mx, my, score, _s = vision.match_template_auto(frame, template, meta, _num(p.get('threshold'), scope, 0.85))
            return found, f'{score:.3f}'
        if mode == 'color':
            region = p.get('region') if isinstance(p.get('region'), dict) else None
            frame, _ox, _oy = ex.grab_region(region) if region else ex.grab('auto')
            count, _fx, _fy = vision.count_color(frame, target_color, _int(p.get('tolerance'), scope, 12))
            return count > 0, f'{count} 像素'
        # pixel
        frame, ox, oy = ex.grab('auto')
        local = vision.pixel_bgr(frame, _int(p.get('x'), scope) - ox, _int(p.get('y'), scope) - oy, 1)
        if local is None:
            return False, '越界'
        return vision.color_within(local, target_color, _int(p.get('tolerance'), scope, 12)), vision.to_hex_color(local)

    while not ex.stopped:
        try:
            ok, info = await asyncio.to_thread(satisfied)
        except Exception as e:
            await ex.log('warn', f'等待：检测失败（{e}），继续重试')
            ok, info = False, ''
        if ok:
            if key:
                ex.vars.set(key, 'yes')
            ex.last_message = '等待条件已满足'
            await ex.log('info', f'等待：条件已满足{"（" + info + "）" if info else ""}')
            return
        if time.time() >= deadline:
            if key:
                ex.vars.set(key, 'no')
            ex.last_message = '等待超时'
            if on_timeout == 'terminate':
                await ex.log('warn', '等待：超时未满足条件 → 终止整个工作流')
                ex.stopped = True
            else:
                await ex.log('warn', '等待：超时未满足条件 → 继续执行')
            return
        await ex.sleep(0.2)

    if key:
        ex.vars.set(key, 'no')


# ===========================================================================
# ④ 工具（script_call 由 executor 处理）
# ===========================================================================

async def record(ex, p) -> None:
    events = p.get('events') or []
    if not isinstance(events, list) or not events:
        await ex.log('warn', '录制内容为空，跳过')
        return
    try:
        speed = float(resolve(p.get('speed'), ex.vars) or 1.0)
    except (TypeError, ValueError):
        speed = 1.0
    if speed <= 0:
        speed = 1.0
    repeat = max(1, min(1000, _int(p.get('repeat'), ex.vars, 1)))
    await ex.log('info', f'回放录制：{len(events)} 个事件 × {repeat} 次，速度 x{speed}')
    for r in range(repeat):
        if ex.stopped:
            return
        if repeat > 1:
            await ex.log('debug', f'回放第 {r + 1}/{repeat} 次')
        await ex._replay_events(events, speed)
    await ex.log('info', '录制回放完成')


async def autoclick(ex, p) -> None:
    scope = ex.vars
    try:
        x = _int(p.get('x'), scope)
        y = _int(p.get('y'), scope)
        count = max(1, min(100000, _int(p.get('count'), scope, 10)))
        interval_ms = max(0, min(600000, _int(p.get('interval_ms'), scope, 100)))
    except (TypeError, ValueError):
        await ex.log('error', '连点器参数无效（坐标 / 次数 / 间隔必须是整数）')
        return
    button = str(p.get('button') or 'left')
    if ex.scale:
        x, y = ex.scale(x, y)
    rate = f'，约 {1000 / interval_ms:.1f} 次/秒' if interval_ms > 0 else ''
    await ex.log('info', f'连点器开始：坐标 ({x}, {y})，{count} 次，间隔 {interval_ms}ms{rate}')
    done = 0
    for i in range(count):
        if ex.stopped:
            await ex.log('warn', f'连点器被中断（已完成 {done}/{count} 次）')
            return
        await ex.wait_if_paused()
        if ex.stopped:
            await ex.log('warn', f'连点器被中断（已完成 {done}/{count} 次）')
            return
        try:
            await asyncio.to_thread(inputctl.click, x, y, button, 1, ex.input_mode, ex.window_hwnd)
            done += 1
        except Exception as e:
            await ex.log('warn', f'连点器第 {i + 1} 次点击失败: {e}')
        if interval_ms > 0:
            await ex.sleep(interval_ms / 1000.0)
    if ex.stopped:
        await ex.log('warn', f'连点器被中断（已完成 {done}/{count} 次）')
        return
    await ex.log('info', f'连点器完成：共点击 {done} 次')


async def external_tool(ex, p) -> None:
    scope = ex.vars
    mode = str(p.get('mode') or 'program')
    key_out = _resolve_save_key(p.get('save_var'), scope)
    key_code = _resolve_save_key(p.get('save_code'), scope)
    timeout_ms = max(100, _int(p.get('timeout_ms'), scope, 10000))

    if mode == 'http':
        url = _str(p.get('url'), scope).strip()
        if not url:
            await ex.log('error', '外部工具：没有填写 URL')
            return
        method = str(p.get('method') or 'GET').upper()
        headers = {}
        for line in str(p.get('headers') or '').splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip()] = v.strip()
        data = interpolate(p.get('body') or '', scope).encode('utf-8') if p.get('body') else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            def _do() -> tuple[int, str]:
                with urllib.request.urlopen(req, timeout=timeout_ms / 1000.0) as resp:
                    return int(resp.status), _decode(resp.read())

            status, body = await asyncio.to_thread(_do)
        except urllib.error.HTTPError as e:
            status, body = int(e.code), _decode(e.read() or b'')
        except Exception as e:
            await ex.log('error', f'外部工具：HTTP 请求失败（{e}）')
            if key_code:
                ex.vars.set(key_code, -1)
            return
        if key_out:
            ex.vars.set(key_out, body)
        if key_code:
            ex.vars.set(key_code, status)
        ex.last_message = f'HTTP {status}'
        await ex.log('info', f'外部工具：{method} {url} → {status}（{len(body)} 字符）')
        return

    path = _str(p.get('path'), scope).strip()
    if not path:
        await ex.log('error', '外部工具：没有填写程序路径')
        return
    args = _str(p.get('args'), scope)
    cwd = _str(p.get('cwd'), scope).strip() or None
    wait = bool(p.get('wait', False))
    cmd = f'{path} {args}'.strip()
    await ex.log('info', f'外部工具：启动 {cmd}')
    if not wait:
        try:
            import subprocess

            await asyncio.to_thread(
                lambda: subprocess.Popen(cmd, cwd=cwd, shell=False)  # noqa: S603 - 用户显式配置的命令
            )
        except Exception as e:
            await ex.log('error', f'外部工具：启动失败（{e}）')
            return
        if key_code:
            ex.vars.set(key_code, 0)
        return
    code, out = await ex.run_shell(cmd, cwd, timeout_ms, 'cmd')
    if key_out:
        ex.vars.set(key_out, out)
    if key_code:
        ex.vars.set(key_code, code)
    ex.last_message = f'退出码 {code}'
    await ex.log('info', f'外部工具：已结束，退出码 {code}')


# ===========================================================================
# ⑤ 数据
# ===========================================================================

async def variable(ex, p) -> None:
    scope = ex.vars
    action = str(p.get('action') or 'set')
    name = interpolate(p.get('name') or '', scope).strip()
    if not name:
        await ex.log('warn', '变量节点：没有填写变量名')
        return
    if action == 'delete':
        scope.delete(name)
        await ex.log('debug', f'已删除变量 {name}')
        return
    if action == 'get':
        target = interpolate(p.get('target') or '', scope).strip()
        if not target:
            await ex.log('warn', '变量节点：没有填写"复制到变量"的目标名')
            return
        value = scope.get(name)
        scope.set(target, value)
        await ex.log('debug', f'变量 {name} → {target}（{value!r}）')
        return
    raw = p.get('value')
    if isinstance(raw, str):
        # 整串是一个 {{var}} 时保留原始类型，否则插值 + 按声明类型转换
        value = resolve(raw, scope, str(p.get('var_type') or 'auto'))
    else:
        value = coerce(raw, str(p.get('var_type') or 'auto'))
    scope.set(name, value)
    await ex.log('debug', f'变量 {name} = {value!r}')


async def calculate(ex, p) -> None:
    scope = ex.vars
    expr = p.get('expr')
    key = _resolve_save_key(p.get('save_var'), scope) or 'result'
    try:
        value = eval_expr(str(expr or ''), scope)
    except ValueError as e:
        await ex.log('error', f'运算失败：{e}')
        return
    precision = max(0, min(10, _int(p.get('precision'), scope, 4)))
    rounded = round(value, precision)
    out = int(rounded) if float(rounded).is_integer() else rounded
    scope.set(key, out)
    ex.last_message = f'{expr} = {out}'
    await ex.log('info', f'运算：{expr} = {out} → {key}')


async def text_process(ex, p) -> None:
    import re as _re

    scope = ex.vars
    action = str(p.get('action') or 'replace')
    key = _resolve_save_key(p.get('save_var'), scope) or 'text_result'
    text = interpolate(p.get('input') or '', scope)
    result = text

    if action == 'concat':
        result = text + interpolate(p.get('input2') or '', scope)
    elif action == 'substr':
        start = max(0, _int(p.get('start'), scope, 0))
        length = max(0, _int(p.get('length'), scope, 10))
        result = text[start:start + length] if length else text[start:]
    elif action == 'replace':
        find = interpolate(p.get('find') or '', scope)
        repl = interpolate(p.get('replace') or '', scope)
        if find:
            if bool(p.get('use_regex')):
                try:
                    result = _re.sub(find, repl, text)
                except _re.error as e:
                    await ex.log('error', f'文本处理：正则表达式有误（{e}）')
                    return
            else:
                result = text.replace(find, repl)
    elif action == 'regex':
        pattern = str(p.get('pattern') or '')
        try:
            m = _re.search(pattern, text)
        except _re.error as e:
            await ex.log('error', f'文本处理：正则表达式有误（{e}）')
            return
        if m:
            gi = max(0, _int(p.get('group'), scope, 0))
            try:
                result = m.group(gi)
            except IndexError:
                result = ''
        else:
            result = ''
    elif action == 'to_number':
        n = to_number(text)
        result = n if n is not None else ''
    elif action == 'trim':
        result = text.strip()
    elif action == 'case':
        result = text.upper() if str(p.get('mode') or 'upper') == 'upper' else text.lower()
    elif action == 'split':
        sep = interpolate(p.get('sep') if p.get('sep') is not None else ',', scope)
        idx = max(0, _int(p.get('index'), scope, 0))
        parts = text.split(sep)
        result = parts[idx] if idx < len(parts) else ''

    scope.set(key, result)
    ex.last_message = f'{action} → {key}'
    await ex.log('info', f'文本处理（{action}）：{str(result)[:40]!r} → {key}')


# ===========================================================================
# ⑥ 系统
# ===========================================================================

async def window(ex, p) -> None:
    scope = ex.vars
    action = str(p.get('action') or 'activate')
    title = _str(p.get('title'), scope).strip()
    key_hwnd = _resolve_save_key(p.get('hwnd_var'), scope)
    key_found = _resolve_save_key(p.get('save_found'), scope)

    hwnd = 0
    if title:
        info = await asyncio.to_thread(winmod.find_window_by_title, title)
        if info:
            hwnd = int(info['hwnd'])
            if key_hwnd:
                scope.set(key_hwnd, hwnd)
    else:
        hwnd = int(ex.window_hwnd or 0)
    if key_found:
        scope.set(key_found, 'yes' if hwnd else 'no')
    if not hwnd:
        await ex.log('warn', f'窗口：没找到标题含「{title}」的窗口' if title else '窗口：没有绑定窗口，也没有填标题关键字')
        return

    if action == 'find':
        await ex.log('info', f'窗口：找到 hwnd={hwnd}')
        return
    if action == 'activate':
        ok = await asyncio.to_thread(winmod.focus_window, hwnd)
        await ex.log('info' if ok else 'warn', f'窗口：{"已激活" if ok else "激活失败（可能被系统前台限制拦住）"} hwnd={hwnd}')
        return
    if action == 'minimize':
        ok = await asyncio.to_thread(winmod.minimize_window, hwnd)
        await ex.log('info', f'窗口：{"已最小化" if ok else "最小化失败"} hwnd={hwnd}')
        return
    if action == 'maximize':
        ok = await asyncio.to_thread(winmod.maximize_window, hwnd)
        await ex.log('info', f'窗口：{"已最大化" if ok else "最大化失败"} hwnd={hwnd}')
        return
    if action == 'restore':
        ok = await asyncio.to_thread(winmod.restore_window, hwnd)
        await ex.log('info', f'窗口：{"已还原" if ok else "还原失败"} hwnd={hwnd}')
        return
    if action == 'move':
        x = _int(p.get('x'), scope)
        y = _int(p.get('y'), scope)
        w = max(1, _int(p.get('width'), scope, 800))
        h = max(1, _int(p.get('height'), scope, 600))
        ok = await asyncio.to_thread(winmod.move_window, hwnd, x, y, w, h)
        await ex.log('info', f'窗口：移动到 ({x}, {y}) 尺寸 {w}×{h} {"成功" if ok else "失败"}')
        return
    if action == 'close':
        ok = await asyncio.to_thread(winmod.close_window, hwnd)
        await ex.log('info', f'窗口：{"已发送关闭请求" if ok else "关闭失败"} hwnd={hwnd}')
        return


async def process(ex, p) -> None:
    scope = ex.vars
    action = str(p.get('action') or 'is_running')
    key = _resolve_save_key(p.get('save_var'), scope)
    key_pid = _resolve_save_key(p.get('save_pid'), scope)

    if action == 'start':
        path = _str(p.get('path'), scope).strip()
        if not path:
            await ex.log('error', '进程：没有填写程序路径')
            return
        args = _str(p.get('args'), scope)
        try:
            import subprocess

            argv = [path, *shlex.split(args, posix=False)] if args.strip() else [path]
            proc = await asyncio.to_thread(lambda: subprocess.Popen(argv))  # noqa: S603 - 用户显式配置
        except Exception as e:
            await ex.log('error', f'进程：启动失败（{e}）')
            return
        if key:
            scope.set(key, proc.pid)
        if key_pid:
            scope.set(key_pid, proc.pid)
        ex.last_message = f'已启动 PID {proc.pid}'
        await ex.log('info', f'进程：已启动 {path}（PID {proc.pid}）')
        return

    name = _str(p.get('name'), scope).strip()
    if not name:
        await ex.log('warn', '进程：没有填写进程名')
        if key:
            scope.set(key, 'no')
        return

    if action == 'kill':
        n = await asyncio.to_thread(winmod.kill_process, name)
        if key:
            scope.set(key, 'yes' if n else 'no')
        await ex.log('info' if n else 'warn', f'进程：已结束 {n} 个「{name}」进程' if n else f'进程：没有找到「{name}」')
        return

    pids = await asyncio.to_thread(winmod.find_pids_by_name, name)
    if key:
        scope.set(key, 'yes' if pids else 'no')
    if key_pid:
        scope.set(key_pid, pids[0] if pids else -1)
    ex.last_message = '运行中' if pids else '未运行'
    await ex.log('info', f'进程：{"「" + name + "」正在运行（PID " + ", ".join(map(str, pids[:3])) + "）" if pids else "「" + name + "」未在运行"}')


async def file(ex, p) -> None:
    scope = ex.vars
    action = str(p.get('action') or 'read')
    key = _resolve_save_key(p.get('save_var'), scope)
    raw_path = interpolate(p.get('path') or '', scope).strip()
    encoding = str(p.get('encoding') or 'utf-8')
    if not raw_path:
        await ex.log('error', '文件：没有填写路径')
        return
    path = Path(os.path.expandvars(os.path.expanduser(raw_path)))

    try:
        if action == 'read':
            text = await asyncio.to_thread(lambda: path.read_text(encoding=encoding, errors='replace'))
            if key:
                scope.set(key, text)
            ex.last_message = f'读取 {len(text)} 字符'
            await ex.log('info', f'文件：已读取 {path}（{len(text)} 字符）')
        elif action in ('write', 'append'):
            content = interpolate(p.get('content') or '', scope)
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)

            def _w():
                mode = 'a' if action == 'append' else 'w'
                with open(path, mode, encoding=encoding, newline='') as f:
                    f.write(content)

            await asyncio.to_thread(_w)
            if key:
                scope.set(key, str(path))
            ex.last_message = f'{"追加" if action == "append" else "写入"} {len(content)} 字符'
            await ex.log('info', f'文件：已{"追加" if action == "append" else "写入"} {path}（{len(content)} 字符）')
        elif action in ('copy', 'move'):
            dst = Path(interpolate(p.get('path2') or '', scope).strip())
            await asyncio.to_thread(dst.parent.mkdir, parents=True, exist_ok=True)
            if action == 'copy':
                await asyncio.to_thread(shutil.copy2, path, dst)
            else:
                await asyncio.to_thread(shutil.move, str(path), str(dst))
            if key:
                scope.set(key, str(dst))
            ex.last_message = f'已{"复制" if action == "copy" else "移动"}到 {dst}'
            await ex.log('info', f'文件：已{"复制" if action == "copy" else "移动"} {path} → {dst}')
        elif action == 'delete':
            if await asyncio.to_thread(path.is_dir):
                await asyncio.to_thread(shutil.rmtree, str(path))
            else:
                await asyncio.to_thread(path.unlink)
            if key:
                scope.set(key, 'yes')
            ex.last_message = '已删除'
            await ex.log('info', f'文件：已删除 {path}')
        elif action == 'exists':
            exists = await asyncio.to_thread(path.exists)
            if key:
                scope.set(key, 'yes' if exists else 'no')
            ex.last_message = '存在' if exists else '不存在'
            await ex.log('info', f'文件：{path} {"存在" if exists else "不存在"}')
        elif action == 'list':
            entries = await asyncio.to_thread(lambda: sorted(x.name for x in path.iterdir()))
            if key:
                scope.set(key, '\n'.join(entries))
            ex.last_message = f'{len(entries)} 个条目'
            await ex.log('info', f'文件：{path} 下有 {len(entries)} 个条目')
        elif action == 'mkdir':
            await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
            if key:
                scope.set(key, str(path))
            ex.last_message = '目录已就绪'
            await ex.log('info', f'文件：目录已就绪 {path}')
    except FileNotFoundError:
        if key:
            scope.set(key, 'no' if action == 'exists' else '')
        await ex.log('error', f'文件：路径不存在（{path}）')
    except Exception as e:
        await ex.log('error', f'文件：{action} 失败（{e}）')


async def command(ex, p) -> None:
    scope = ex.vars
    shell = str(p.get('shell') or 'cmd')
    cmd = interpolate(p.get('command') or '', scope).strip()
    key_out = _resolve_save_key(p.get('save_var'), scope)
    key_code = _resolve_save_key(p.get('save_code'), scope)
    if not cmd:
        await ex.log('warn', '命令：内容为空')
        return
    cwd = _str(p.get('cwd'), scope).strip() or None
    timeout_ms = max(100, _int(p.get('timeout_ms'), scope, 30000))
    wd = f'（工作目录 {cwd}）' if cwd else ''
    await ex.log('info', f'命令[{shell}]：{cmd}{wd}')
    code, out = await ex.run_shell(cmd, cwd, timeout_ms, shell)
    if key_out:
        scope.set(key_out, out)
    if key_code:
        scope.set(key_code, code)
    ex.last_message = f'退出码 {code}'
    tail = out.strip().splitlines()[-1] if out.strip() else ''
    await ex.log('info', f'命令结束：退出码 {code}' + (f'，输出末行 {tail[:60]!r}' if tail else ''))


# ===========================================================================
# 注册表
# ===========================================================================

HANDLERS = {
    # ① 输入
    'mouse': mouse,
    'keyboard': keyboard,
    'text_input': text_input,
    'clipboard': clipboard,
    # ② 视觉
    'find_image': find_image,
    'ocr': ocr,
    'color_check': color_check,
    'pixel_check': pixel_check,
    'region_analysis': region_analysis,
    # ③ 流程
    'delay': delay,
    'wait': wait,
    # ④ 工具
    'record': record,
    'autoclick': autoclick,
    'external_tool': external_tool,
    # ⑤ 数据
    'variable': variable,
    'calculate': calculate,
    'text_process': text_process,
    # ⑥ 系统
    'window': window,
    'process': process,
    'file': file,
    'command': command,
}

# 由 executor 直接处理（需要改控制流）的节点
CONTROL_NODES = {'judge', 'loop', 'terminate', 'script_call'}
