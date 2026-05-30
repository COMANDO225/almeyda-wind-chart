//! Captura de una region rectangular de pantalla a PNG bytes.
//!
//! En Windows captura SOLO la region pedida con un BitBlt directo de GDI
//! (~sub-ms), en vez de capturar el monitor entero y recortar (lo que costaba
//! ~15-40 ms por frame). El BitBlt del DC de pantalla respeta
//! `WDA_EXCLUDEFROMCAPTURE`, asi que los markers excluidos siguen sin aparecer.
//! Fuera de Windows cae a `xcap` (captura el monitor y recorta).

use anyhow::{Context, Result};
use image::{ImageEncoder, Rgba, RgbaImage};

use crate::state::Rect;

/// Modo de captura: rectangulo entero o con mascara circular.
#[derive(Debug, Clone, Copy)]
pub enum CaptureShape {
    Rect,
    /// Mascara circular inscrita en el rect cuadrado: pixeles fuera del
    /// circulo se pintan de negro. Usado para el medidor de viento, donde la
    /// zona fuera del circulo no aporta info y solo confunde al detector.
    Circle,
}

pub fn capture_region_png(rect: Rect, shape: CaptureShape) -> Result<Vec<u8>> {
    let mut cropped = capture_region(rect)?;
    if matches!(shape, CaptureShape::Circle) {
        apply_circle_mask(&mut cropped);
    }
    let (w, h) = (cropped.width(), cropped.height());
    let mut buf = Vec::with_capacity((w * h * 4) as usize);
    image::codecs::png::PngEncoder::new(&mut buf)
        .write_image(cropped.as_raw(), w, h, image::ExtendedColorType::Rgba8)
        .context("PNG encode")?;
    Ok(buf)
}

/// Captura SOLO la region (coords absolutas en pixels fisicos) con un BitBlt
/// directo de GDI. Mucho mas barato que capturar el monitor entero.
#[cfg(windows)]
fn capture_region(rect: Rect) -> Result<RgbaImage> {
    use std::ffi::c_void;
    use windows_sys::Win32::Graphics::Gdi::{
        BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject, GetDC,
        GetDIBits, ReleaseDC, SelectObject, BITMAPINFO, BITMAPINFOHEADER, DIB_RGB_COLORS, SRCCOPY,
    };

    let w = rect.w.max(1);
    let h = rect.h.max(1);
    let (wi, hi) = (w as i32, h as i32);

    // SAFETY: secuencia estandar de captura GDI. Todos los recursos creados
    // (DC de memoria + bitmap) se liberan antes de salir, incluso en error.
    unsafe {
        let screen_dc = GetDC(std::ptr::null_mut());
        if screen_dc.is_null() {
            anyhow::bail!("GetDC(NULL) fallo");
        }
        let mem_dc = CreateCompatibleDC(screen_dc);
        let bitmap = CreateCompatibleBitmap(screen_dc, wi, hi);
        if mem_dc.is_null() || bitmap.is_null() {
            if !bitmap.is_null() {
                DeleteObject(bitmap);
            }
            if !mem_dc.is_null() {
                DeleteDC(mem_dc);
            }
            ReleaseDC(std::ptr::null_mut(), screen_dc);
            anyhow::bail!("CreateCompatibleDC/Bitmap fallo");
        }

        let old = SelectObject(mem_dc, bitmap);
        let blt_ok = BitBlt(mem_dc, 0, 0, wi, hi, screen_dc, rect.x, rect.y, SRCCOPY);
        SelectObject(mem_dc, old); // deseleccionar el bitmap ANTES de GetDIBits

        let mut bmi: BITMAPINFO = std::mem::zeroed();
        bmi.bmiHeader.biSize = std::mem::size_of::<BITMAPINFOHEADER>() as u32;
        bmi.bmiHeader.biWidth = wi;
        bmi.bmiHeader.biHeight = -hi; // negativo = top-down (fila 0 = arriba)
        bmi.bmiHeader.biPlanes = 1;
        bmi.bmiHeader.biBitCount = 32;
        bmi.bmiHeader.biCompression = 0; // BI_RGB (sin compresion)

        let mut buf = vec![0u8; (w * h * 4) as usize];
        let lines = GetDIBits(
            mem_dc,
            bitmap,
            0,
            h,
            buf.as_mut_ptr() as *mut c_void,
            &mut bmi,
            DIB_RGB_COLORS,
        );

        DeleteObject(bitmap);
        DeleteDC(mem_dc);
        ReleaseDC(std::ptr::null_mut(), screen_dc);

        if blt_ok == 0 {
            anyhow::bail!("BitBlt fallo");
        }
        if lines == 0 {
            anyhow::bail!("GetDIBits no devolvio scanlines");
        }

        // Un DIB de 32bpp viene en orden BGRA y GDI deja el 4to byte en 0;
        // lo pasamos a RGBA opaco para `image`/PNG.
        for px in buf.chunks_exact_mut(4) {
            px.swap(0, 2);
            px[3] = 255;
        }
        RgbaImage::from_raw(w, h, buf).context("RgbaImage::from_raw")
    }
}

/// Fallback no-Windows: captura el monitor con xcap y recorta la region.
#[cfg(not(windows))]
fn capture_region(rect: Rect) -> Result<RgbaImage> {
    let monitors = xcap::Monitor::all().context("xcap::Monitor::all")?;
    let monitor = monitors
        .iter()
        .find(|m| {
            let (mx, my) = (m.x(), m.y());
            let (mw, mh) = (m.width() as i32, m.height() as i32);
            rect.x >= mx
                && rect.y >= my
                && rect.x + rect.w as i32 <= mx + mw
                && rect.y + rect.h as i32 <= my + mh
        })
        .cloned()
        .or_else(|| monitors.first().cloned())
        .context("ningun monitor encontrado")?;
    let full = monitor.capture_image().context("monitor.capture_image")?;
    let rel_x = (rect.x - monitor.x()).max(0) as u32;
    let rel_y = (rect.y - monitor.y()).max(0) as u32;
    let w = rect.w.min(full.width().saturating_sub(rel_x));
    let h = rect.h.min(full.height().saturating_sub(rel_y));
    Ok(image::imageops::crop_imm(&full, rel_x, rel_y, w, h).to_image())
}

/// Pinta de negro los pixeles fuera del circulo inscrito.
///
/// El circulo esta centrado en el rect y su radio es min(w, h) / 2. Esto
/// elimina el ruido de la zona vacia cuando el marker es circular (radar del
/// viento) — el OCR / detector de puntero solo ve el contenido relevante.
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
