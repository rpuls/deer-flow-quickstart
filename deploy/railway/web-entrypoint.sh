#!/bin/sh
# Frontend container entrypoint.
#
# Next.js evaluates `rewrites()` during `next build` and freezes the result into
# .next/routes-manifest.json, so DEER_FLOW_INTERNAL_GATEWAY_BASE_URL read at
# runtime never reaches the /api/* proxy - the server would keep dialling the
# build-time default (127.0.0.1:8001) and every API call would be refused.
#
# The image is therefore built against a sentinel host, which this script
# rewrites to the real Gateway URL before the server starts. That keeps one
# image usable in every environment instead of baking a deployment's topology
# into the build.
set -eu

SENTINEL="http://deerflow-gateway.invalid:8001"
TARGET="${DEER_FLOW_INTERNAL_GATEWAY_BASE_URL:-}"

# A misconfigured proxy target is the one failure that hides itself: the server
# starts, /healthz answers, the platform reports the deploy healthy, and every
# API call fails in the browser. So say something loud about it here.
if [ -z "$TARGET" ]; then
  echo "[entrypoint] WARNING: DEER_FLOW_INTERNAL_GATEWAY_BASE_URL is not set." >&2
  echo "[entrypoint] WARNING: falling back to http://127.0.0.1:8001, which on a multi-service" >&2
  echo "[entrypoint] WARNING: deployment is this container - /api/* will not reach the gateway." >&2
  TARGET="http://127.0.0.1:8001"
fi

case "$TARGET" in
  http://* | https://*) ;;
  *)
    echo "[entrypoint] ERROR: DEER_FLOW_INTERNAL_GATEWAY_BASE_URL must start with http:// or https://" >&2
    echo "[entrypoint] ERROR: got '$TARGET'. Refusing to start with a proxy target that cannot work." >&2
    exit 1
    ;;
esac

# Trailing slashes would produce `//api` after substitution.
TARGET="${TARGET%/}"

MANIFEST=/app/frontend/.next/routes-manifest.json

if [ -f "$MANIFEST" ]; then
  if grep -q "$SENTINEL" "$MANIFEST"; then
    # `|` as the delimiter: the replacement contains slashes and colons.
    sed -i "s|$SENTINEL|$TARGET|g" "$MANIFEST"
    echo "[entrypoint] gateway proxy target set to $TARGET"
  else
    echo "[entrypoint] gateway proxy target already resolved; leaving the manifest alone"
  fi
else
  echo "[entrypoint] WARNING: $MANIFEST not found; the /api proxy may be misconfigured" >&2
fi

# Every service in a one-click stack starts at the same moment, and nothing
# orders them. Serving the UI before the gateway answers means a first visitor
# gets a login page whose POST fails, which reads as a broken deployment rather
# than a slow one. Waiting is bounded and never fatal: /healthz deliberately
# does not consult the gateway, so a gateway outage must not also take the
# frontend down - it just means this container stops waiting and serves.
WAIT_SECONDS="${DEER_FLOW_GATEWAY_WAIT_SECONDS:-90}"
case "$WAIT_SECONDS" in
  '' | *[!0-9]*)
    echo "[entrypoint] WARNING: DEER_FLOW_GATEWAY_WAIT_SECONDS='$WAIT_SECONDS' is not a whole number; using 90" >&2
    WAIT_SECONDS=90
    ;;
esac

# Bounded by the wall clock, not by a loop counter: each probe costs its own
# connect timeout, so counting iterations would overshoot the budget by roughly
# the timeout on every pass and could outlast the platform's health check.
wait_for_gateway() {
  [ "$WAIT_SECONDS" -gt 0 ] || return 0
  started_at=$(date +%s)
  deadline=$((started_at + WAIT_SECONDS))
  while :; do
    if wget -q -T 3 -O /dev/null "$TARGET/health/ready" 2>/dev/null; then
      echo "[entrypoint] gateway answered /health/ready after $(($(date +%s) - started_at))s"
      return 0
    fi
    [ "$(date +%s)" -lt "$deadline" ] || break
    sleep 2
  done
  echo "[entrypoint] WARNING: gateway did not answer /health/ready within ${WAIT_SECONDS}s (waited $(($(date +%s) - started_at))s); starting anyway" >&2
  return 1
}

wait_for_gateway || true

cd /app/frontend
exec pnpm start
