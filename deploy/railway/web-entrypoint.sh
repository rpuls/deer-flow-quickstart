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
TARGET="${DEER_FLOW_INTERNAL_GATEWAY_BASE_URL:-http://127.0.0.1:8001}"
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
  echo "[entrypoint] warning: $MANIFEST not found; the /api proxy may be misconfigured" >&2
fi

cd /app/frontend
exec pnpm start
