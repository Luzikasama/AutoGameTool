"""引擎运行日志回归测试（不需要 GUI、不注入任何输入）

覆盖的是「事后能不能查」这件事本身，以及一个安全硬要求：

  1. setup() 会建出日志文件，且幂等（重复调用不会加重复 handler）
  2. **访问令牌绝不落盘**：`?token=xxx` 一律掩成 `token=***`
     —— 引擎启动时打印的编辑器地址、uvicorn 访问日志里都带 token，
        不掩就等于把令牌写进文件
  3. print() 的输出会被接管进日志（打包成无控制台后 stdout 是 None，
     不接管的话原有的 print 会直接抛 AttributeError）
  4. 推给前端的运行日志（type=log）会同时写进文件，**即使当时没有任何页面连接**
  5. 体积轮转生效（超过上限会切出 .1 备份）
  6. recorded 这类大数组**不写**日志（否则会把有用信息挤出轮转窗口）

用法：
    engine\\.venv\\Scripts\\python.exe tools\\test_engine_log.py
"""
import io
import logging
import os
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(_ENGINE))

# 必须先把 APPDATA 指到隔离目录：enginelog 按 APPDATA 决定日志位置，
# 否则这个测试会往用户真实的 %APPDATA%\AutoGameTool\engine.log 里写东西。
# 用项目内 .tmp（而不是系统临时目录）：受限沙箱下系统临时目录不允许建子目录。
_TMP = Path(__file__).resolve().parent.parent / ".tmp" / "logtest-appdata"
shutil.rmtree(_TMP, ignore_errors=True)
(_TMP / "AutoGameTool").mkdir(parents=True, exist_ok=True)
os.environ["APPDATA"] = str(_TMP)

import enginelog  # noqa: E402

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


def read_log() -> str:
    p = enginelog.log_path()
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


print("== 1. 建立与幂等 ==")
path = enginelog.setup(max_bytes=64 * 1024, backups=2)
if path is None:
    print("  setup() 失败原因: %s" % enginelog.last_error())
check("setup() 返回日志路径", path is not None, path)
check("日志文件已创建", path is not None and Path(path).is_file(), path)
check("路径在 APPDATA 下", str(path).startswith(str(_TMP)), path)
again = enginelog.setup(max_bytes=64 * 1024, backups=2)
check("重复 setup() 返回同一路径", str(again) == str(path), again)
n_handlers = len(logging.getLogger("autogametool").handlers)
check("handler 没有被重复添加", n_handlers == 1, n_handlers)

print("== 2. 令牌绝不落盘（安全硬要求）==")
SECRET = "gho_TESTTOKEN_should_never_appear_0123456789"
enginelog.info("编辑器地址: http://127.0.0.1:8765/?token=%s", SECRET)
print(f"[AutoGameTool] 编辑器地址: http://127.0.0.1:8765/?token={SECRET}", flush=True)
logging.getLogger("uvicorn.access").info(
    '127.0.0.1:1234 - "GET /run/state?token=%s HTTP/1.1" 200 OK', SECRET
)
enginelog.info("Authorization: Bearer %s", SECRET)  # 这种没有 token= 前缀的本来也不该记录
txt = read_log()
check("日志里没有明文令牌", SECRET not in txt, "令牌泄漏到日志文件！")
check("token= 被掩成 token=***", "token=***" in txt, txt[-400:])

print("== 3. print() 被接管 ==")
print("print-capture-marker-xyz", flush=True)
check("print 的内容进了日志", "print-capture-marker-xyz" in read_log())

print("== 4. 运行日志落盘（即使当时没有页面连接）==")
# 模拟「没有任何 WS 连接」的情况：钩子是 broadcast 里最先执行的一步，与连接数无关
enginelog.note_broadcast({"type": "log", "level": "info", "message": "第 1/1000 轮", "step": "找图 任务"})
enginelog.note_broadcast({"type": "log", "level": "error", "message": "节点执行失败(找图): 目标窗口已最小化"})
enginelog.note_broadcast({"type": "state", "state": "running", "paused": False})
txt = read_log()
check("运行日志写入（含步骤名）", "第 1/1000 轮" in txt and "找图 任务" in txt)
check("错误级别日志写入", "目标窗口已最小化" in txt)
check("状态事件写入", '"state": "running"' in txt)

print("== 5. recorded 不写日志（避免挤掉有用信息）==")
big = {"type": "recorded", "events": [{"t": i, "type": "keydown", "key": "x"} for i in range(5000)]}
enginelog.note_broadcast(big)
check("recorded 的载荷未写入", '"keydown"' not in read_log())

print("== 6. 体积轮转 ==")
if path is None:
    check("体积轮转（因 setup 失败跳过）", False, "setup 未成功")
    rotated = None
else:
    # 写爆上限，确认切出 .1 备份
    chunk = "x" * 4000
    for i in range(40):
        enginelog.info("填充 %d %s", i, chunk)
    rotated = Path(str(path) + ".1")
    check("产生了 .1 轮转文件", rotated.is_file(),
          [p.name for p in Path(path).parent.glob("engine.log*")])
    check("当前日志文件仍可用", Path(path).is_file() and Path(path).stat().st_size > 0)
    check("轮转后令牌依然被掩", SECRET not in read_log())

print("== 7. 退出原因可记录 ==")
enginelog.log_exit("WebUI 页面全部断开且 6 秒内没有重连")
check("退出原因写入日志", "引擎退出" in read_log())

print("")
print("结果: PASS=%d  FAIL=%d" % (_pass, _fail))
# 临时目录清理：先关掉 handler，避免 Windows 上文件被占用删不掉
try:
    for h in list(logging.getLogger("autogametool").handlers):
        h.close()
except Exception:
    pass
shutil.rmtree(_TMP, ignore_errors=True)
sys.stdout.flush()
os._exit(0 if _fail == 0 else 1)
