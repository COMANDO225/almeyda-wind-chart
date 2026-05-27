//! ai-dragonbound — Rust core de la app Tauri.

mod capture;
mod dataset;
mod loop_;
mod sidecar;
mod state;

use state::AppState;
use std::sync::Mutex;
use tauri::{Manager, WindowEvent};
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};

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
        // Hotkeys globales (Sprint C.1) — funcionan incluso con el juego en foco.
        //   F1 → captura del WIND (numero del radar, guarda en wind_number/)
        //   F2 → captura del ANGLE (rect entero, guarda en angle/)
        // El usuario puede spamear F2 varias veces por turno porque el angulo
        // cambia mucho durante el apuntado.
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_shortcuts([
                    Shortcut::new(Some(Modifiers::empty()), Code::F1),
                    Shortcut::new(Some(Modifiers::empty()), Code::F2),
                ])
                .expect("Shortcuts F1/F2 invalidos")
                .with_handler(|app, shortcut, event| {
                    if event.state != ShortcutState::Pressed {
                        return;
                    }
                    if shortcut.matches(Modifiers::empty(), Code::F1) {
                        if let Err(e) = dataset::capture_wind_sample(app) {
                            log::warn!("F1 captura fallo: {e}");
                        }
                    } else if shortcut.matches(Modifiers::empty(), Code::F2) {
                        if let Err(e) = dataset::capture_angle_sample(app) {
                            log::warn!("F2 captura fallo: {e}");
                        }
                    }
                })
                .build(),
        )
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
