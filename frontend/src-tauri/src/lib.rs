// AutoTool 桌面壳（Tauri 2）
//
// 职责边界（刻意的设计）：
//   · 界面与业务逻辑仍然完全在 Python 引擎里（FastAPI + 内嵌前端），**一行都没搬**；
//     壳只做三件事：拉起引擎、等它就绪、开一个原生窗口指向引擎的入口 URL。
//   · 这样「浏览器模式」与「桌面模式」共用同一份引擎与同一套数据目录
//     （%APPDATA%\AutoTool），老脚本 .agflow 与找图模板零改动可用。
//
// 为什么窗口 URL 指向 http://127.0.0.1:8765 而不是打包进壳的前端产物：
//   · 前端由引擎同源提供，fetch/WebSocket 天然同源，不需要处理 CORS，
//     也不需要把访问令牌从壳里注入页面 —— 令牌直接放在入口 URL 上（没有地址栏，用户看不到）。
//   · 代价是壳必须等引擎起来才能开窗（见 start_engine/wait_health）。

use std::io::Write;
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// 引擎监听地址（与 engine/main.py 保持一致）
const ENGINE_ADDR: &str = "127.0.0.1:8765";
const ENGINE_PORT: u16 = 8765;
/// 首次启动时等待引擎就绪的上限（冷启动 + 杀软扫描可能偏慢）
const HEALTH_TIMEOUT: Duration = Duration::from_secs(90);

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[derive(Default)]
struct EngineHandle {
    /// 只有「由本壳拉起」的引擎才需要由壳负责结束
    child: Mutex<Option<Child>>,
}

/// 壳自己的诊断日志（%APPDATA%\AutoTool\shell.log）。
///
/// 为什么不用 eprintln：release 是 windows 子系统（没有控制台），
/// 而调试期从 `pnpm tauri dev` 起时 stderr 又常被上层缓冲住看不到；
/// 写文件是两种形态下都可靠的取证方式。
fn shell_log(msg: &str) {
    // 默认写 %APPDATA%\AutoTool\shell.log；
    // 设了 AUTOTOOL_SHELL_LOG 就写到指定文件（自动化验证时常把日志引到工作区，
    // 因为受限会话里子进程写不了 %APPDATA%）。
    let path = match std::env::var("AUTOTOOL_SHELL_LOG") {
        Ok(p) if !p.trim().is_empty() => PathBuf::from(p),
        _ => token_file().with_file_name("shell.log"),
    };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let _ = writeln!(f, "[unix={secs}] {msg}");
    }
}

fn token_file() -> PathBuf {
    let appdata = std::env::var("APPDATA").unwrap_or_default();
    PathBuf::from(appdata).join("AutoTool").join("engine.token")
}

/// 0.1.2 及更早（工具还叫 AutoGameTool）存放令牌的位置。
///
/// 升级上来必须能读到它：否则壳会另生成一个令牌，而**真正在跑的引擎**用的是旧令牌，
/// 页面就永远连不上（正是 v0.8.1 修过的那类「反复提示令牌校验失败」）。
fn legacy_token_file() -> PathBuf {
    let appdata = std::env::var("APPDATA").unwrap_or_default();
    PathBuf::from(appdata).join("AutoGameTool").join("engine.token")
}

/// 读一个令牌文件；内容不够长就当作没有。
fn read_token(path: &PathBuf) -> Option<String> {
    let text = std::fs::read_to_string(path).ok()?;
    let t = text.trim().to_string();
    if t.len() >= 16 {
        Some(t)
    } else {
        None
    }
}

/// 读引擎落盘的访问令牌；没有就生成一个并写回，保证「第二次启动」也能连上同一个引擎。
///
/// 引擎自己在首次启动时也会写这个文件（engine/main.py 的 _load_or_create_token），
/// 这里做的是兜底：万一文件被删了，本次仍要能开出一个可用的窗口。
fn load_or_create_token() -> String {
    let path = token_file();
    if let Some(t) = read_token(&path) {
        return t;
    }
    // 升级路径：旧目录里有令牌就沿用，并写一份到新位置。
    // （引擎侧是"按项补齐"式迁移，只补目标缺失的文件，所以这里先写过去不影响其它数据）
    if let Some(t) = read_token(&legacy_token_file()) {
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let _ = std::fs::write(&path, &t);
        return t;
    }
    let token = random_token();
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let _ = std::fs::write(&path, &token);
    token
}

/// 不引第三方 crate 的简易随机串（本机回环端口用的 CSRF 令牌，够用即可）
fn random_token() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let pid = std::process::id() as u128;
    let mut acc = nanos ^ (pid << 64);
    let mut out = String::with_capacity(48);
    for i in 0..6u32 {
        acc = acc
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407 + i as u128);
        out.push_str(&format!("{:016x}", (acc >> 32) as u64));
    }
    out
}

/// 引擎是否已经在跑（只做一个 TCP 连接，不引 HTTP 客户端依赖）
fn engine_alive() -> bool {
    TcpStream::connect_timeout(
        &format!("127.0.0.1:{ENGINE_PORT}").parse().unwrap(),
        Duration::from_millis(400),
    )
    .is_ok()
}

/// 等引擎可用。
///
/// 判据刻意"宽"：**只要端口能连上**就算就绪 —— 因为
///   1) uvicorn 是先绑定端口再跑 lifespan，端口通了说明进程活着且监听正常；
///   2) 之前用「自己拼 HTTP 请求再解析 200」的写法太脆（读超时/分片都会误判成未就绪），
///      实测导致壳一直等到超时、窗口始终不出现（进程活着但什么都没发生）。
/// 界面侧本来就有重连与轮询，端口通了之后那点启动尾巴完全能自愈。
fn wait_ready(deadline: Duration) -> bool {
    let start = Instant::now();
    let mut hits = 0;
    while start.elapsed() < deadline {
        if engine_alive() {
            hits += 1;
            // 连续两次探测都通，再多给 400ms 让 lifespan 收尾
            if hits >= 2 {
                std::thread::sleep(Duration::from_millis(400));
                return true;
            }
        } else {
            hits = 0;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

/// 开发模式：直接用 venv 里的解释器跑源码；发布模式：用随包分发的 onedir 引擎
fn engine_command(app: &AppHandle) -> Result<(Command, PathBuf), String> {
    let mut cmd;
    let cwd;
    if cfg!(debug_assertions) {
        // CARGO_MANIFEST_DIR = <项目>/frontend/src-tauri
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .ok_or("定位项目根目录失败")?
            .to_path_buf();
        let py = root.join("engine").join(".venv").join("Scripts").join("python.exe");
        if !py.is_file() {
            return Err(format!("找不到引擎解释器：{}", py.display()));
        }
        cwd = root.join("engine");
        cmd = Command::new(py);
        cmd.arg("main.py");
        // 开发模式：免令牌 + 放行 vite 1420 的 CORS（与 run_engine.ps1 一致），
        // 这样窗口可以直接开在 vite dev 上，改前端即时热更新。
        cmd.env("AUTOTOOL_DEV", "1");
    } else {
        let res = app
            .path()
            .resource_dir()
            .map_err(|e| format!("拿不到资源目录：{e}"))?;
        let exe = res.join("engine").join("AutoTool.exe");
        if !exe.is_file() {
            return Err(format!("找不到随包引擎：{}", exe.display()));
        }
        cwd = exe.parent().unwrap().to_path_buf();
        cmd = Command::new(exe);
    }
    cmd.current_dir(cwd.clone())
        .env("AUTOTOOL_DESKTOP", "1")
        .env("AUTOTOOL_NO_BROWSER", "1")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    Ok((cmd, cwd))
}

fn start_engine(app: &AppHandle) -> Result<String, String> {
    // 1) 已经有引擎在跑（比如用户先开了浏览器版）→ 直接用它的令牌
    if engine_alive() {
        shell_log("检测到已有引擎在运行，复用它");
        let token = load_or_create_token();
        let _ = wait_ready(Duration::from_secs(5));
        return Ok(token);
    }

    // 2) 拉起引擎。令牌先定下来并通过环境变量传进去，保证「壳拿到的 == 引擎认的」
    let token = load_or_create_token();
    let (mut cmd, cwd) = engine_command(app)?;
    shell_log(&format!("启动引擎：{cmd:?}（工作目录 {cwd:?}）"));
    cmd.env("AUTOTOOL_TOKEN", &token);
    let child = cmd.spawn().map_err(|e| format!("启动引擎失败：{e}"))?;
    if let Some(state) = app.try_state::<EngineHandle>() {
        if let Ok(mut slot) = state.child.lock() {
            *slot = Some(child);
        }
    }

    if !wait_ready(HEALTH_TIMEOUT) {
        return Err(format!(
            "引擎在 {} 秒内没有就绪，请查看日志：%APPDATA%\\AutoTool\\engine.log",
            HEALTH_TIMEOUT.as_secs()
        ));
    }
    shell_log("引擎 /health 已就绪");
    Ok(token)
}

/// 窗口该指向哪里：
///   · 开发：vite dev（改前端即时热更新；引擎已开 DEV 模式免令牌 + 放行 1420 CORS）
///   · 发布：引擎入口 URL（前端由引擎同源提供，天然没有 CORS 与令牌注入问题）
fn entry_url(token: &str) -> String {
    if cfg!(debug_assertions) {
        "http://localhost:1420/".to_string()
    } else {
        format!("http://{ENGINE_ADDR}/?token={token}")
    }
}

fn open_main_window(app: &AppHandle, token: &str) -> Result<(), String> {
    let url = entry_url(token);
    shell_log(&format!("创建主窗口：{url}"));
    let parsed = url.parse().map_err(|e| format!("入口地址非法：{e}"))?;
    WebviewWindowBuilder::new(app, "main", WebviewUrl::External(parsed))
        .title("AutoTool")
        .inner_size(1360.0, 860.0)
        .min_inner_size(1000.0, 660.0)
        .center()
        .build()
        .map_err(|e| format!("创建窗口失败：{e}"))?;
    shell_log("主窗口已创建");
    Ok(())
}

/// 窗口建不出来时的兜底：用系统默认浏览器打开同一个界面。
///
/// 为什么要有这条：WebView2 建窗依赖 Chromium 宿主窗口，在**锁屏/非活动桌面**等场合
/// 会以 `os error 5（拒绝访问）` 失败（实测）。这时如果直接退出，用户看到的就是
/// "双击了没反应"；改为退回浏览器 + 在 shell.log 里写清原因，至少界面还能用，
/// 而且问题可诊断。引擎与悬浮框都还在跑。
fn fallback_to_browser(token: &str, err: &str) {
    let url = entry_url(token);
    shell_log(&format!("窗口创建失败，退回系统浏览器：{url}（原因：{err}）"));
    if let Err(e) = tauri_plugin_opener::open_url(url, None::<&str>) {
        shell_log(&format!("退回浏览器也失败：{e}"));
    }
}

/// 顶栏「关于」等外链：交给系统默认浏览器
#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    tauri_plugin_opener::open_url(url, None::<&str>).map_err(|e| e.to_string())
}

fn kill_engine(app: &AppHandle) {
    if let Some(state) = app.try_state::<EngineHandle>() {
        if let Ok(mut slot) = state.child.lock() {
            if let Some(mut child) = slot.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.show();
                let _ = win.unminimize();
                let _ = win.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .manage(EngineHandle::default())
        .invoke_handler(tauri::generate_handler![open_external])
        .setup(|app| {
            // 关键：启动引擎与创建窗口都放在 **主线程** 的 setup 里。
            // 试过「后台线程里 start_engine + 跨线程建窗」，结果是进程活着但窗口始终不出现
            // （静默失败，连错误都拿不到）。这里宁可让窗口晚 5~10 秒出现（引擎冷启动），
            // 也不要那种"看起来启动了、其实什么也没有"的状态。
            let handle = app.handle().clone();
            shell_log("setup：开始启动引擎");
            match start_engine(&handle) {
                Ok(token) => {
                    if let Err(e) = open_main_window(&handle, &token) {
                        // 建窗失败不再直接退出（那会表现成"双击没反应"）：
                        // 退回浏览器 + 写清原因，引擎与悬浮框继续可用。
                        shell_log(&e);
                        fallback_to_browser(&token, &e);
                    }
                }
                Err(e) => {
                    shell_log(&format!("引擎启动失败：{e}"));
                    return Err(e.into());
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                kill_engine(app);
            }
        });
}
