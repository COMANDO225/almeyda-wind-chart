//! Captura de una región rectangular de pantalla a PNG bytes.
//!
//! Usa la crate `xcap` que en Windows envuelve Windows.Graphics.Capture y en
//! otros SOs cae a APIs nativas. Es muy rápida (~5–15 ms por captura típica) y
//! no abre ventanas extra.

use anyhow::{Context, Result};
use image::{ImageEncoder, Rgba, RgbaImage};

use crate::state::Rect;

/// Modo de captura: rectángulo entero o con máscara circular.
#[derive(Debug, Clone, Copy)]
pub enum CaptureShape {
    Rect,
    /// Máscara circular inscrita en el rect cuadrado: píxeles fuera del
    /// círculo se pintan de negro. Usado para el medidor de viento, donde
    /// la zona fuera del círculo no aporta info y solo confunde al detector.
    Circle,
}

pub fn capture_region_png(rect: Rect, shape: CaptureShape) -> Result<Vec<u8>> {
    let monitors = xcap::Monitor::all().context("xcap::Monitor::all")?;
    let monitor = monitors
        .iter()
        .find(|m| {
            let mx = m.x();
            let my = m.y();
            let mw = m.width() as i32;
            let mh = m.height() as i32;
            rect.x >= mx
                && rect.y >= my
                && rect.x + rect.w as i32 <= mx + mw
                && rect.y + rect.h as i32 <= my + mh
        })
        .cloned()
        .or_else(|| monitors.first().cloned())
        .context("ningún monitor encontrado")?;

    let full = monitor.capture_image().context("monitor.capture_image")?;
    let mx = monitor.x();
    let my = monitor.y();
    let rel_x = (rect.x - mx).max(0) as u32;
    let rel_y = (rect.y - my).max(0) as u32;
    let w = rect.w.min(full.width().saturating_sub(rel_x));
    let h = rect.h.min(full.height().saturating_sub(rel_y));

    let mut cropped = image::imageops::crop_imm(&full, rel_x, rel_y, w, h).to_image();
    if matches!(shape, CaptureShape::Circle) {
        apply_circle_mask(&mut cropped);
    }

    let mut buf = Vec::with_capacity((w * h * 4) as usize);
    image::codecs::png::PngEncoder::new(&mut buf)
        .write_image(
            cropped.as_raw(),
            cropped.width(),
            cropped.height(),
            image::ExtendedColorType::Rgba8,
        )
        .context("PNG encode")?;
    Ok(buf)
}

/// Pinta de negro los píxeles fuera del círculo inscrito.
///
/// El círculo está centrado en el rect y su radio es min(w, h) / 2. Esto
/// elimina el ruido de la zona vacía cuando el marker es circular (radar
/// del viento) — el OCR / detector de puntero solo ve el contenido relevante.
fn apply_circle_mask(img: &mut RgbaImage) {
    let w = img.width() as f32;
    let h = img.height() as f32;
    let cx = w / 2.0;
    let cy = h / 2.0;
    let r = (w.min(h) / 2.0) - 0.5; // -0.5 para evitar borde con aliasing
    let r2 = r * r;
    let black = Rgba([0u8, 0, 0, 255]);
    for y in 0..img.height() {
        let dy = y as f32 + 0.5 - cy;
        let dy2 = dy * dy;
        for x in 0..img.width() {
            let dx = x as f32 + 0.5 - cx;
            if dx * dx + dy2 > r2 {
                img.put_pixel(x, y, black);
            }
        }
    }
}
