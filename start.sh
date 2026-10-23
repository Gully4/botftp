#!/usr/bin/env bash
set -u
mkdir -p logs downloads

# Prefer a maintained CA bundle for HTTPS clients (including HTTPX/Telegram).
# TLS certificate verification stays enabled.
if python -c "import certifi" >/dev/null 2>&1; then
  CERT_BUNDLE="$(python -m certifi 2>/dev/null || true)"
  if [ -n "$CERT_BUNDLE" ] && [ -f "$CERT_BUNDLE" ]; then
    export SSL_CERT_FILE="$CERT_BUNDLE"
    export REQUESTS_CA_BUNDLE="$CERT_BUNDLE"
    echo "[$(date -Is)] TLS CA bundle: $CERT_BUNDLE" >> logs/runner.log
  else
    echo "[$(date -Is)] WARNING: certifi bundle path not found; using runtime defaults" >> logs/runner.log
  fi
else
  echo "[$(date -Is)] WARNING: certifi not installed; run pip install -r requirements.txt" >> logs/runner.log
fi

RESTART_DELAY=5
MAX_RESTART_DELAY=60
trap 'echo "[$(date -Is)] Stop signal received" >> logs/runner.log; exit 0' INT TERM
while true; do
  echo "[$(date -Is)] Starting NEON OS multi-bot" >> logs/runner.log
  python -u bot.py >> logs/bot.log 2>&1
  STATUS=$?
  echo "[$(date -Is)] bot.py exited status=$STATUS; restart in ${RESTART_DELAY}s" >> logs/runner.log
  sleep "$RESTART_DELAY"
  if [ "$RESTART_DELAY" -lt "$MAX_RESTART_DELAY" ]; then
    RESTART_DELAY=$((RESTART_DELAY * 2))
    if [ "$RESTART_DELAY" -gt "$MAX_RESTART_DELAY" ]; then RESTART_DELAY="$MAX_RESTART_DELAY"; fi
  fi
done
