// Wrappers tipados sobre los comandos Rust y los eventos que emite el backend.

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Point {
  x: number;
  y: number;
}

export interface Points {
  yo: Point | null;
  el: Point | null;
}

export interface WindReading {
  value: number | null;
  direction_deg: number | null;
  confidence: number;
}

export interface AngleReading {
  value: number | null;
  confidence: number;
}

/** Fuerza recomendada (0.0–4.0) que el sistema computa. `reachable` es false si
 *  el objetivo queda fuera de alcance fisico (no hay solucion). */
export interface ForceReading {
  value: number | null;
  reachable: boolean;
}

export type MarkerName = "wind" | "angle" | "power_bar";

export async function getMarkerRect(name: MarkerName): Promise<Rect | null> {
  return invoke<Rect | null>("get_marker_rect", { name });
}

export async function setMarkerRect(name: MarkerName, rect: Rect): Promise<void> {
  return invoke<void>("set_marker_rect", { name, rect });
}

export type CornerName = "tl" | "br";

/** Esquineros de la zona de juego. El vertice (cruz) se guarda/lee en pixels
 *  fisicos absolutos de pantalla. */
export async function getCorner(name: CornerName): Promise<Point | null> {
  return invoke<Point | null>("get_corner", { name });
}

export async function setCorner(name: CornerName, point: Point): Promise<void> {
  return invoke<void>("set_corner", { name, point });
}

/** Rectangulo de la zona de juego derivado de los dos esquineros (fisico
 *  absoluto). null si falta algun esquinero. */
export async function getGameZone(): Promise<Rect | null> {
  return invoke<Rect | null>("get_game_zone");
}

export type OverlayName = "power_bar" | "overlay";

/** Lock de un overlay interactivo. true = click-through ON (el mouse pasa al
 *  juego). false = se puede mover/redimensionar. */
export async function getLock(name: OverlayName): Promise<boolean> {
  return invoke<boolean>("get_lock", { name });
}

export async function setLock(name: OverlayName, locked: boolean): Promise<void> {
  return invoke<void>("set_lock", { name, locked });
}

/** Puntos YO/EL (origen/destino del disparo) en pixels fisicos absolutos. */
export async function getPoints(): Promise<Points> {
  return invoke<Points>("get_points");
}

export async function clearPoints(): Promise<void> {
  return invoke<void>("clear_points");
}

/** Emitido cuando el usuario coloca/limpia los puntos YO/EL (hotkeys Q/E). */
export function onPoints(handler: (p: Points) => void): Promise<UnlistenFn> {
  return listen<Points>("points:update", (e) => handler(e.payload));
}

export interface CalibInfo {
  samples: number;
  k: number;
  wind_factor: number;
}

export async function getCalibration(): Promise<CalibInfo> {
  return invoke<CalibInfo>("get_calibration");
}

/** Registra un disparo real (fuerza usada + si pego) con los YO/EL y el
 *  angulo/viento detectados actuales. Devuelve el estado de calibracion. */
export async function addCalibrationSample(forceUsed: number, hit: boolean): Promise<CalibInfo> {
  return invoke<CalibInfo>("add_calibration_sample", { forceUsed, hit });
}

/** Ajusta la constante k del Armor por la mediana de las muestras que pegaron. */
export async function fitCalibration(): Promise<CalibInfo> {
  return invoke<CalibInfo>("fit_calibration");
}

/** marker_wind: el backend corre 2 flujos internos (puntero + numero) y emite
 *  un WindReading con AMBOS campos llenos (value + direction_deg). */
export function onWind(handler: (w: WindReading) => void): Promise<UnlistenFn> {
  return listen<WindReading>("detection:wind", (e) => handler(e.payload));
}

export function onAngle(handler: (a: AngleReading) => void): Promise<UnlistenFn> {
  return listen<AngleReading>("detection:angle", (e) => handler(e.payload));
}

/** Fuerza recomendada recalculada por el backend (cambia con angulo/viento/puntos). */
export function onForce(handler: (f: ForceReading) => void): Promise<UnlistenFn> {
  return listen<ForceReading>("detection:force", (e) => handler(e.payload));
}

/** Marker capture affinity: cuando es true, los markers son INVISIBLES a
 *  capturas externas (WDA_EXCLUDEFROMCAPTURE). Default true. */
export async function getExcludeFromCapture(): Promise<boolean> {
  return invoke<boolean>("get_exclude_from_capture");
}

export async function setExcludeFromCapture(enabled: boolean): Promise<void> {
  return invoke<void>("set_exclude_from_capture", { enabled });
}
