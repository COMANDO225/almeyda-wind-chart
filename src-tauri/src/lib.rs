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
        // Hotkeys globales (funcionan incluso con el juego en foco).
        //   F1 → captura del NUMERO del viento (centro+zoom2x, wind_number/)
        //   F2 → captura del ANGLE del HUD (rect entero, angle/)
        //   F3 → captura del PUNTERO del viento (circulo completo, wind_pointer/)
        // F2/F3 se pueden spamear varias veces por turno porque tanto el
        // angulo como el puntero cambian mucho mientras se apunta.
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_shortcuts([
                    Shortcut::new(Some(Modifiers::empty()), Code::F1),
                    Shortcut::new(Some(Modifiers::empty()), Code::F2),
                    Shortcut::new(Some(Modifiers::empty()), Code::F3),
                ])
                .expect("Shortcuts F1/F2/F3 invalidos")
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
                    } else if shortcut.matches(Modifiers::empty(), Code::F3) {
                        if let Err(e) = dataset::capture_wind_pointer_sample(app) {
                            log::warn!("F3 captura fallo: {e}");
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
                // Aplicar el flag de exclusion DESPUES del restore, asi se
                // respeta el valor que el usuario eligio la sesion anterior
                // (default true si nunca se guardo).
                let enabled = {
                    let s = handle.state::<Mutex<AppState>>();
                    let s = s.lock().unwrap();
                    s.exclude_from_capture
                };
                apply_marker_capture_affinity(&handle, enabled);
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
            state::get_exclude_from_capture,
            state::set_exclude_from_capture,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Aplica el modo de captura a las ventanas marker:
///   * `enabled = true`  → `WDA_EXCLUDEFROMCAPTURE`: los markers son visibles
///     en pantalla pero EXCLUIDOS de toda captura (xcap/BitBlt respeta la
///     affinity). Util para datasets/loops OCR limpios y para no aparecer en
///     screenshots/streams del juego.
///   * `enabled = false` → `WDA_NONE`: comportamiento estandar, los markers
///     SI aparecen en capturas (util si el usuario quiere mostrarlos en un
///     tutorial o screen recording).
///
/// Llamable en cualquier momento — Win32 actualiza la affinity en vivo.
#[cfg(windows)]
pub fn apply_marker_capture_affinity<R: tauri::Runtime>(app: &tauri::AppHandle<R>, enabled: bool) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        SetWindowDisplayAffinity, WDA_EXCLUDEFROMCAPTURE, WDA_NONE,
    };
    let affinity = if enabled {
        WDA_EXCLUDEFROMCAPTURE
    } else {
        WDA_NONE
    };
    for label in ["marker_wind", "marker_angle"] {
        let Some(win) = app.get_webview_window(label) else {
            log::warn!("apply_capture_affinity: ventana '{label}' no encontrada");
            continue;
        };
        match win.hwnd() {
            Ok(hwnd) => {
                let ok = unsafe { SetWindowDisplayAffinity(hwnd.0 as _, affinity) };
                if ok == 0 {
                    log::warn!(
                        "SetWindowDisplayAffinity fallo en '{label}' (este PC podria no soportarlo)"
                    );
                } else {
                    let modo = if enabled { "excluido" } else { "visible" };
                    log::info!("'{label}' affinity → {modo}");
                }
            }
            Err(e) => log::warn!("no se pudo obtener HWND de '{label}': {e}"),
        }
    }
}

#[cfg(not(windows))]
pub fn apply_marker_capture_affinity<R: tauri::Runtime>(
    _app: &tauri::AppHandle<R>,
    _enabled: bool,
) {
    // WDA_EXCLUDEFROMCAPTURE es especifico de Windows. En otros SO no aplica.
}
