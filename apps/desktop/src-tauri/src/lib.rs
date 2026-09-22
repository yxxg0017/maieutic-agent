//! Tauri 壳：负责 sidecar 生命周期、连接信息与最小权限外链。
//! 不承担模型编排；所有业务逻辑在 Python sidecar 中。

use std::io::{BufRead, BufReader};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use base64::Engine;
use rand::RngCore;
use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[derive(Clone, Serialize)]
pub struct Connection {
    pub port: u16,
    pub token: String,
}

#[derive(Default)]
struct SidecarState {
    token: String,
    connection: Arc<Mutex<Option<Connection>>>,
    child: Arc<Mutex<Option<CommandChild>>>,
    dev_child: Arc<Mutex<Option<std::process::Child>>>,
}

fn new_token() -> String {
    let mut bytes = [0u8; 32]; // 256-bit，每次启动重新生成
    rand::thread_rng().fill_bytes(&mut bytes);
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
}

fn data_dir(app: &AppHandle) -> std::path::PathBuf {
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("maieutic-agent"))
}

/// 从 sidecar 的 ready 行解析实际端口。ready 行不含 token。
fn parse_ready(line: &str) -> Option<u16> {
    let value: serde_json::Value = serde_json::from_str(line).ok()?;
    if value.get("event")?.as_str()? != "ready" {
        return None;
    }
    value.get("port")?.as_u64().map(|port| port as u16)
}

fn spawn_packaged_sidecar(app: &AppHandle, state: &SidecarState) -> Result<(), String> {
    let dir = data_dir(app);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let command = app
        .shell()
        .sidecar("binaries/kel-sidecar")
        .map_err(|e| e.to_string())?
        .args([
            "--data-dir",
            dir.to_string_lossy().as_ref(),
            "--log-level",
            "info",
            "--parent-pid",
            &std::process::id().to_string(),
        ])
        .env("KEL_SESSION_TOKEN", state.token.clone())
        .env("KEL_DATA_DIR", dir.to_string_lossy().to_string());

    let (mut rx, child) = command.spawn().map_err(|e| e.to_string())?;
    *state.child.lock().unwrap() = Some(child);

    let connection = state.connection.clone();
    let token = state.token.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let text = String::from_utf8_lossy(&line).to_string();
                    if let Some(port) = parse_ready(text.trim()) {
                        *connection.lock().unwrap() = Some(Connection {
                            port,
                            token: token.clone(),
                        });
                    }
                }
                CommandEvent::Terminated(_) => {
                    *connection.lock().unwrap() = None; // 异常退出：显示可恢复错误，不静默重启
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

/// 开发模式：允许调用本地 Python 虚拟环境（KEL_DEV_PYTHON 指向解释器）。
fn spawn_dev_sidecar(app: &AppHandle, state: &SidecarState, python: String) -> Result<(), String> {
    let dir = data_dir(app);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let mut child = std::process::Command::new(python)
        .args([
            "-m",
            "kel.main",
            "--data-dir",
            dir.to_string_lossy().as_ref(),
            "--parent-pid",
            &std::process::id().to_string(),
        ])
        .env("KEL_SESSION_TOKEN", state.token.clone())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;

    let stdout = child.stdout.take().ok_or("sidecar stdout unavailable")?;
    *state.dev_child.lock().unwrap() = Some(child);
    let connection = state.connection.clone();
    let token = state.token.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(port) = parse_ready(line.trim()) {
                *connection.lock().unwrap() = Some(Connection {
                    port,
                    token: token.clone(),
                });
            }
        }
    });
    Ok(())
}

#[tauri::command]
async fn sidecar_connection(state: State<'_, SidecarState>) -> Result<Connection, String> {
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        if let Some(connection) = state.connection.lock().unwrap().clone() {
            return Ok(connection);
        }
        if Instant::now() > deadline {
            return Err("sidecar_not_ready".into());
        }
        tokio_sleep(Duration::from_millis(100)).await;
    }
}

async fn tokio_sleep(duration: Duration) {
    tauri::async_runtime::spawn_blocking(move || std::thread::sleep(duration))
        .await
        .ok();
}

/// 仅允许 https；本地文件另走受控命令。
#[tauri::command]
async fn open_external(app: AppHandle, url: String) -> Result<(), String> {
    if !url.starts_with("https://") {
        return Err("scheme_not_allowed".into());
    }
    tauri_plugin_opener::OpenerExt::opener(&app)
        .open_url(url, None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn reveal_log_dir(app: AppHandle) -> Result<String, String> {
    let dir = data_dir(&app);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    tauri_plugin_opener::OpenerExt::opener(&app)
        .open_path(dir.to_string_lossy().to_string(), None::<&str>)
        .map_err(|e| e.to_string())?;
    Ok(dir.to_string_lossy().to_string())
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

fn shutdown(state: &SidecarState) {
    if let Some(child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
    }
    if let Some(mut child) = state.dev_child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(SidecarState {
            token: new_token(),
            ..Default::default()
        })
        .invoke_handler(tauri::generate_handler![
            sidecar_connection,
            open_external,
            reveal_log_dir,
            quit_app
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            let state = app.state::<SidecarState>();
            let result = match std::env::var("KEL_DEV_PYTHON") {
                Ok(python) if !python.is_empty() => spawn_dev_sidecar(&handle, &state, python),
                _ => spawn_packaged_sidecar(&handle, &state),
            };
            if let Err(error) = result {
                eprintln!("sidecar 启动失败：{error}"); // 前端会显示可恢复错误
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                shutdown(&app.state::<SidecarState>());
            }
        });
}
