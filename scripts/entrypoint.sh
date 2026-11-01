#!/bin/bash
set -e

# If REDIS_URL points to localhost/127.0.0.1 or is unset, launch internal Redis daemon
if [[ -z "$REDIS_URL" || "$REDIS_URL" == *"127.0.0.1"* || "$REDIS_URL" == *"localhost"* ]]; then
  echo "[entrypoint] Starting internal Redis server on 127.0.0.1:6379..."
  redis-server --daemonize yes --port 6379 --dir /tmp --save "" --appendonly no
  
  # Wait until Redis responds to ping
  until redis-cli -p 6379 ping 2>/dev/null | grep -q "PONG"; do
    sleep 0.1
  done
  echo "[entrypoint] Internal Redis server is ready."
fi

# Set default HTTP listening port (Hugging Face Spaces default is 7860)
PORT="${PORT:-7860}"

# If custom command arguments are passed (e.g. from docker-compose), execute them
if [ "$#" -gt 0 ]; then
  exec "$@"
else
  # Default standalone mode: Run FastAPI with embedded worker on $PORT
  export WORKER_MODE="${WORKER_MODE:-embedded}"
  echo "[entrypoint] Starting FastAPI application on port $PORT (WORKER_MODE=$WORKER_MODE)..."
  exec uvicorn src.api.main:app --host 0.0.0.0 --port "$PORT"
fi
