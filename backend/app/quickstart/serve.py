"""Uvicorn launcher that listens on IPv4 and IPv6 at the same time.

Neither single-family bind is correct everywhere:

* ``0.0.0.0`` is invisible on Railway, whose private network is IPv6-only, so
  the frontend service cannot reach the Gateway at all.
* ``::`` looks like it covers both, but asyncio sets ``IPV6_V6ONLY`` on every
  AF_INET6 listener it creates, so an IPv4 client - a Docker Compose service
  name, a ``127.0.0.1`` health check - gets connection refused.

So the socket is created here instead, with ``dualstack_ipv6``, and handed to
uvicorn by file descriptor. Hosts without IPv6 fall back to a plain IPv4
listener.
"""

from __future__ import annotations

import logging
import os
import socket
import sys

import uvicorn

logger = logging.getLogger("app.quickstart.serve")

DEFAULT_APP = "app.gateway.app:app"
BACKLOG = 2048


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using %d", name, raw, default)
        return default


def listen_port() -> int:
    """Port to bind.

    ``PORT`` wins because that is what a PaaS injects *and* health-checks
    against; a gateway pinned to a different port would pass no probe.
    ``GATEWAY_PORT`` is the fallback for plain Docker, where nothing injects
    ``PORT``.
    """
    if os.getenv("PORT", "").strip():
        return _int_env("PORT", 8001)
    return _int_env("GATEWAY_PORT", 8001)


def create_listener(port: int) -> socket.socket:
    """Return a listening socket that accepts both address families if possible."""
    host = os.getenv("GATEWAY_HOST", "").strip()
    if host and host not in {"::", "0.0.0.0", ""}:
        # An operator pinned a specific interface; honour it literally.
        sock = socket.create_server((host, port), backlog=BACKLOG, reuse_port=False)
        logger.info("Listening on %s:%d", host, port)
        return sock

    if socket.has_dualstack_ipv6():
        sock = socket.create_server(("", port), family=socket.AF_INET6, dualstack_ipv6=True, backlog=BACKLOG)
        logger.info("Listening on [::]:%d (dual-stack, IPv4 included)", port)
        return sock

    sock = socket.create_server(("0.0.0.0", port), backlog=BACKLOG)
    logger.info("Listening on 0.0.0.0:%d (no IPv6 on this host)", port)
    return sock


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    port = listen_port()
    workers = _int_env("GATEWAY_WORKERS", 1)

    try:
        sock = create_listener(port)
    except OSError as exc:
        logger.error("Could not bind port %d: %s", port, exc)
        sys.exit(1)

    # `fd` rather than host/port: uvicorn must adopt the socket built above
    # instead of creating its own single-family one.
    uvicorn.run(
        os.getenv("GATEWAY_APP", DEFAULT_APP),
        fd=sock.fileno(),
        workers=workers,
        log_level=os.getenv("GATEWAY_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
