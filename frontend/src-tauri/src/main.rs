#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{fs::OpenOptions, path::PathBuf, process::{Child, Command, Stdio}, sync::Mutex};
use tauri::{Emitter, Manager, menu::{Menu, MenuItem}, tray::{TrayIconBuilder, TrayIconEvent, MouseButton, MouseButtonState}};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
mod job;
struct PrivacyState { enabled: AtomicBool, updating: AtomicBool, original_style: Mutex<Option<isize>> }
struct NativeUpdateGuard<'a> { flag: &'a AtomicBool, previous: bool }
impl<'a> NativeUpdateGuard<'a> {
    fn new(flag: &'a AtomicBool) -> Self { Self { flag, previous: flag.swap(true, Ordering::Relaxed) } }
}
impl Drop for NativeUpdateGuard<'_> {
    fn drop(&mut self) { self.flag.store(self.previous, Ordering::Relaxed); }
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show(); let _ = window.unminimize(); let _ = window.set_focus();
        // Tao rebuilds extended styles when showing/restoring a window.
        // Reapply after those operations, while already on the main thread.
        if window.state::<PrivacyState>().enabled.load(Ordering::Relaxed) {
            if let Err(error) = set_switcher_privacy(&window, true) {
                record_warning(app, format!("Не удалось восстановить режим окна: {error}"));
            }
        }
    }
}

fn setup_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "Открыть AQA Copilot", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "hide", "Свернуть в трей", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Выход", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &hide, &quit])?;
    let mut builder = TrayIconBuilder::with_id("main-tray").tooltip("AQA Copilot")
        .menu(&menu).show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => show_main(app),
            "hide" => { if let Some(window) = app.get_webview_window("main") { let _ = window.hide(); } },
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event { show_main(tray.app_handle()); }
        });
    if let Some(icon) = app.default_window_icon() { builder = builder.icon(icon.clone()); }
    builder.build(app)?;
    Ok(())
}

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn SetWindowDisplayAffinity(hwnd: *mut std::ffi::c_void, affinity: u32) -> i32;
    fn GetWindowDisplayAffinity(hwnd: *mut std::ffi::c_void, affinity: *mut u32) -> i32;
    fn GetWindowLongPtrW(hwnd: *mut std::ffi::c_void, index: i32) -> isize;
    fn SetWindowLongPtrW(hwnd: *mut std::ffi::c_void, index: i32, value: isize) -> isize;
    fn IsWindowVisible(hwnd: *mut std::ffi::c_void) -> i32;
    fn IsIconic(hwnd: *mut std::ffi::c_void) -> i32;
    fn GetForegroundWindow() -> *mut std::ffi::c_void;
    fn SetForegroundWindow(hwnd: *mut std::ffi::c_void) -> i32;
    fn ShowWindow(hwnd: *mut std::ffi::c_void, command: i32) -> i32;
    fn SetWindowPos(hwnd: *mut std::ffi::c_void, after: *mut std::ffi::c_void,
                    x: i32, y: i32, width: i32, height: i32, flags: u32) -> i32;
}

#[cfg(windows)]
const SWITCHER_MASK: isize = 0x80 | 0x40000; // WS_EX_TOOLWINDOW | WS_EX_APPWINDOW

#[cfg(windows)]
fn write_window_style(window: &tauri::WebviewWindow, desired: isize) -> Result<(), String> {
    let state = window.state::<PrivacyState>();
    let _updating = NativeUpdateGuard::new(&state.updating);
    let hwnd = window.hwnd().map_err(|e| e.to_string())?;
    let hwnd = hwnd.0 as *mut std::ffi::c_void;
    unsafe {
        let current = GetWindowLongPtrW(hwnd, -20);
        if current == desired { return Ok(()); }
        let visible = IsWindowVisible(hwnd) != 0;
        let minimized = IsIconic(hwnd) != 0;
        let focused = GetForegroundWindow() == hwnd;
        // Shell taskbar buttons require hide -> style -> show. Use native
        // ShowWindow here: Tao's show() would overwrite TOOLWINDOW again.
        if visible { ShowWindow(hwnd, 0); }
        let result = (|| -> Result<(), String> {
            windows_sys::Win32::Foundation::SetLastError(0);
            if SetWindowLongPtrW(hwnd, -20, desired) == 0 &&
                windows_sys::Win32::Foundation::GetLastError() != 0 {
                return Err(std::io::Error::last_os_error().to_string());
            }
            // SWP_NOSIZE | NOMOVE | NOZORDER | NOACTIVATE | FRAMECHANGED.
            if SetWindowPos(hwnd, std::ptr::null_mut(), 0, 0, 0, 0, 0x37) == 0 {
                return Err(std::io::Error::last_os_error().to_string());
            }
            if GetWindowLongPtrW(hwnd, -20) & SWITCHER_MASK != desired & SWITCHER_MASK {
                return Err("Windows не подтвердила стиль окна".into());
            }
            Ok(())
        })();
        if result.is_err() {
            SetWindowLongPtrW(hwnd, -20, current);
            SetWindowPos(hwnd, std::ptr::null_mut(), 0, 0, 0, 0, 0x37);
        }
        if visible { ShowWindow(hwnd, if minimized { 7 } else { 8 }); }
        if focused && !minimized { SetForegroundWindow(hwnd); }
        result
    }
}

#[cfg(windows)]
fn set_switcher_privacy(window: &tauri::WebviewWindow, enabled: bool) -> Result<(), String> {
    let hwnd = window.hwnd().map_err(|e| e.to_string())?;
    let state = window.state::<PrivacyState>();
    let saved = *state.original_style.lock().map_err(|e| e.to_string())?;
    let current = unsafe { GetWindowLongPtrW(hwnd.0 as _, -20) };
    let desired = if enabled { (current | 0x80) & !0x40000 }
        else { (current & !SWITCHER_MASK) | (saved.unwrap_or(current) & SWITCHER_MASK) };
    write_window_style(window, desired)?;
    // ShowWindow can synchronously emit focus/resize events; never hold this
    // mutex while calling native window APIs.
    let mut saved = state.original_style.lock().map_err(|e| e.to_string())?;
    if enabled { if saved.is_none() { *saved = Some(current & SWITCHER_MASK); } }
    else { *saved = None; }
    Ok(())
}

#[cfg(not(windows))]
fn set_switcher_privacy(_window: &tauri::WebviewWindow, _enabled: bool) -> Result<(), String> {
    Err("Режим доступен только в Windows".into())
}

#[tauri::command]
fn capture_privacy(window: tauri::WebviewWindow) -> Result<bool, String> {
    #[cfg(windows)] {
        let hwnd = window.hwnd().map_err(|e| e.to_string())?;
        let mut affinity = 0u32;
        // The handle belongs to this application's live top-level window.
        if unsafe { GetWindowDisplayAffinity(hwnd.0 as _, &mut affinity) } == 0 {
            return Err(format!("Не удалось проверить защиту от захвата: {}", std::io::Error::last_os_error()));
        }
        Ok(affinity == 0x11)
    }
    #[cfg(not(windows))] { let _ = window; Err("Режим доступен только в Windows".into()) }
}

fn set_capture_privacy_on_main(window: tauri::WebviewWindow, enabled: bool) -> Result<bool, String> {
    #[cfg(windows)] {
        if enabled && window.app_handle().tray_by_id("main-tray").is_none() {
            return Err("Значок трея недоступен. Перезапустите приложение перед включением сокрытия.".into());
        }
        let hwnd = window.hwnd().map_err(|e| e.to_string())?;
        let state = window.state::<PrivacyState>();
        let _updating = NativeUpdateGuard::new(&state.updating);
        let previous_enabled = state.enabled.load(Ordering::Relaxed);
        let previous_saved = *state.original_style.lock().map_err(|e| e.to_string())?;
        let previous_style = unsafe { GetWindowLongPtrW(hwnd.0 as _, -20) };
        let mut previous_affinity = 0;
        if unsafe { GetWindowDisplayAffinity(hwnd.0 as _, &mut previous_affinity) } == 0 {
            return Err(format!("Не удалось прочитать защиту от захвата: {}", std::io::Error::last_os_error()));
        }
        let result = (|| -> Result<bool, String> {
            if unsafe { SetWindowDisplayAffinity(hwnd.0 as _, if enabled { 0x11 } else { 0 }) } == 0 {
                return Err(format!("Не удалось изменить защиту от захвата: {}", std::io::Error::last_os_error()));
            }
            if capture_privacy(window.clone())? != enabled {
                return Err("Windows не подтвердила изменение защиты от захвата".into());
            }
            // Save the original mask BEFORE Tao/taskbar updates change it.
            if enabled { set_switcher_privacy(&window, true)?; }
            window.set_skip_taskbar(enabled).map_err(|e| e.to_string())?;
            set_switcher_privacy(&window, enabled)?;
            state.enabled.store(enabled, Ordering::Relaxed);
            Ok(enabled)
        })();
        if let Err(error) = result {
            let _ = window.set_skip_taskbar(previous_enabled);
            let style_restored = write_window_style(&window, previous_style).is_ok();
            let affinity_restored = unsafe { SetWindowDisplayAffinity(hwnd.0 as _, previous_affinity) } != 0;
            *state.original_style.lock().map_err(|e| e.to_string())? = previous_saved;
            return Err(if style_restored && affinity_restored { error }
                else { format!("{error}. Не удалось полностью восстановить прежний режим; перезапустите приложение.") });
        }
        result
    }
    #[cfg(not(windows))] { let _ = (window, enabled); Err("Режим доступен только в Windows".into()) }
}

#[tauri::command]
async fn set_capture_privacy(window: tauri::WebviewWindow, enabled: bool) -> Result<bool, String> {
    // Serialize the whole native transaction on the UI thread; setters invoked
    // from command workers otherwise only enqueue their operations.
    let (sender, receiver) = std::sync::mpsc::channel();
    let target = window.clone();
    window.run_on_main_thread(move || { let _ = sender.send(set_capture_privacy_on_main(target, enabled)); })
        .map_err(|e| e.to_string())?;
    tauri::async_runtime::spawn_blocking(move || receiver.recv().map_err(|e| e.to_string())?)
        .await.map_err(|e| e.to_string())?
}

#[derive(Clone, serde::Serialize)]
struct ConnectionInfo { url: String, token: String }
struct ServiceState { child: Mutex<Option<Child>>, job: Mutex<Option<job::BackendJob>>, connection: ConnectionInfo, warnings: Mutex<Vec<String>> }

#[tauri::command]
fn connection_info(state: tauri::State<'_, ServiceState>) -> Result<ConnectionInfo, String> {
    let mut locked = state.child.lock().map_err(|_| "Service state unavailable".to_string())?;
    if let Some(child) = locked.as_mut() {
        match child.try_wait() {
            Ok(Some(status)) => return Err(format!("Локальный сервис завершился ({status}). Подробности: backend.log в папке данных.")),
            Err(e) => return Err(format!("Не удалось проверить локальный сервис: {e}")),
            Ok(None) => {}
        }
    } else { return Err("Локальный сервис не запущен. Проверьте папку resources/backend.".into()); }
    Ok(state.connection.clone())
}

#[tauri::command]
fn native_warnings(state: tauri::State<'_, ServiceState>) -> Vec<String> {
    state.warnings.lock().map(|w| w.clone()).unwrap_or_default()
}

fn record_warning(app: &tauri::AppHandle, warning: String) {
    if let Ok(mut warnings) = app.state::<ServiceState>().warnings.lock() { warnings.push(warning.clone()); }
    let _ = app.emit("shortcut-error", warning);
}

fn spawn_backend(app: &tauri::AppHandle, token: &str) -> Result<(Child, job::BackendJob), String> {
    let data = match std::env::var_os("AQACOPILOT_DATA").filter(|p| !p.is_empty()) {
        Some(path) => PathBuf::from(path),
        None => {
            let executable = std::env::current_exe().map_err(|e| e.to_string())?;
            let directory = executable.parent().ok_or("Не найдена папка приложения")?;
            let config = directory.join("installation.json");
            if config.is_file() {
                let text = std::fs::read_to_string(config).map_err(|e| e.to_string())?;
                let value: serde_json::Value = serde_json::from_str(text.trim_start_matches('\u{feff}')).map_err(|e| format!("Некорректный installation.json: {e}"))?;
                let path = PathBuf::from(value["data_dir"].as_str().ok_or("В installation.json не указан data_dir")?);
                if !path.is_absolute() { return Err("data_dir должен быть абсолютным путём".into()); }
                path
            } else { directory.join("data") }
        }
    };
    std::fs::create_dir_all(&data).map_err(|e| format!("Не удалось создать папку данных {}: {e}", data.display()))?;
    // Bootstrap the portable backend's old defaults without changing existing settings.
    match OpenOptions::new().write(true).create_new(true).open(data.join("settings.json")) {
        Ok(mut file) => {
            use std::io::Write;
            let settings = serde_json::json!({"asr_model_path": data.join("models/whisper-medium")});
            file.write_all(settings.to_string().as_bytes()).map_err(|e| format!("Не удалось записать настройки: {e}"))?;
        }
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {},
        Err(e) => return Err(format!("Не удалось создать настройки: {e}")),
    }
    let resource = app.path().resource_dir().map_err(|e| e.to_string())?;
    let mut executable = resource.join("resources/backend/aqa-backend.exe");
    if cfg!(debug_assertions) && !executable.is_file() { executable = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/backend/aqa-backend.exe"); }
    if !executable.is_file() { return Err(format!("Не найден локальный сервис: {}", executable.display())); }
    let log = OpenOptions::new().create(true).append(true).open(data.join("backend.log")).map_err(|e| e.to_string())?;
    let error_log = log.try_clone().map_err(|e| e.to_string())?;
    let mut command = Command::new(&executable);
    command.arg("--port").arg("17321").arg("--token").arg(token).arg("--data-dir").arg(&data).arg("--warmup")
        .current_dir(executable.parent().ok_or("Invalid backend path")?)
        .stdin(Stdio::null()).stdout(Stdio::from(log)).stderr(Stdio::from(error_log));
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW, console belongs to no user interface.
    }
    let job = job::BackendJob::new()?;
    let mut child = command.spawn().map_err(|e| format!("Не удалось запустить локальный сервис: {e}"))?;
    if let Err(error) = job.attach(&child) { let _ = child.kill(); let _ = child.wait(); return Err(error); }
    Ok((child, job))
}

fn stop_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<ServiceState>() {
        if let Ok(mut job) = state.job.lock() { drop(job.take()); }
        if let Ok(mut child) = state.child.lock() {
            if let Some(mut process) = child.take() { let _ = process.kill(); let _ = process.wait(); }
        }
    }
}

fn main() {
    // Explicit smoke-test mode exercises only this window; no backend or models start.
    let test_report = std::env::args().skip_while(|arg| arg != "--desktop-self-test").nth(1).map(PathBuf::from);
    let testing = test_report.is_some();
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![connection_info, native_warnings, capture_privacy, set_capture_privacy])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Resized(_) | tauri::WindowEvent::Focused(true)) &&
                window.state::<PrivacyState>().enabled.load(Ordering::Relaxed) &&
                !window.state::<PrivacyState>().updating.load(Ordering::Relaxed) {
                if let Some(main) = window.app_handle().get_webview_window("main") {
                    if let Err(error) = set_switcher_privacy(&main, true) {
                        record_warning(window.app_handle(), format!("Не удалось сохранить режим окна: {error}"));
                    }
                }
            }
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.state::<PrivacyState>().enabled.load(Ordering::Relaxed) {
                    api.prevent_close();
                    if let Err(error) = window.hide() { record_warning(window.app_handle(), format!("Не удалось свернуть окно: {error}")); }
                }
            }
        })
        .setup(move |app| {
            app.manage(PrivacyState { enabled: AtomicBool::new(false), updating: AtomicBool::new(false), original_style: Mutex::new(None) });
            let token = format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple());
            let connection = ConnectionInfo { url:"http://127.0.0.1:17321".into(), token:token.clone() };
            app.manage(ServiceState { child:Mutex::new(None), job:Mutex::new(None), connection, warnings:Mutex::new(Vec::new()) });
            if let Err(error) = setup_tray(app.handle()) { record_warning(app.handle(), format!("Не удалось создать значок трея: {error}")); }
            // The configured window starts hidden. Apply the same checked native
            // transaction used by the toggle before its first presentation.
            // If it fails, retain the normal window and report the real error.
            if let Some(window) = app.get_webview_window("main") {
                if let Err(error) = set_capture_privacy_on_main(window, true) {
                    record_warning(app.handle(), format!("Не удалось включить скрытие при запуске: {error}"));
                }
            }
            if !testing { match spawn_backend(app.handle(), &token) {
                Ok((child, job)) => { *app.state::<ServiceState>().child.lock().unwrap() = Some(child); *app.state::<ServiceState>().job.lock().unwrap() = Some(job); }
                Err(message) => record_warning(app.handle(), message)
            } }
            let modifiers = Some(Modifiers::CONTROL | Modifiers::ALT);
            let toggle = Shortcut::new(modifiers, Code::Space);
            let capture = Shortcut::new(modifiers, Code::KeyS);
            let cancel = Shortcut::new(modifiers, Code::KeyX);
            let plugin = tauri_plugin_global_shortcut::Builder::new().with_handler(move |app, shortcut, event| {
                if event.state() != ShortcutState::Pressed { return; }
                if shortcut == &toggle {
                    if let Some(window) = app.get_webview_window("main") {
                        if window.is_visible().unwrap_or(true) && !window.is_minimized().unwrap_or(false) { let _ = window.hide(); }
                        else { show_main(app); }
                    }
                } else if shortcut == &capture { let _ = app.emit("capture-selected", ()); }
                else if shortcut == &cancel { let _ = app.emit("cancel", ()); }
            }).build();
            if let Err(e) = app.handle().plugin(plugin) { record_warning(app.handle(), format!("Не удалось включить горячие клавиши: {e}")); }
            else {
                for (key, name) in [(toggle,"Ctrl+Alt+Space"),(capture,"Ctrl+Alt+S"),(cancel,"Ctrl+Alt+X")] {
                    if let Err(e) = app.global_shortcut().register(key) { record_warning(app.handle(), format!("Горячая клавиша {name} занята или недоступна: {e}")); }
                }
            }
            show_main(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Не удалось запустить окно AQA Copilot");
    app.run(move |handle, event| {
        if let tauri::RunEvent::Ready = event {
            if let Some(path) = &test_report {
                let result = (|| -> Result<(), String> {
                    let window = handle.get_webview_window("main").ok_or("Window missing")?;
                    if handle.tray_by_id("main-tray").is_none() { return Err("Tray missing".into()); }
                    if !window.state::<PrivacyState>().enabled.load(Ordering::Relaxed) || !capture_privacy(window.clone())? {
                        return Err("Startup privacy was not enabled".into());
                    }
                    if !window.is_visible().map_err(|e| e.to_string())? { return Err("Startup window was not shown".into()); }
                    #[cfg(windows)]
                    let original_mask = window.state::<PrivacyState>().original_style.lock()
                        .map_err(|e| e.to_string())?.ok_or("Original startup window style missing")?;
                    set_capture_privacy_on_main(window.clone(), true)?;
                    set_capture_privacy_on_main(window.clone(), true)?;
                    #[cfg(windows)] {
                        let hwnd = window.hwnd().map_err(|e| e.to_string())?;
                        if unsafe { GetWindowLongPtrW(hwnd.0 as _, -20) } & 0x80 == 0 { return Err("Alt-Tab privacy failed".into()); }
                    }
                    if !capture_privacy(window.clone())? { return Err("Capture privacy failed".into()); }
                    window.hide().map_err(|e| e.to_string())?;
                    if window.is_visible().map_err(|e| e.to_string())? { return Err("Hide failed".into()); }
                    show_main(handle);
                    if !window.is_visible().map_err(|e| e.to_string())? { return Err("Restore failed".into()); }
                    #[cfg(windows)] {
                        let hwnd = window.hwnd().map_err(|e| e.to_string())?;
                        if unsafe { GetWindowLongPtrW(hwnd.0 as _, -20) } & SWITCHER_MASK != 0x80 { return Err("Privacy lost after hide/show".into()); }
                    }
                    window.minimize().map_err(|e| e.to_string())?;
                    show_main(handle);
                    #[cfg(windows)] {
                        let hwnd = window.hwnd().map_err(|e| e.to_string())?;
                        if unsafe { GetWindowLongPtrW(hwnd.0 as _, -20) } & SWITCHER_MASK != 0x80 { return Err("Privacy lost after minimize/restore".into()); }
                    }
                    set_capture_privacy_on_main(window.clone(), false)?;
                    set_capture_privacy_on_main(window.clone(), false)?;
                    if capture_privacy(window.clone())? { return Err("Privacy reset failed".into()); }
                    #[cfg(windows)] {
                        let hwnd = window.hwnd().map_err(|e| e.to_string())?;
                        if unsafe { GetWindowLongPtrW(hwnd.0 as _, -20) } & SWITCHER_MASK != original_mask { return Err("Original window style not restored".into()); }
                    }
                    Ok(())
                })();
                let output = match &result { Ok(()) => "PASS: startup privacy enabled before first show; tray; repeated privacy toggles; hide/show; minimize/restore; original style restored; no backend started".to_string(), Err(error) => format!("FAIL: {error}") };
                let saved = std::fs::write(path, output).is_ok();
                handle.exit(if result.is_ok() && saved { 0 } else { 1 });
            }
        }
        if let tauri::RunEvent::Exit = event { stop_backend(handle); }
    });
}
