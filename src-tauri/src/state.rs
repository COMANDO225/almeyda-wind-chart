//! Estado global de la app y comandos para que el frontend lea/escriba los
//! rects de los markers, ademÃ¡s de persistencia con `tauri-plugin-store`.

use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, Runtime};
use tauri_plugin_store::StoreExt;

const STORE_PATH: &str = "markers.json";

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
}

#[derive(Debug, Default, Clone)]
pub struct AppState {
    pub wind_rect: Option<Rect>,
    pub angle_rect: Option<Rect>,
    pub last_wind: Option<WindReading>,
    pub last_angle: Option<AngleReading>,
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
pub fn get_marker_rect(
    name: &str,
    state: tauri::State<'_, Mutex<AppState>>,
) -> Option<Rect> {
    let s = state.lock().unwrap();
    match name {
        "wind" => s.wind_rect,
        "angle" => s.angle_rect,
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
            other => return Err(format!("marker desconocido: {other}")),
        }
    }
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
    store.save()?;
    Ok(())
}

pub async fn restore_from_store<R: Runtime>(app: &AppHandle<R>) -> anyhow::Result<()> {
    let store = app.store(STORE_PATH)?;
    let mut wind = None;
    let mut angle = None;
    if let Some(v) = store.get("wind_rect") {
        wind = serde_json::from_value(v.clone()).ok();
    }
    if let Some(v) = store.get("angle_rect") {
        angle = serde_json::from_value(v.clone()).ok();
    }
    let state = app.state::<Mutex<AppState>>();
    let mut s = state.lock().unwrap();
    s.wind_rect = wind;
    s.angle_rect = angle;
    Ok(())
}

