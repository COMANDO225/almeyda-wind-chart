//! IPC con el sidecar Python (`vision/main.py serve`).
//!
//! Mantiene un proceso Python vivo y le manda frames por stdin. Lee respuestas
//! JSON por stdout. Si el proceso muere, se reintenta arrancarlo.
//!
//! El sidecar espera lÃ­neas JSON con shape:
//!   {"type":"frame","detector":"wind|angle","frame_id":N,"png_b64":"..."}
//!   {"type":"config","config":{...}}    // opcional

use anyhow::{Context, Result};
use base64::Engine;
use serde::{Deserialize, Serialize};
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::Mutex;

/// Encuentra la raíz del proyecto (donde vive `vision/` y `.venv/`).
/// Tauri dev arranca con cwd en `src-tauri/`, así que subimos un nivel.
/// Buscamos hasta 3 niveles arriba por si el cwd cambia.
fn project_root() -> std::path::PathBuf {
    let cwd = std::env::current_dir().unwrap_or_else(|_| ".".into());
    let mut p = cwd.as_path();
    for _ in 0..3 {
        if p.join("vision").join("__init__.py").exists() {
            return p.to_path_buf();
        }
        match p.parent() {
            Some(parent) => p = parent,
            None => break,
        }
    }
    cwd
}

/// Path al python del venv del proyecto. Si no existe, fallback al `python`
/// global (que no tendrá rapidocr y los detectores fallarán silenciosamente).
fn python_path(root: &std::path::Path) -> std::path::PathBuf {
    let venv_python = if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    };
    if venv_python.exists() {
        log::info!("usando python del venv: {}", venv_python.display());
        venv_python
    } else {
        log::warn!("no se encuentra .venv/, usando python del PATH");
        std::path::PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
    }
}

#[derive(Debug, Serialize)]
pub struct DetectRequest<'a> {
    #[serde(rename = "type")]
    pub kind: &'static str,
    pub detector: &'a str,
    pub frame_id: u64,
    pub png_b64: String,
}

#[derive(Debug, Deserialize)]
pub struct DetectResponse {
    pub wind: Option<crate::state::WindReading>,
    pub angle: Option<crate::state::AngleReading>,
}

pub struct Sidecar {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    stdout: Mutex<Option<BufReader<ChildStdout>>>,
}

impl Sidecar {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            stdin: Mutex::new(None),
            stdout: Mutex::new(None),
        }
    }

    pub async fn ensure_running(&self) -> Result<()> {
        let mut child_guard = self.child.lock().await;
        if let Some(c) = child_guard.as_mut() {
            if c.try_wait()?.is_none() {
                return Ok(());
            }
        }
        let root = project_root();
        let py = python_path(&root);
        log::info!("arrancando sidecar Python (vision/main.py serve) en {}", root.display());
        let mut cmd = Command::new(&py);
        cmd.args(["-u", "-m", "vision.main", "serve"])
            .current_dir(&root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        let mut child = cmd.spawn().context("spawn python sidecar")?;
        let stdin = child.stdin.take().context("sidecar stdin")?;
        let stdout = BufReader::new(child.stdout.take().context("sidecar stdout")?);
        *self.stdin.lock().await = Some(stdin);
        *self.stdout.lock().await = Some(stdout);
        *child_guard = Some(child);
        Ok(())
    }

    pub async fn detect(
        &self,
        detector: &str,
        frame_id: u64,
        png_bytes: &[u8],
    ) -> Result<DetectResponse> {
        self.ensure_running().await?;
        let b64 = base64::engine::general_purpose::STANDARD.encode(png_bytes);
        let req = DetectRequest {
            kind: "frame",
            detector,
            frame_id,
            png_b64: b64,
        };
        let line = serde_json::to_string(&req)?;
        {
            let mut stdin = self.stdin.lock().await;
            let stdin = stdin.as_mut().context("sidecar stdin no inicializado")?;
            stdin.write_all(line.as_bytes()).await?;
            stdin.write_all(b"\n").await?;
            stdin.flush().await?;
        }
        let mut buf = String::new();
        {
            let mut stdout = self.stdout.lock().await;
            let stdout = stdout.as_mut().context("sidecar stdout no inicializado")?;
            stdout.read_line(&mut buf).await?;
        }
        if buf.is_empty() {
            anyhow::bail!("sidecar cerrÃ³ stdout inesperadamente");
        }
        Ok(serde_json::from_str(buf.trim())?)
    }
}

