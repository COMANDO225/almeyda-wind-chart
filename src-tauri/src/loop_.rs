//! Loops de deteccion automatica.
//!
//! ANGULO y VIENTO corren en TAREAS y procesos Python SEPARADOS, asi la
//! lentitud de RapidOCR (viento) nunca traba al CNN (angulo). El angulo a
//! ~25 FPS, el viento a ~1 FPS. En cada tick:
//!   1. Lee el rect LOCAL del marker desde `AppState`.
//!   2. Suma posicion/escala de la ventana → rect ABSOLUTO en pixels fisicos.
//!   3. Captura SOLO esa region (BitBlt) y la hashea: si es identica al frame
//!      anterior (frame-skip), no recalcula nada — los frames quietos son casi
//!      gratis y el cambio real se detecta al instante.
//!   4. Si cambio, la manda al sidecar y emite `detection:wind` / `detection:angle`
//!      al frontend (el angulo con anti-rebote por confianza).

use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::capture::{capture_region_png, CaptureShape};
use crate::sidecar::Sidecar;
use crate::state::{AppState, Rect};

/// Confianza minima (producto de las 3 cabezas de la CNN) para aceptar una
/// lectura de angulo. Los frames dudosos se descartan (no mueven el panel).
const ANGLE_CONF_GATE: f64 = 0.6;
/// Confirmaciones consecutivas antes de mostrar un valor NUEVO.
///   1 = al instante (sigue el cambio en vivo; el gate de confianza ya filtra
///       frames basura/transicion de baja confianza).
///   2+ = mas estable pero agrega 1 frame de latencia por confirmacion; subir
///        solo si se ve parpadeo molesto en las transiciones.
const ANGLE_CONFIRM_FRAMES: u8 = 1;
/// Cadencia del loop del angulo. Con el frame-skip (no recalcula si la region
/// no cambio) muestrear agresivo es barato: 40ms = 25 FPS. Un cambio se detecta
/// en <=40ms; los frames quietos cuestan solo capturar + hashear.
const ANGLE_INTERVAL_MS: u64 = 40;
/// Cadencia del loop del viento. Corre en su PROPIO sidecar/tarea, asi que su
/// lentitud (RapidOCR ~2 s) no afecta al angulo. El viento cambia poco.
const WIND_INTERVAL_MS: u64 = 1000;

pub async fn start<R: Runtime>(app: AppHandle<R>) {
    log::info!("loop de deteccion arrancando (angulo 4 FPS, viento aparte)");

    // El viento corre en su PROPIA tarea con su PROPIO sidecar (proceso Python
    // separado). Asi RapidOCR (lento) nunca bloquea el loop del angulo.
    {
        let app_wind = app.clone();
        tauri::async_runtime::spawn(async move { wind_loop(app_wind).await });
    }

    // Loop del angulo: CNN rapido, sin nada que lo trabe.
    let sidecar = Sidecar::new();
    let mut frame_id: u64 = 0;
    let mut last_hash: Option<u64> = None;
    let mut ticker = tokio::time::interval(Duration::from_millis(ANGLE_INTERVAL_MS));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        ticker.tick().await;
        frame_id = frame_id.wrapping_add(1);

        let angle_local = {
            let state = app.state::<Mutex<AppState>>();
            let s = state.lock().unwrap();
            s.angle_rect
        };
        if let Some(local) = angle_local {
            if let Some(abs) = local_to_absolute(&app, "marker_angle", local) {
                if let Err(e) = process_one(
                    &app,
                    &sidecar,
                    "angle",
                    abs,
                    CaptureShape::Rect,
                    frame_id,
                    &mut last_hash,
                )
                .await
                {
                    log::debug!("angle detect fallo (frame {frame_id}): {e}");
                }
            }
        }
    }
}

/// Loop del viento, independiente del angulo. marker_wind es circular y el
/// sidecar corre DOS FLUJOS (puntero geometrico + numero por OCR) sobre el
/// mismo frame. RapidOCR es lento, pero al estar en su propia tarea/proceso no
/// afecta la fluidez del angulo.
async fn wind_loop<R: Runtime>(app: AppHandle<R>) {
    let sidecar = Sidecar::new();
    let mut frame_id: u64 = 0;
    let mut last_hash: Option<u64> = None;
    let mut ticker = tokio::time::interval(Duration::from_millis(WIND_INTERVAL_MS));
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    loop {
        ticker.tick().await;
        frame_id = frame_id.wrapping_add(1);

        let wind_local = {
            let state = app.state::<Mutex<AppState>>();
            let s = state.lock().unwrap();
            s.wind_rect
        };
        if let Some(local) = wind_local {
            if let Some(abs) = local_to_absolute(&app, "marker_wind", local) {
                if let Err(e) = process_one(
                    &app,
                    &sidecar,
                    "wind",
                    abs,
                    CaptureShape::Circle,
                    frame_id,
                    &mut last_hash,
                )
                .await
                {
                    log::debug!("wind detect fallo (frame {frame_id}): {e}");
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

/// Hash rapido (no criptografico) de los bytes del frame, para el frame-skip.
fn hash_bytes(bytes: &[u8]) -> u64 {
    use std::hash::{Hash, Hasher};
    let mut h = std::collections::hash_map::DefaultHasher::new();
    bytes.hash(&mut h);
    h.finish()
}

async fn process_one<R: Runtime>(
    app: &AppHandle<R>,
    sidecar: &Sidecar,
    detector: &str,
    rect: Rect,
    shape: CaptureShape,
    frame_id: u64,
    last_hash: &mut Option<u64>,
) -> anyhow::Result<()> {
    let png = tokio::task::spawn_blocking(move || capture_region_png(rect, shape)).await??;
    // Frame-skip: si la region es identica al frame anterior no hay nada nuevo
    // que detectar — saltamos el sidecar (CNN/OCR) entero. Los frames quietos
    // quedan casi gratis y el cambio real se detecta al instante.
    let hash = hash_bytes(&png);
    if *last_hash == Some(hash) {
        return Ok(());
    }
    *last_hash = Some(hash);
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
            // Anti-rebote para refrescar casi en tiempo real sin parpadeos:
            //   * descartamos frames con confianza baja (no mueven el panel);
            //   * un valor NUEVO debe leerse ANGLE_CONFIRM_FRAMES veces seguidas
            //     antes de mostrarse (filtra un frame aislado raro);
            //   * una vez mostrado, se mantiene hasta que otro valor se confirme.
            let Some(a) = resp.angle else { return Ok(()) };
            let Some(v) = a.value else { return Ok(()) };
            if a.confidence < ANGLE_CONF_GATE {
                return Ok(());
            }
            let state = app.state::<Mutex<AppState>>();
            let emit = {
                let mut s = state.lock().unwrap();
                if s.last_angle.and_then(|r| r.value) == Some(v) {
                    // ya estamos mostrando este valor: nada que confirmar.
                    s.angle_pending = None;
                    s.angle_pending_count = 0;
                    false
                } else {
                    // valor distinto al mostrado: contar confirmaciones seguidas.
                    let count = if s.angle_pending == Some(v) {
                        s.angle_pending_count.saturating_add(1)
                    } else {
                        1
                    };
                    if count >= ANGLE_CONFIRM_FRAMES {
                        s.last_angle = Some(a);
                        s.angle_pending = None;
                        s.angle_pending_count = 0;
                        true
                    } else {
                        s.angle_pending = Some(v);
                        s.angle_pending_count = count;
                        false
                    }
                }
            };
            if emit {
                let _ = app.emit("detection:angle", &a);
                log::info!("angle → {} (conf {:.2})", v, a.confidence);
            }
        }
        _ => {}
    }
    Ok(())
}
