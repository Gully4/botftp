#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1 PYTHONUTF8=1

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then PYTHON_BIN="$(command -v python)"
  else echo "[NEON V32] Python 3 tidak ditemukan." >&2; exit 127; fi
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "[NEON V32] Membuat virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi
VENV_PY="$PWD/.venv/bin/python"
echo "[NEON V32] Memeriksa dan memasang dependency otomatis..."
"$VENV_PY" -m pip install --disable-pip-version-check -q -r requirements.txt

if ! command -v cloudflared >/dev/null 2>&1 && [[ ! -x "$HOME/.local/bin/cloudflared" ]]; then
  echo "[NEON V32] PERINGATAN: cloudflared belum tersedia; cek replit.nix dan restart environment."
fi

# Only Gateway is launched here. Gateway itself starts and supervises bot.py.
exec "$VENV_PY" -u neon_gateway.py
