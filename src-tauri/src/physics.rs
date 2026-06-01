//! Motor de fisica del asistente de punteria.
//!
//! Computa la FUERZA (0.0–4.0) que necesita el disparo para ir del punto YO al
//! punto EL, dado el angulo y el viento detectados y el mobile seleccionado.
//! La fuerza es el OUTPUT del sistema (no un input).
//!
//! Modelo: trayectoria parabolica de Gunbound/Dragonbound (gravedad g=98). La
//! relacion fuerza↔alcance se despeja de:
//!
//!   Power = sqrt( D / ( k^2 · sin(2θ) · (1/(g + W·sin(X))) ) ) · 4
//!         = sqrt( D · (g + W·sin(X)) / (k^2 · sin(2θ)) ) · 4
//!
//! con D = distancia YO→EL en "unidades de pantalla" (px / ancho de la zona),
//! θ = angulo, W = magnitud del viento, X = direccion del viento (convencion
//! del proyecto: 0°=este, 90°=abajo, horario — sin(X)=componente VERTICAL).
//!
//! La constante `k` (escala/velocidad de bala del mobile) y el `wind_factor`
//! NO estan documentados con precision; el modo calibracion los ajusta a partir
//! de disparos reales. El default solo da un punto de partida razonable.

use serde::{Deserialize, Serialize};
use std::sync::Mutex;

use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::state::AppState;

/// Parametros fisicos de un mobile. `k` y `wind_factor` se calibran.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct MobileSpec {
    pub gravity: f64,
    pub k: f64,
    pub wind_factor: f64,
}

impl MobileSpec {
    /// Default del Armor: g=98 (estandar Gunbound), k≈47.87 (constante de escala
    /// reportada en analisis comunitarios), wind_factor=1.0 (sin ajustar).
    pub fn armor_default() -> Self {
        Self {
            gravity: 98.0,
            k: 47.87,
            wind_factor: 1.0,
        }
    }
}

impl Default for MobileSpec {
    fn default() -> Self {
        Self::armor_default()
    }
}

/// Una muestra de calibracion: un disparo real con resultado conocido.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct CalibSample {
    pub d_screen: f64,
    pub angle_deg: f64,
    pub wind_mag: f64,
    pub wind_dir_deg: f64,
    pub force_used: f64,
    pub hit: bool,
}

/// Lectura de fuerza emitida al frontend. `reachable=false` si el objetivo no
/// tiene solucion fisica con el angulo/viento actuales.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default)]
pub struct ForceReading {
    pub value: Option<f64>,
    pub reachable: bool,
}

/// Gravedad efectiva = gravedad + componente VERTICAL del viento. El viento
/// hacia abajo (sin(X)>0) "pesa" mas → mas fuerza para el mismo alcance.
fn effective_gravity(spec: &MobileSpec, wind_mag: f64, wind_dir_deg: f64) -> f64 {
    spec.gravity + spec.wind_factor * wind_mag * wind_dir_deg.to_radians().sin()
}

/// Fuerza (0.0–4.0) requerida para alcanzar el objetivo, o `None` si no hay
/// solucion fisica (angulo fuera de (0,90), gravedad efectiva no positiva).
///
/// `angle_deg` se toma en MAGNITUD: el alcance horizontal es simetrico izq/der,
/// y la direccion la decide de que lado quedo EL respecto de YO.
pub fn required_force(
    d_screen: f64,
    angle_deg: f64,
    wind_mag: f64,
    wind_dir_deg: f64,
    spec: &MobileSpec,
) -> Option<f64> {
    let theta = angle_deg.abs().to_radians();
    let sin2 = (2.0 * theta).sin();
    if sin2 <= 1e-6 {
        return None;
    }
    let g_eff = effective_gravity(spec, wind_mag, wind_dir_deg);
    if g_eff <= 0.0 {
        return None;
    }
    let inside = d_screen * g_eff / (spec.k * spec.k * sin2);
    if inside < 0.0 {
        return None;
    }
    Some((inside.sqrt() * 4.0).clamp(0.0, 4.0))
}

/// Despeja la constante `k` de UNA muestra (asumiendo wind_factor del spec):
///   k = sqrt( D · g_eff / sin(2θ) ) / (force/4)
/// `None` si la muestra es degenerada (fuerza 0, angulo fuera de rango, etc.).
pub fn solve_k(sample: &CalibSample, spec: &MobileSpec) -> Option<f64> {
    let theta = sample.angle_deg.abs().to_radians();
    let sin2 = (2.0 * theta).sin();
    if sin2 <= 1e-6 || sample.force_used <= 1e-6 {
        return None;
    }
    let g_eff = effective_gravity(spec, sample.wind_mag, sample.wind_dir_deg);
    if g_eff <= 0.0 {
        return None;
    }
    let num = (sample.d_screen * g_eff / sin2).sqrt();
    Some(num / (sample.force_used / 4.0))
}

/// Mediana (robusta a outliers) de una lista no vacia.
fn median(mut xs: Vec<f64>) -> Option<f64> {
    if xs.is_empty() {
        return None;
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = xs.len();
    Some(if n % 2 == 1 {
        xs[n / 2]
    } else {
        (xs[n / 2 - 1] + xs[n / 2]) / 2.0
    })
}

/// Ajusta `k` por la MEDIANA de las k despejadas de las muestras que PEGARON.
/// Devuelve el spec ajustado, o `None` si no hay muestras utiles.
pub fn fit_k(samples: &[CalibSample], base: &MobileSpec) -> Option<MobileSpec> {
    let ks: Vec<f64> = samples
        .iter()
        .filter(|s| s.hit)
        .filter_map(|s| solve_k(s, base))
        .collect();
    let k = median(ks)?;
    if !(k.is_finite() && k > 0.0) {
        return None;
    }
    Some(MobileSpec { k, ..*base })
}

/// Recalcula la fuerza con el estado actual (angulo, viento, puntos, zona, spec)
/// y la emite como `detection:force`. Se llama cuando cambia cualquier input.
pub fn recompute_and_emit<R: Runtime>(app: &AppHandle<R>) {
    let reading = {
        let s = app.state::<Mutex<AppState>>();
        let s = s.lock().unwrap();
        compute_from_state(&s)
    };
    {
        let s = app.state::<Mutex<AppState>>();
        s.lock().unwrap().last_force = reading.value;
    }
    let _ = app.emit("detection:force", &reading);
}

/// Computa la fuerza a partir de un snapshot del estado. Separada para testear
/// sin un AppHandle.
pub fn compute_from_state(s: &AppState) -> ForceReading {
    let (Some(yo), Some(el), Some(zone), Some(angle)) = (
        s.yo_point,
        s.el_point,
        s.game_zone(),
        s.last_angle.and_then(|a| a.value),
    ) else {
        return ForceReading::default();
    };
    let dx = (el.x - yo.x) as f64;
    let dy = (el.y - yo.y) as f64;
    let dist_px = (dx * dx + dy * dy).sqrt();
    let d_screen = dist_px / zone.w.max(1) as f64;
    let (wind_mag, wind_dir) = match s.last_wind {
        Some(w) => (w.value.unwrap_or(0) as f64, w.direction_deg.unwrap_or(0.0)),
        None => (0.0, 0.0),
    };
    match required_force(d_screen, angle as f64, wind_mag, wind_dir, &s.armor_spec) {
        Some(v) => ForceReading {
            value: Some(v),
            reachable: true,
        },
        None => ForceReading {
            value: None,
            reachable: false,
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fuerza_crece_con_la_distancia() {
        let spec = MobileSpec::armor_default();
        let f1 = required_force(0.5, 45.0, 0.0, 0.0, &spec).unwrap();
        let f2 = required_force(1.5, 45.0, 0.0, 0.0, &spec).unwrap();
        assert!(f2 > f1, "mas distancia → mas fuerza");
    }

    #[test]
    fn angulo_nulo_no_tiene_solucion() {
        let spec = MobileSpec::armor_default();
        assert!(required_force(1.0, 0.0, 0.0, 0.0, &spec).is_none());
    }

    #[test]
    fn k_round_trip() {
        // Con una fuerza/distancia coherentes, solve_k recupera la k del spec.
        let spec = MobileSpec::armor_default();
        let force = required_force(1.0, 50.0, 0.0, 0.0, &spec).unwrap();
        let sample = CalibSample {
            d_screen: 1.0,
            angle_deg: 50.0,
            wind_mag: 0.0,
            wind_dir_deg: 0.0,
            force_used: force,
            hit: true,
        };
        let k = solve_k(&sample, &spec).unwrap();
        assert!(
            (k - spec.k).abs() < 1e-6,
            "k recuperada = {k}, esperada {}",
            spec.k
        );
    }
}
