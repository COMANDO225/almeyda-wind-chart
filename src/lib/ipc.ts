// Wrappers tipados sobre los comandos Rust y los eventos que emite el backend.

import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
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

export type MarkerName = "wind" | "angle";

export async function getMarkerRect(name: MarkerName): Promise<Rect | null> {
  return invoke<Rect | null>("get_marker_rect", { name });
}

export async function setMarkerRect(name: MarkerName, rect: Rect): Promise<void> {
  return invoke<void>("set_marker_rect", { name, rect });
}

/** marker_wind: el backend corre 2 flujos internos (puntero + numero) y emite
 *  un WindReading con AMBOS campos llenos (value + direction_deg). */
export function onWind(handler: (w: WindReading) => void): Promise<UnlistenFn> {
  return listen<WindReading>("detection:wind", (e) => handler(e.payload));
}

export function onAngle(handler: (a: AngleReading) => void): Promise<UnlistenFn> {
  return listen<AngleReading>("detection:angle", (e) => handler(e.payload));
}

/** Marker capture affinity: cuando es true, los markers son INVISIBLES a
 *  capturas externas (WDA_EXCLUDEFROMCAPTURE). Default true. */
export async function getExcludeFromCapture(): Promise<boolean> {
  return invoke<boolean>("get_exclude_from_capture");
}

export async function setExcludeFromCapture(enabled: boolean): Promise<void> {
  return invoke<void>("set_exclude_from_capture", { enabled });
}
