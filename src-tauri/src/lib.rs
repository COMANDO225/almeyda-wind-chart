//! ai-dragonbound — Rust core de la app Tauri.

mod capture;
mod loop_;
mod sidecar;
mod state;

use state::AppState;
use std::sync::Mutex;
use tauri::{Manager, WindowEvent};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .targets([
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
                        file_name: None,
                    }),
                ])
                .build(),
        )
        .plugin(tauri_plugin_store::Builder::new().build())
        .manage(Mutex::new(AppState::default()))
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = state::restore_from_store(&handle).await {
                    log::warn!("no se pudieron restaurar rects: {e}");
                }
                loop_::start(handle).await;
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                if window.label() == "control_panel" {
                    log::info!("control_panel cerrado → exit app");
                    window.app_handle().exit(0);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            state::get_marker_rect,
            state::set_marker_rect,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
