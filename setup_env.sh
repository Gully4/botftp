#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env 2>/dev/null || true
  echo "Template .env dibuat. Edit .env dan isi kredensial sendiri."
else
  echo ".env sudah ada; tidak ditimpa."
fi
