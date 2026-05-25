//! Captura de una región rectangular de pantalla a PNG bytes.
//!
//! Usa la crate `xcap` que en Windows envuelve Windows.Graphics.Capture y en
//! otros SOs cae a APIs nativas. Es muy rápida (~5–15 ms por captura típica) y
//! no abre ventanas extra.

use anyhow::{Context, Result};
use image::ImageEncoder;

use crate::state::Rect;

pub fn capture_region_png(rect: Rect) -> Result<Vec<u8>> {
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

    let cropped = image::imageops::crop_imm(&full, rel_x, rel_y, w, h).to_image();

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
