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
    // WebView2/Chromium estrangula el repintado y los timers de las ventanas
    // SIN foco. Como el foco esta en el juego, el panel se actualizaba con
    // retardo (se "despertaba" al hacer click). Estos flags desactivan ese
    // throttling para que el panel repinte en tiempo real siempre.
    #[cfg(windows)]
    std::env::set_var(
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
        "--disable-background-timer-throttling \
         --disable-renderer-backgrounding \
         --disable-backgrounding-occluded-windows",
    );

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
            // Excluir los markers de las capturas de pantalla: siguen visibles
            // para el usuario pero NO aparecen en los PNGs que toma xcap.
            exclude_markers_from_capture(app.handle());

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

/// Marca las ventanas marker con `WDA_EXCLUDEFROMCAPTURE`: siguen visibles en
/// pantalla pero el compositor DWM las excluye de toda captura (xcap usa
/// BitBlt, que respeta esta affinity). Asi las muestras del dataset y los
/// frames del loop OCR salen limpios, sin el borde celeste del marker.
#[cfg(windows)]
fn exclude_markers_from_capture<R: tauri::Runtime>(app: &tauri::AppHandle<R>) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        SetWindowDisplayAffinity, WDA_EXCLUDEFROMCAPTURE,
    };
    for label in ["marker_wind", "marker_angle"] {
        let Some(win) = app.get_webview_window(label) else {
            log::warn!("exclude_from_capture: ventana '{label}' no encontrada");
            continue;
        };
        match win.hwnd() {
            Ok(hwnd) => {
                let ok = unsafe { SetWindowDisplayAffinity(hwnd.0 as _, WDA_EXCLUDEFROMCAPTURE) };
                if ok == 0 {
                    log::warn!("SetWindowDisplayAffinity fallo en '{label}' (este PC podria no soportarlo)");
                } else {
                    log::info!("'{label}' excluido de capturas (WDA_EXCLUDEFROMCAPTURE)");
                }
            }
            Err(e) => log::warn!("no se pudo obtener HWND de '{label}': {e}"),
        }
    }
}

#[cfg(not(windows))]
fn exclude_markers_from_capture<R: tauri::Runtime>(_app: &tauri::AppHandle<R>) {
    // WDA_EXCLUDEFROMCAPTURE es especifico de Windows. En otros SO no aplica.
}
