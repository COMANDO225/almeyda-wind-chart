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

use std::collections::HashMap;
use std::collections::VecDeque;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::capture::{capture_region_png, CaptureShape};
use crate::sidecar::Sidecar;
use crate::state::{AppState, Rect, WindReading};

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
/// Cadencia del loop del viento. Ahora que el numero del viento es CNN (~1 ms,
/// ya no RapidOCR), y con el frame-skip (no recalcula si el radar no cambio),
/// muestrear seguido es barato → el cambio de viento se detecta casi al
/// instante. Corre en su propia tarea/sidecar, sin trabar el angulo.
const WIND_INTERVAL_MS: u64 = 150;
/// Ventana de suavizado temporal del viento. El viento es casi ESTÁTICO (solo
/// cambia entre turnos), asi que podemos promediar fuerte: elimina el temblor
/// del puntero por animaciones de fondo (remolinos) y descarta lecturas
/// outlier aisladas (p.ej. una flecha invertida 180° ocasional). ~8 lecturas
/// a ~7 FPS = ~1.1 s para estabilizar tras cambiar de turno (aceptable: hay
/// segundos para apuntar). Dirección = promedio CIRCULAR; número = MODA.
const WIND_HISTORY_CAP: usize = 8;

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

/// Consenso temporal de la ventana de lecturas del viento.
///   * dirección: PROMEDIO CIRCULAR (atan2 de la media de sin/cos). Robusto a
///     outliers minoritarios — una flecha invertida 180° ocasional no mueve la
///     resultante si la mayoría apunta bien. Inmune al wrap 0/360.
///   * número: MODA (valor más frecuente en la ventana), desempate por la mejor
///     confianza — igual criterio que usábamos para el ángulo.
///   * confianza: promedio de la ventana.
fn smooth_wind(history: &VecDeque<WindReading>) -> WindReading {
    // --- dirección: promedio circular ---
    let (mut sx, mut sy, mut ndir) = (0.0f64, 0.0f64, 0u32);
    for r in history {
        if let Some(d) = r.direction_deg {
            let rad = d.to_radians();
            sx += rad.cos();
            sy += rad.sin();
            ndir += 1;
        }
    }
    let direction_deg = if ndir > 0 && (sx * sx + sy * sy) > 1e-9 {
        Some((sy.atan2(sx).to_degrees() + 360.0) % 360.0)
    } else {
        None
    };

    // --- número: moda (con mejor confianza como desempate) ---
    let mut counts: HashMap<i32, (u32, f64)> = HashMap::new();
    for r in history {
        if let Some(v) = r.value {
            let e = counts.entry(v).or_insert((0, 0.0));
            e.0 += 1;
            if r.confidence > e.1 {
                e.1 = r.confidence;
            }
        }
    }
    let value = counts
        .iter()
        .max_by(|a, b| {
            a.1 .0.cmp(&b.1 .0).then(
                a.1 .1
                    .partial_cmp(&b.1 .1)
                    .unwrap_or(std::cmp::Ordering::Equal),
            )
        })
        .map(|(v, _)| *v);

    // --- confianza: promedio de la ventana ---
    let confidence = if history.is_empty() {
        0.0
    } else {
        history.iter().map(|r| r.confidence).sum::<f64>() / history.len() as f64
    };

    WindReading {
        value,
        direction_deg,
        confidence,
    }
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
                // Suavizado temporal: empuja la lectura cruda a la ventana y
                // emite el CONSENSO (dirección = promedio circular, número =
                // moda). Estabiliza el puntero frente a animaciones de fondo y
                // descarta outliers aislados (flecha invertida ocasional).
                let state = app.state::<Mutex<AppState>>();
                let (smoothed, prev) = {
                    let mut s = state.lock().unwrap();
                    s.wind_history.push_back(w);
                    while s.wind_history.len() > WIND_HISTORY_CAP {
                        s.wind_history.pop_front();
                    }
                    let sm = smooth_wind(&s.wind_history);
                    let prev = s.last_wind.and_then(|p| p.value);
                    s.last_wind = Some(sm);
                    (sm, prev)
                };
                let _ = app.emit("detection:wind", &smoothed);
                crate::physics::recompute_and_emit(app);
                if smoothed.value != prev {
                    log::info!(
                        "wind → value {:?} (conf {:.2}), dir {:?}",
                        smoothed.value,
                        smoothed.confidence,
                        smoothed.direction_deg
                    );
                }
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
                crate::physics::recompute_and_emit(app);
                log::info!("angle → {} (conf {:.2})", v, a.confidence);
            }
        }
        _ => {}
    }
    Ok(())
}
