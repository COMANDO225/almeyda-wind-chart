// Helpers de logging que mandan al backend Rust (tauri-plugin-log).
// El backend escribe a un archivo unificado en:
//   %APPDATA%\com.aidragonbound.app\logs\ai-dragonbound.log   (Windows)
//   ~/.config/com.aidragonbound.app/logs/ai-dragonbound.log   (Linux)
// y también al stdout del proceso (vista en `tauri-dev.log` durante dev).
//
// Para tail-ear en tiempo real desde PowerShell:
//   Get-Content "$env:APPDATA\com.aidragonbound.app\logs\ai-dragonbound.log" -Wait -Tail 30

import { trace, debug, info, warn, error } from "@tauri-apps/plugin-log";

const target = (window: string) => `frontend.${window}`;

/** Detecta el nombre de la ventana actual desde el query string (?name=wind|angle)
 *  o la primera ruta. Útil para distinguir logs de cada ventana. */
function whoami(): string {
  if (typeof window === "undefined") return "?";
  const q = new URLSearchParams(window.location.search);
  const name = q.get("name");
  if (name) return `marker_${name}`;
  if (window.location.pathname.includes("/panel")) return "control_panel";
  return "app";
}

const who = whoami();

function fmt(msg: string, data?: unknown): string {
  if (data === undefined) return msg;
  try {
    return `${msg} | ${JSON.stringify(data)}`;
  } catch {
    return `${msg} | <unserializable>`;
  }
}

export const log = {
  trace: (msg: string, data?: unknown) => trace(fmt(msg, data), { keyValues: { target: target(who) } }),
  debug: (msg: string, data?: unknown) => debug(fmt(msg, data), { keyValues: { target: target(who) } }),
  info:  (msg: string, data?: unknown) => info(fmt(msg, data),  { keyValues: { target: target(who) } }),
  warn:  (msg: string, data?: unknown) => warn(fmt(msg, data),  { keyValues: { target: target(who) } }),
  error: (msg: string, data?: unknown) => error(fmt(msg, data), { keyValues: { target: target(who) } }),
};
