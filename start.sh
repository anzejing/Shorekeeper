#!/usr/bin/env bash
# Shorekeeper — 一键启动前后端
# Usage: ./start.sh

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo "Done."
}
trap cleanup EXIT INT TERM

# --- Backend ---
echo "Starting backend..."
cd "$BACKEND"
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# --- Frontend ---
echo "Starting frontend..."
cd "$FRONTEND"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "================================"
echo "  Shorekeeper is running"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000"
echo "  Press Ctrl+C to stop"
echo "================================"
echo ""

wait
