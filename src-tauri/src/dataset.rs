//! Captura de samples para el dataset de entrenamiento de la CNN (Sprint C.1).
//!
//! Hotkeys globales (registrados con `tauri-plugin-global-shortcut`, funcionan
//! incluso con el juego en foco):
//!
//! * `F1` → captura solo del WIND (cuadrado central del marker_wind ampliado
//!   al 80% del lado para tolerar descentrados — guarda en `wind_number/`).
//!
//! * `F2` → captura solo del ANGLE (rect entero del marker_angle — guarda
//!   en `angle/`). El usuario puede spamear F2 varias veces por turno porque
//!   el angulo cambia mucho mientras apunta.
//!
//! Carpeta destino: `<project_root>/assets/dataset/raw/<detector>/{ts}.png`.

use anyhow::{Context, Result};
use chrono::Local;
use image::imageops::FilterType;
use std::io::Cursor;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Manager, Runtime};

use crate::capture::{capture_region_png, CaptureShape};
use crate::sidecar::project_root;
use crate::state::{AppState, Rect};

/// Aplica un upscale (NxN) a un PNG ya codificado. Util para "zoom in" del
/// sample antes de guardarlo: el numero del juego es relativamente chiquito
/// dentro del crop, multiplicar resolucion lo hace mas enfocado y deja mas
/// detalle disponible para la CNN.
fn zoom_png(png_bytes: &[u8], factor: u32) -> Result<Vec<u8>> {
    if factor <= 1 {
        return Ok(png_bytes.to_vec());
    }
    let img = image::load_from_memory(png_bytes).context("load PNG")?;
    let resized = img.resize_exact(
        img.width().saturating_mul(factor),
        img.height().saturating_mul(factor),
        FilterType::CatmullRom,
    );
    let mut out = Vec::with_capacity(png_bytes.len() * (factor as usize).pow(2));
    resized
        .write_to(&mut Cursor::new(&mut out), image::ImageFormat::Png)
        .context("re-encode PNG")?;
    Ok(out)
}

/// Agranda un rect por N pixels en cada lado. Util cuando el marker es
/// chico y queremos capturar un poco mas de contexto alrededor.
fn outset_rect(rect: Rect, outset: u32) -> Rect {
    let o = outset as i32;
    Rect {
        x: rect.x - o,
        y: rect.y - o,
        w: rect.w + outset * 2,
        h: rect.h + outset * 2,
    }
}

fn dataset_dir(detector: &str) -> PathBuf {
    project_root()
        .join("assets")
        .join("dataset")
        .join("raw")
        .join(detector)
}

fn save_sample(detector: &str, png: &[u8]) -> Result<PathBuf> {
    let dir = dataset_dir(detector);
    std::fs::create_dir_all(&dir).context("crear dir dataset")?;
    // Timestamp con milisegundos para evitar colisiones si F1 se presiona rapido.
    let ts = Local::now().format("%Y%m%d_%H%M%S_%3f").to_string();
    let path = dir.join(format!("{}.png", ts));
    std::fs::write(&path, png).context("escribir PNG")?;
    Ok(path)
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

/// Recorta el cuadrado central del rect al 80% del lado.
///
/// El detector `wind_number.detect()` usa 55% para enfocar el OCR, pero
/// para el DATASET de entrenamiento queremos mas margen — el numero del
/// juego puede estar levemente descentrado dentro del circulo (mas a la
/// izquierda) y el 55% lo recorta. El 80% incluye todo el numero aunque
/// no este perfectamente centrado, y deja que el labeling tool segmente
/// los digitos individuales.
fn center_80_pct(rect: Rect) -> Rect {
    let side = ((rect.w.min(rect.h) as f64) * 0.80).round() as u32;
    let cx = rect.x + rect.w as i32 / 2;
    let cy = rect.y + rect.h as i32 / 2;
    Rect {
        x: cx - side as i32 / 2,
        y: cy - side as i32 / 2,
        w: side,
        h: side,
    }
}

/// F1 → captura del marker_wind (centro 80% + zoom 2x, guarda en `wind_number/`).
///
/// El zoom 2x amplifica la resolucion del numero del viento, que tiende a
/// ser chico relativo al circulo del marker. El sample queda mas enfocado
/// y la CNN puede aprovechar mas pixeles del digito.
pub fn capture_wind_sample<R: Runtime>(app: &AppHandle<R>) -> Result<Option<PathBuf>> {
    let state = app.state::<Mutex<AppState>>();
    let wind_local = state.lock().unwrap().wind_rect;
    let Some(local) = wind_local else {
        log::warn!("F1: marker_wind sin rect — coloca primero el marker");
        return Ok(None);
    };
    let Some(abs) = local_to_absolute(app, "marker_wind", local) else {
        return Ok(None);
    };
    let center = center_80_pct(abs);
    // El marker esta excluido de captura (WDA_EXCLUDEFROMCAPTURE), asi que la
    // captura sale limpia sin necesidad de ocultar la ventana.
    let png = capture_region_png(center, CaptureShape::Rect)?;
    let zoomed = zoom_png(&png, 2)?;
    let path = save_sample("wind_number", &zoomed)?;
    log::info!(
        "F1 sample wind_number (center80+zoom2x): {}",
        path.display()
    );
    Ok(Some(path))
}

/// F2 → captura del marker_angle (rect entero, guarda en `angle/`).
pub fn capture_angle_sample<R: Runtime>(app: &AppHandle<R>) -> Result<Option<PathBuf>> {
    let state = app.state::<Mutex<AppState>>();
    let angle_local = state.lock().unwrap().angle_rect;
    let Some(local) = angle_local else {
        log::warn!("F2: marker_angle sin rect — coloca primero el marker");
        return Ok(None);
    };
    let Some(abs) = local_to_absolute(app, "marker_angle", local) else {
        return Ok(None);
    };
    // Outset 2px a cada lado para abarcar TODAS las letras del angulo
    // aunque el usuario haya dejado el rect un poco corto.
    let expanded = outset_rect(abs, 2);
    let png = capture_region_png(expanded, CaptureShape::Rect)?;
    let path = save_sample("angle", &png)?;
    log::info!("F2 sample angle (outset2): {}", path.display());
    Ok(Some(path))
}
