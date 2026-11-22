#!/bin/sh
set -eu

# Schema migrations are guarded by a Postgres advisory lock, so it is safe
# for several replicas to start at once.
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "running database migrations"
  alembic upgrade head
fi

# exec => uvicorn is PID 1 and receives SIGTERM for graceful shutdown.
exec uvicorn "$APP_FACTORY" --factory \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --proxy-headers \
  --forwarded-allow-ips "*" \
  --no-access-log \
  --no-server-header \
  --timeout-graceful-shutdown 20
