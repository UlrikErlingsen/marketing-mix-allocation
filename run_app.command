#!/bin/bash
set -e

cd "$(dirname "$0")"

PID_FILE=".venv/.allocsignal.pid"
PORT_FILE=".venv/.allocsignal.port"

if [ -f "$PID_FILE" ] && [ -f "$PORT_FILE" ]; then
  EXISTING_PID="$(/bin/cat "$PID_FILE")"
  EXISTING_PORT="$(/bin/cat "$PORT_FILE")"
  EXISTING_URL="http://127.0.0.1:${EXISTING_PORT}"
  if /bin/kill -0 "$EXISTING_PID" 2>/dev/null && /usr/bin/curl -fsS "${EXISTING_URL}/_stcore/health" >/dev/null 2>&1; then
    echo "AllocSignal is already running. Opening it now."
    if [ "${ALLOCSIGNAL_NO_BROWSER:-0}" != "1" ]; then
      /usr/bin/open "$EXISTING_URL"
    fi
    exit 0
  fi
  /bin/rm -f "$PID_FILE" "$PORT_FILE"
fi

if ! /usr/bin/env python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "AllocSignal needs Python 3.10 or newer."
  echo "Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Return to close..."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating AllocSignal's private Python environment..."
  /usr/bin/env python3 -m venv .venv
fi

source .venv/bin/activate
export ARROW_DEFAULT_MEMORY_POOL="${ARROW_DEFAULT_MEMORY_POOL:-system}"

REQUIREMENTS_HASH="$(/usr/bin/shasum -a 256 requirements.txt | /usr/bin/awk '{print $1}')"
READY_FILE=".venv/.allocsignal-requirements-${REQUIREMENTS_HASH}"
if [ ! -f "$READY_FILE" ]; then
  echo "First launch: downloading AllocSignal's Python packages. This can take a few minutes."
  echo "Later launches will be much faster and can work offline."
  python -m pip --disable-pip-version-check install --prefer-binary -r requirements.txt
  /bin/rm -f .venv/.allocsignal-requirements-* .venv/.allocsignal-ready
  /usr/bin/touch "$READY_FILE"
else
  echo "Using the existing AllocSignal environment."
fi

PORT="${ALLOCSIGNAL_PORT:-8593}"
if ! python - "$PORT" <<'PY'
import socket
import sys

sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
then
  echo "AllocSignal's local port ${PORT} is already in use."
  echo "Close the other app, or launch with ALLOCSIGNAL_PORT set to a different private port."
  read -r -p "Press Return to close..."
  exit 1
fi

URL="http://127.0.0.1:${PORT}"
MAX_UPLOAD_MB="${ALLOCSIGNAL_MAX_UPLOAD_MB:-200}"

echo "Starting AllocSignal at ${URL}..."
python -m streamlit run app.py \
  --server.headless=true \
  --server.address=127.0.0.1 \
  --server.port="$PORT" \
  --server.maxUploadSize="$MAX_UPLOAD_MB" \
  --server.fileWatcherType=none \
  --browser.gatherUsageStats=false >.venv/allocsignal.log 2>&1 &
APP_PID=$!

echo "$APP_PID" > "$PID_FILE"
echo "$PORT" > "$PORT_FILE"

cleanup() {
  /bin/rm -f "$PID_FILE" "$PORT_FILE"
}
trap cleanup EXIT

for _ in {1..80}; do
  if ! /bin/kill -0 "$APP_PID" 2>/dev/null; then
    echo "AllocSignal stopped before it was ready."
    /bin/cat .venv/allocsignal.log
    read -r -p "Press Return to close..."
    exit 1
  fi
  if /usr/bin/curl -fsS "${URL}/_stcore/health" >/dev/null 2>&1; then
    echo "AllocSignal is ready. Keep this window open while you use the app."
    if [ "${ALLOCSIGNAL_NO_BROWSER:-0}" != "1" ]; then
      /usr/bin/open "$URL"
    fi
    wait "$APP_PID"
    exit $?
  fi
  /bin/sleep 0.25
done

echo "AllocSignal took too long to start."
/bin/cat .venv/allocsignal.log
/bin/kill "$APP_PID" 2>/dev/null || true
read -r -p "Press Return to close..."
exit 1
