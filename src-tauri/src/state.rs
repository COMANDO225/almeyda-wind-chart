//! Estado global de la app y comandos para que el frontend lea/escriba los
//! rects de los markers, ademas de persistencia con `tauri-plugin-store`.

use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_store::StoreExt;

use crate::physics::{CalibSample, MobileSpec};

const STORE_PATH: &str = "markers.json";

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
}

/// Punto en pixels FISICOS absolutos de pantalla. Lo usan los esquineros que
/// anclan la zona de juego (su vertice/cruz) y los puntos YO/EL.
#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
pub struct Point {
    pub x: i32,
    pub y: i32,
}

/// Par de puntos YO/EL para el frontend (overlay y panel).
#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
pub struct Points {
    pub yo: Option<Point>,
    pub el: Option<Point>,
}

#[derive(Debug, Clone)]
pub struct AppState {
    pub wind_rect: Option<Rect>,
    pub angle_rect: Option<Rect>,
    /// Vertices (cruz) de los esquineros que delimitan la zona de juego, en
    /// pixels fisicos absolutos. TL = esquina superior-izquierda, BR =
    /// inferior-derecha. Juntos definen el rectangulo de la zona jugable
    /// sobre el que viven los puntos YO/EL y la normalizacion de distancias.
    pub corner_tl: Option<Point>,
    pub corner_br: Option<Point>,
    /// Rect LOCAL (con PADDING) del overlay de la barra de fuerza, igual que los
    /// markers. El usuario lo coloca/redimensiona sobre la barra del juego.
    pub power_bar_rect: Option<Rect>,
    /// Locks de los overlays interactivos. `true` = bloqueado = click-through ON
    /// (el mouse pasa al juego, el overlay solo muestra). `false` = se puede
    /// mover/redimensionar. Default `false` para poder colocarlos la 1ra vez.
    pub power_bar_locked: bool,
    pub overlay_locked: bool,
    /// Puntos YO (origen del proyectil) y EL (destino), en pixels fisicos
    /// absolutos. Transitorios (se marcan con Q/E cada turno, no se persisten).
    pub yo_point: Option<Point>,
    pub el_point: Option<Point>,
    /// Fuerza recomendada mas reciente (0.0–4.0). Transitoria.
    pub last_force: Option<f64>,
    /// Parametros fisicos del Armor (calibrables) + muestras de calibracion.
    pub armor_spec: MobileSpec,
    pub calib_samples: Vec<CalibSample>,
    pub last_wind: Option<WindReading>,
    pub last_angle: Option<AngleReading>,
    /// Anti-rebote del angulo: valor candidato a confirmar y cuantos frames
    /// consecutivos lleva leido. NO se serializa ni persiste.
    pub angle_pending: Option<i32>,
    pub angle_pending_count: u8,
    /// Ventana de lecturas recientes del viento para el suavizado temporal
    /// (promedio circular de dirección + moda del número). NO se serializa.
    pub wind_history: VecDeque<WindReading>,
    /// Si los markers se ocultan de capturas externas (WDA_EXCLUDEFROMCAPTURE).
    /// Default `true`: comportamiento heredado, los markers no aparecen en
    /// ninguna captura. El usuario lo puede apagar desde el panel cuando
    /// quiera que SI aparezcan (p.ej. para grabar un tutorial mostrandolos).
    pub exclude_from_capture: bool,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            wind_rect: None,
            angle_rect: None,
            corner_tl: None,
            corner_br: None,
            power_bar_rect: None,
            power_bar_locked: false,
            // El overlay de puntos nunca se interactua: siempre click-through.
            overlay_locked: true,
            yo_point: None,
            el_point: None,
            last_force: None,
            armor_spec: MobileSpec::armor_default(),
            calib_samples: Vec::new(),
            last_wind: None,
            last_angle: None,
            angle_pending: None,
            angle_pending_count: 0,
            wind_history: VecDeque::new(),
            exclude_from_capture: true,
        }
    }
}

impl AppState {
    /// Rectangulo de la zona de juego en pixels fisicos absolutos, derivado de
    /// los dos esquineros. Normaliza el orden (min/max) por si el usuario los
    /// coloco cruzados. `None` si falta algun esquinero o el area es degenerada.
    pub fn game_zone(&self) -> Option<Rect> {
        let tl = self.corner_tl?;
        let br = self.corner_br?;
        let x0 = tl.x.min(br.x);
        let y0 = tl.y.min(br.y);
        let w = (tl.x.max(br.x) - x0) as u32;
        let h = (tl.y.max(br.y) - y0) as u32;
        if w == 0 || h == 0 {
            return None;
        }
        Some(Rect { x: x0, y: y0, w, h })
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default)]
pub struct WindReading {
    pub value: Option<i32>,
    pub direction_deg: Option<f64>,
    pub confidence: f64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default)]
pub struct AngleReading {
    pub value: Option<i32>,
    pub confidence: f64,
}

#[tauri::command]
pub fn get_marker_rect(name: &str, state: tauri::State<'_, Mutex<AppState>>) -> Option<Rect> {
    let s = state.lock().unwrap();
    match name {
        "wind" => s.wind_rect,
        "angle" => s.angle_rect,
        "power_bar" => s.power_bar_rect,
        _ => None,
    }
}

#[tauri::command]
pub async fn set_marker_rect<R: Runtime>(
    name: String,
    rect: Rect,
    app: AppHandle<R>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    {
        let mut s = state.lock().unwrap();
        match name.as_str() {
            "wind" => s.wind_rect = Some(rect),
            "angle" => s.angle_rect = Some(rect),
            "power_bar" => s.power_bar_rect = Some(rect),
            other => return Err(format!("marker desconocido: {other}")),
        }
    }
    persist(&app).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_corner(name: &str, state: tauri::State<'_, Mutex<AppState>>) -> Option<Point> {
    let s = state.lock().unwrap();
    match name {
        "tl" => s.corner_tl,
        "br" => s.corner_br,
        _ => None,
    }
}

/// El esquinero reporta el vertice de su cruz (centro de la ventana) en pixels
/// fisicos absolutos cada vez que se mueve. Guardamos y persistimos; al fijar
/// ambos, logueamos la zona de juego resultante para verificacion.
#[tauri::command]
pub async fn set_corner<R: Runtime>(
    name: String,
    point: Point,
    app: AppHandle<R>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    let zone = {
        let mut s = state.lock().unwrap();
        match name.as_str() {
            "tl" => s.corner_tl = Some(point),
            "br" => s.corner_br = Some(point),
            other => return Err(format!("esquinero desconocido: {other}")),
        }
        s.game_zone()
    };
    if let Some(z) = zone {
        log::info!("zona de juego → x={} y={} w={} h={}", z.x, z.y, z.w, z.h);
    }
    persist(&app).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn get_game_zone(state: tauri::State<'_, Mutex<AppState>>) -> Option<Rect> {
    state.lock().unwrap().game_zone()
}

#[tauri::command]
pub fn get_points(state: tauri::State<'_, Mutex<AppState>>) -> Points {
    let s = state.lock().unwrap();
    Points {
        yo: s.yo_point,
        el: s.el_point,
    }
}

/// Coloca el punto YO o EL (lo llama el handler de las hotkeys Q/E con la
/// posicion del cursor). Emite `points:update` y recalcula la fuerza. NO
/// persiste (los puntos son transitorios por turno).
pub fn set_point<R: Runtime>(app: &AppHandle<R>, which: &str, point: Point) {
    let points = {
        let state = app.state::<Mutex<AppState>>();
        let mut s = state.lock().unwrap();
        match which {
            "yo" => s.yo_point = Some(point),
            "el" => s.el_point = Some(point),
            _ => return,
        }
        Points {
            yo: s.yo_point,
            el: s.el_point,
        }
    };
    let _ = app.emit("points:update", &points);
    crate::physics::recompute_and_emit(app);
}

#[tauri::command]
pub async fn clear_points<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    {
        let mut s = state.lock().unwrap();
        s.yo_point = None;
        s.el_point = None;
    }
    let _ = app.emit("points:update", &Points::default());
    crate::physics::recompute_and_emit(&app);
    Ok(())
}

/// Info de calibracion para el panel: nº de muestras y la `k` actual del Armor.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct CalibInfo {
    pub samples: usize,
    pub k: f64,
    pub wind_factor: f64,
}

#[tauri::command]
pub fn get_calibration(state: tauri::State<'_, Mutex<AppState>>) -> CalibInfo {
    let s = state.lock().unwrap();
    CalibInfo {
        samples: s.calib_samples.len(),
        k: s.armor_spec.k,
        wind_factor: s.armor_spec.wind_factor,
    }
}

/// Registra una muestra de calibracion (un disparo real). `d_screen` se toma de
/// los puntos YO/EL actuales si los hay; el resto lo aporta el usuario.
#[tauri::command]
pub async fn add_calibration_sample<R: Runtime>(
    force_used: f64,
    hit: bool,
    app: AppHandle<R>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<CalibInfo, String> {
    let info = {
        let mut s = state.lock().unwrap();
        let Some(zone) = s.game_zone() else {
            return Err("falta anclar la zona de juego (esquineros)".into());
        };
        let (Some(yo), Some(el)) = (s.yo_point, s.el_point) else {
            return Err("faltan los puntos YO/EL".into());
        };
        let dx = (el.x - yo.x) as f64;
        let dy = (el.y - yo.y) as f64;
        let d_screen = (dx * dx + dy * dy).sqrt() / zone.w.max(1) as f64;
        let angle_deg = s.last_angle.and_then(|a| a.value).unwrap_or(0) as f64;
        let (wind_mag, wind_dir_deg) = match s.last_wind {
            Some(w) => (w.value.unwrap_or(0) as f64, w.direction_deg.unwrap_or(0.0)),
            None => (0.0, 0.0),
        };
        s.calib_samples.push(CalibSample {
            d_screen,
            angle_deg,
            wind_mag,
            wind_dir_deg,
            force_used,
            hit,
        });
        CalibInfo {
            samples: s.calib_samples.len(),
            k: s.armor_spec.k,
            wind_factor: s.armor_spec.wind_factor,
        }
    };
    persist(&app).map_err(|e| e.to_string())?;
    Ok(info)
}

/// Limpia todas las muestras de calibracion y vuelve al spec base del Armor.
/// Util cuando el usuario registro muestras con valores incorrectos.
#[tauri::command]
pub async fn clear_calibration<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<CalibInfo, String> {
    let info = {
        let mut s = state.lock().unwrap();
        s.calib_samples.clear();
        s.armor_spec = MobileSpec::armor_default();
        CalibInfo {
            samples: 0,
            k: s.armor_spec.k,
            wind_factor: s.armor_spec.wind_factor,
        }
    };
    persist(&app).map_err(|e| e.to_string())?;
    Ok(info)
}

/// Ajusta la `k` del Armor por la mediana de las muestras que pegaron y
/// recalcula la fuerza con el nuevo spec.
#[tauri::command]
pub async fn fit_calibration<R: Runtime>(
    app: AppHandle<R>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<CalibInfo, String> {
    let info = {
        let mut s = state.lock().unwrap();
        let base = s.armor_spec;
        let Some(fitted) = crate::physics::fit_k(&s.calib_samples, &base) else {
            return Err("no hay muestras utiles (necesito disparos marcados como acierto)".into());
        };
        s.armor_spec = fitted;
        CalibInfo {
            samples: s.calib_samples.len(),
            k: fitted.k,
            wind_factor: fitted.wind_factor,
        }
    };
    persist(&app).map_err(|e| e.to_string())?;
    crate::physics::recompute_and_emit(&app);
    Ok(info)
}

/// Mapea un nombre de overlay logico a su label de ventana Tauri.
fn overlay_window_label(name: &str) -> Option<&'static str> {
    match name {
        "power_bar" => Some("power_bar"),
        "overlay" => Some("overlay_zone"),
        _ => None,
    }
}

#[tauri::command]
pub fn get_lock(name: &str, state: tauri::State<'_, Mutex<AppState>>) -> bool {
    let s = state.lock().unwrap();
    match name {
        "power_bar" => s.power_bar_locked,
        "overlay" => s.overlay_locked,
        _ => false,
    }
}

/// Bloquea/desbloquea un overlay: `locked = true` activa el click-through (el
/// mouse pasa al juego) y `false` lo desactiva (se puede mover/redimensionar).
#[tauri::command]
pub async fn set_lock<R: Runtime>(
    name: String,
    locked: bool,
    app: AppHandle<R>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    let Some(label) = overlay_window_label(&name) else {
        return Err(format!("overlay desconocido: {name}"));
    };
    {
        let mut s = state.lock().unwrap();
        match name.as_str() {
            "power_bar" => s.power_bar_locked = locked,
            "overlay" => s.overlay_locked = locked,
            _ => unreachable!(),
        }
    }
    crate::set_click_through(&app, label, locked);
    persist(&app).map_err(|e| e.to_string())
}

pub fn persist<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let store = app.store(STORE_PATH)?;
    let s = app.state::<Mutex<AppState>>();
    let s = s.lock().unwrap();
    if let Some(r) = s.wind_rect {
        store.set("wind_rect", serde_json::to_value(r)?);
    }
    if let Some(r) = s.angle_rect {
        store.set("angle_rect", serde_json::to_value(r)?);
    }
    if let Some(p) = s.corner_tl {
        store.set("corner_tl", serde_json::to_value(p)?);
    }
    if let Some(p) = s.corner_br {
        store.set("corner_br", serde_json::to_value(p)?);
    }
    if let Some(r) = s.power_bar_rect {
        store.set("power_bar_rect", serde_json::to_value(r)?);
    }
    store.set(
        "power_bar_locked",
        serde_json::Value::Bool(s.power_bar_locked),
    );
    store.set("overlay_locked", serde_json::Value::Bool(s.overlay_locked));
    store.set("armor_spec", serde_json::to_value(s.armor_spec)?);
    store.set("calib_samples", serde_json::to_value(&s.calib_samples)?);
    store.set(
        "exclude_from_capture",
        serde_json::Value::Bool(s.exclude_from_capture),
    );
    store.save()?;
    Ok(())
}

pub async fn restore_from_store<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let store = app.store(STORE_PATH)?;
    let mut wind = None;
    let mut angle = None;
    let mut corner_tl = None;
    let mut corner_br = None;
    if let Some(v) = store.get("wind_rect") {
        wind = serde_json::from_value(v.clone()).ok();
    }
    if let Some(v) = store.get("angle_rect") {
        angle = serde_json::from_value(v.clone()).ok();
    }
    if let Some(v) = store.get("corner_tl") {
        corner_tl = serde_json::from_value(v.clone()).ok();
    }
    if let Some(v) = store.get("corner_br") {
        corner_br = serde_json::from_value(v.clone()).ok();
    }
    let mut power_bar_rect = None;
    if let Some(v) = store.get("power_bar_rect") {
        power_bar_rect = serde_json::from_value(v.clone()).ok();
    }
    let power_bar_locked = store
        .get("power_bar_locked")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let overlay_locked = store
        .get("overlay_locked")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let armor_spec = store
        .get("armor_spec")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
        .unwrap_or_else(MobileSpec::armor_default);
    let calib_samples: Vec<CalibSample> = store
        .get("calib_samples")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
        .unwrap_or_default();
    // Si el flag nunca se guardo, queda en el default (true) del AppState.
    let exclude = store
        .get("exclude_from_capture")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let state = app.state::<Mutex<AppState>>();
    let mut s = state.lock().unwrap();
    s.wind_rect = wind;
    s.angle_rect = angle;
    s.corner_tl = corner_tl;
    s.corner_br = corner_br;
    s.power_bar_rect = power_bar_rect;
    s.power_bar_locked = power_bar_locked;
    s.overlay_locked = overlay_locked;
    s.armor_spec = armor_spec;
    s.calib_samples = calib_samples;
    s.exclude_from_capture = exclude;
    Ok(())
}

#[tauri::command]
pub fn get_exclude_from_capture(state: tauri::State<'_, Mutex<AppState>>) -> bool {
    state.lock().unwrap().exclude_from_capture
}

/// El frontend cambia el toggle del panel → guardamos el flag, persistimos, y
/// aplicamos a las ventanas vivas (la funcion concreta vive en `lib.rs` porque
/// usa la Win32 API; aca solo manejamos el estado).
#[tauri::command]
pub async fn set_exclude_from_capture<R: Runtime>(
    enabled: bool,
    app: AppHandle<R>,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Result<(), String> {
    {
        let mut s = state.lock().unwrap();
        s.exclude_from_capture = enabled;
    }
    persist(&app).map_err(|e| e.to_string())?;
    crate::apply_marker_capture_affinity(&app, enabled);
    Ok(())
}
