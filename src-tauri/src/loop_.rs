//! Loop de detecciÃ³n automÃ¡tica a 4 FPS.
//!
//! Cada 250 ms:
//!   1. Lee el rect LOCAL de cada marker desde `AppState`.
//!   2. Suma la posiciÃ³n/escala de la ventana correspondiente para obtener
//!      el rect ABSOLUTO en pixels fÃ­sicos de pantalla.
//!   3. Captura esa regiÃ³n y la manda al sidecar Python.
//!   4. Emite eventos `detection:wind` / `detection:angle` al frontend.
//!
//! Se inicia automÃ¡ticamente al arrancar â€” no hay botÃ³n Start/Stop.

use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::capture::capture_region_png;
use crate::sidecar::Sidecar;
use crate::state::{AppState, Rect};

pub async fn start<R: Runtime>(app: AppHandle<R>) {
    log::info!("loop de detecciÃ³n arrancando (4 FPS)");
    let sidecar = Sidecar::new();
    let mut frame_id: u64 = 0;
    let mut ticker = tokio::time::interval(Duration::from_millis(250));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        ticker.tick().await;
        frame_id = frame_id.wrapping_add(1);

        let (wind_local, angle_local) = {
            let state = app.state::<Mutex<AppState>>();
            let s = state.lock().unwrap();
            (s.wind_rect, s.angle_rect)
        };

        if let Some(local) = wind_local {
            if let Some(abs) = local_to_absolute(&app, "marker_wind", local) {
                if let Err(e) = process_one(&app, &sidecar, "wind", abs, frame_id).await {
                    log::debug!("wind detect fallÃ³ (frame {frame_id}): {e}");
                }
            }
        }
        if let Some(local) = angle_local {
            if let Some(abs) = local_to_absolute(&app, "marker_angle", local) {
                if let Err(e) = process_one(&app, &sidecar, "angle", abs, frame_id).await {
                    log::debug!("angle detect fallÃ³ (frame {frame_id}): {e}");
                }
            }
        }
    }
}

fn local_to_absolute<R: Runtime>(
    app: &AppHandle<R>,
    window_label: &str,
    local: Rect,
) -> Option<Rect> {
    let win = app.get_webview_window(window_label)?;
    let pos = win.outer_position().ok()?;
    let scale = win.scale_factor().ok().unwrap_or(1.0);
    Some(Rect {
        x: pos.x + (local.x as f64 * scale).round() as i32,
        y: pos.y + (local.y as f64 * scale).round() as i32,
        w: (local.w as f64 * scale).round() as u32,
        h: (local.h as f64 * scale).round() as u32,
    })
}

async fn process_one<R: Runtime>(
    app: &AppHandle<R>,
    sidecar: &Sidecar,
    detector: &str,
    rect: Rect,
    frame_id: u64,
) -> anyhow::Result<()> {
    let png = tokio::task::spawn_blocking(move || capture_region_png(rect)).await??;
    let resp = sidecar.detect(detector, frame_id, &png).await?;
    match detector {
        "wind" => {
            if let Some(w) = resp.wind {
                let _ = app.emit("detection:wind", &w);
                let state = app.state::<Mutex<AppState>>();
                state.lock().unwrap().last_wind = Some(w);
            }
        }
        "angle" => {
            if let Some(a) = resp.angle {
                let _ = app.emit("detection:angle", &a);
                let state = app.state::<Mutex<AppState>>();
                state.lock().unwrap().last_angle = Some(a);
            }
        }
        _ => {}
    }
    Ok(())
}

