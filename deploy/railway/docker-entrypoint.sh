#!/bin/sh
# Gateway container entrypoint.
#
# Order matters: config.yaml must exist before uvicorn imports the app, because
# the Gateway lifespan loads it strictly. app.quickstart.bootstrap renders it
# from config.example.yaml plus the environment plus whatever the operator has
# already onboarded through the web UI.
set -eu

cd /app/backend

EXTENSIONS_CONFIG="${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-/app/extensions_config.json}"
if [ ! -f "$EXTENSIONS_CONFIG" ]; then
  cp /app/extensions_config.example.json "$EXTENSIONS_CONFIG"
fi

echo "[entrypoint] rendering config.yaml"
PYTHONPATH=. uv run --no-sync python -m app.quickstart.bootstrap

if [ "$#" -gt 0 ]; then
  # An explicit command overrides the default server, which is how one-off
  # tasks (a migration, a shell) run in the same image.
  exec "$@"
fi

# app.quickstart.serve owns the listening socket so the Gateway answers on IPv4
# and IPv6 at once — see its docstring for why uvicorn cannot do that itself.
echo "[entrypoint] starting gateway"
exec env PYTHONPATH=. uv run --no-sync python -m app.quickstart.serve
