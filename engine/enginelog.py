"""引擎运行日志：写轮转文件，供事后排查（v0.7.3 起）。

为什么需要：v0.7.2 及以前，引擎只把日志推给前端 WebSocket 并打印到控制台，**两者都不落盘**。
后端一旦意外退出，日志随之消失（用户问「能不能调出运行日志」时只能回答「调不出来」）。
配合打包成无控制台（--noconsole）之后，落盘更是唯一的可观测输出。

安全：日志里**绝不出现访问令牌**。所有记录都会过一遍 `_redact()`，把 `token=xxx` 掩成
`token=***`——引擎启动时打印的编辑器地址、uvicorn 的访问日志都带 `?token=`。
控制台（若存在）仍然显示完整地址，只有落盘的那份被掩掉。

设计取舍：
  - 落盘失败绝不影响引擎运行（所有入口都 try/except，失败就是没有日志）
  - 只记录「推给前端的 log / state / overlay / repeat」等结构化事件，**不记录 recorded**
    （键鼠录制的完整事件数组很大，写进去只会把有用信息挤出轮转窗口）
  - 关掉 uvicorn 的访问日志：前端每秒两个轮询请求，开着会以每秒两行的速度把 2MB 轮转窗口
    冲掉，反而看不到关键事件；WS 连接/断开另行显式记录
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import traceback
from pathlib import Path

_LOG_NAME = "engine.log"
_DEFAULT_MAX_BYTES = 2 * 1024 * 1024
_DEFAULT_BACKUPS = 3

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warn": logging.WARNING,
           "warning": logging.WARNING, "error": logging.ERROR}

_lock = threading.Lock()
_ready = False
_last_error = ""
# 防重入标记（见 _StreamToLogger.write）
_writing = threading.local()
_logger = logging.getLogger("autogametool")
# 窗口化打包后 stdout/stderr 是 None；从源码运行/开发时它们存在，需要继续回显到控制台
_orig_stdout = sys.stdout
_orig_stderr = sys.stderr

_TOKEN_RE = re.compile(r"(token=)[^&\s\"']+", re.IGNORECASE)
# 除 token= 之外的其它可能泄漏形式（Authorization 头、GitHub 令牌前缀……）
_EXTRA_PATTERNS = (
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b(gh[opsur]_)[A-Za-z0-9]{16,}"),
    re.compile(r"\b(github_pat_)[A-Za-z0-9_]{16,}"),
)
# 运行期登记的「已知密钥」：整串精确替换，最可靠（引擎自己的本地令牌就走这条）
_secrets: set[str] = set()


def log_dir() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "AutoGameTool"


def log_path() -> Path:
    return log_dir() / _LOG_NAME


def register_secret(value: str) -> None:
    """登记一个必须从日志里抹掉的字面量（例如引擎的本地访问令牌）。

    比模式匹配可靠：无论它以什么形式出现（URL 参数、请求头、报错信息里被回显），
    只要出现就会被替换。太短的串不登记，避免把正常文本打成星号。
    """
    try:
        text = str(value or "")
        if len(text) >= 8:
            _secrets.add(text)
    except Exception:
        pass


def last_error() -> str:
    """最近一次 setup() 失败的原因。

    日志不可用时引擎照常运行（这是刻意的），但**必须留下原因**——
    否则「为什么没有日志文件」会变成第二个查不出来的问题。
    """
    return _last_error


def redact(text: str) -> str:
    """把访问令牌掩掉（唯一出口，所有写日志的路径都必须经过它）。"""
    out = text or ""
    try:
        for secret in tuple(_secrets):
            if secret and secret in out:
                out = out.replace(secret, "***")
        out = _TOKEN_RE.sub(r"\1***", out)
        for pat in _EXTRA_PATTERNS:
            out = pat.sub(lambda m: m.group(1) + "***", out)
    except Exception:
        pass
    return out


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            masked = redact(msg)
            if masked != msg:
                record.msg = masked
                record.args = ()
        except Exception:
            pass
        return True


class _StreamToLogger:
    """把 print() / 第三方库写到 stdout、stderr 的内容转发进日志。

    窗口化打包后这两个流是 None，代码里原有的 print 若不接管会直接抛 AttributeError。
    """

    def __init__(self, level: int, also=None) -> None:
        self._level = level
        self._also = also

    def write(self, text) -> int:
        if not text:
            return 0
        if self._also is not None:
            try:
                self._also.write(text)  # 控制台照旧显示原文（含完整地址）
            except Exception:
                pass
        # 防重入：日志不可用时 `_logger` 没有 handler，会落到 logging.lastResort 写 stderr，
        # 而 stderr 又被本类接管 —— 不挡住就会无限递归、把同一行重复打印很多遍。
        if getattr(_writing, "active", False):
            return len(text)
        _writing.active = True
        try:
            for line in str(text).splitlines():
                if line.strip():
                    _logger.log(self._level, line.rstrip())
        except Exception:
            pass
        finally:
            _writing.active = False
        return len(text)

    def flush(self) -> None:
        if self._also is not None:
            try:
                self._also.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return
    try:
        _logger.error("主线程未捕获异常", exc_info=(exc_type, exc, tb))
    except Exception:
        pass
    if _orig_stderr is not None:
        try:
            traceback.print_exception(exc_type, exc, tb, file=_orig_stderr)
        except Exception:
            pass


def _thread_excepthook(args) -> None:
    """线程里的未捕获异常（例如 Tk 线程、钩子线程）——不接管的话它会静默消失。"""
    if args.exc_type is SystemExit:
        return
    try:
        _logger.error(
            "线程 %s 未捕获异常", getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    except Exception:
        pass


def setup(max_bytes: int = _DEFAULT_MAX_BYTES, backups: int = _DEFAULT_BACKUPS) -> Path | None:
    """安装文件日志（幂等）。返回日志路径；失败返回 None，且绝不影响引擎。"""
    global _ready, _last_error
    with _lock:
        if _ready:
            return log_path()
        # 先把标准流接管掉，这样下面万一失败也能从异常里看到原因
        try:
            sys.stdout = _StreamToLogger(logging.INFO, _orig_stdout)
            sys.stderr = _StreamToLogger(logging.ERROR, _orig_stderr)
        except Exception:
            pass
        try:
            path = log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                str(path), maxBytes=int(max_bytes), backupCount=int(backups), encoding="utf-8"
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
                                  datefmt="%Y-%m-%d %H:%M:%S")
            )
            handler.addFilter(_RedactFilter())

            _logger.setLevel(logging.INFO)
            _logger.handlers = [handler]
            _logger.propagate = False

            # uvicorn 自己的 logger 默认写 stderr：窗口化后没有 stderr，必须显式接管
            for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
                lg = logging.getLogger(name)
                lg.handlers = [handler]
                lg.propagate = False
                lg.setLevel(logging.INFO)

            sys.excepthook = _excepthook
            threading.excepthook = _thread_excepthook
            _ready = True
            _last_error = ""
            return path
        except Exception as e:
            _last_error = f"{type(e).__name__}: {e}"
            return None


def install_loop_handler(loop) -> None:
    """把 asyncio 里未处理的异常也记下来（后台任务抛异常时默认只打印一行）。"""
    try:
        def _handler(_, context):
            try:
                exc = context.get("exception")
                msg = context.get("message") or "asyncio 未处理异常"
                if exc is not None:
                    _logger.error("asyncio：%s", msg, exc_info=exc)
                else:
                    _logger.error("asyncio：%s", msg)
            except Exception:
                pass

        loop.set_exception_handler(_handler)
    except Exception:
        pass


def info(msg: str, *args) -> None:
    if not _ready:
        return
    try:
        _logger.info(msg, *args)
    except Exception:
        pass


def warn(msg: str, *args) -> None:
    if not _ready:
        return
    try:
        _logger.warning(msg, *args)
    except Exception:
        pass


def error(msg: str, *args) -> None:
    if not _ready:
        return
    try:
        _logger.error(msg, *args)
    except Exception:
        pass


def log_exit(reason: str) -> None:
    """记录退出原因——排查「后端为什么突然没了」时这行最关键。"""
    if not _ready:
        return
    try:
        _logger.warning("引擎退出：%s", reason)
    except Exception:
        pass


def note_broadcast(message: dict) -> None:
    """把「推给前端的结构化事件」同时写进运行日志。

    这样即使 WebSocket 断开、页面被关掉，运行过程仍然可以在文件里事后查看。
    刻意跳过 recorded（键鼠录制事件数组很大），避免把有用信息挤出轮转窗口。
    """
    if not _ready:
        return
    try:
        mtype = message.get("type")
        if mtype == "log":
            level = _LEVELS.get(str(message.get("level") or "info").lower(), logging.INFO)
            step = str(message.get("step") or "").strip()
            text = str(message.get("message") or "")
            _logger.log(level, "运行｜%s%s", f"[{step}] " if step else "", text)
        elif mtype in ("state", "overlay", "repeat"):
            _logger.info("事件｜%s", json.dumps(message, ensure_ascii=False))
    except Exception:
        pass
