"""Pre-start hook that materializes ``config.yaml`` before the Gateway boots.

``python -m app.quickstart.bootstrap`` is the first thing the container
entrypoint runs. It exists because ``create_app()`` tolerates a missing
``config.yaml`` but the Gateway lifespan does not - so on a fresh one-click
deployment, with no config file and no API keys anywhere, something has to
write a valid config before uvicorn starts.

Failure handling is asymmetric on purpose. With no database configured there is
nothing to lose, so a bad read still renders a config from
``config.example.yaml`` plus the environment and the operator onboards from the
web UI. With a database configured the stored providers *are* the deployment's
configuration, and the container filesystem is discarded on every redeploy - so
rendering an empty config because Postgres was slow to accept connections would
hand back a deployment that looks healthy and has no models. That case waits,
and then fails loudly so the platform restarts us.
"""

from __future__ import annotations

import logging
import os
import sys

from app.quickstart import config_builder, store

logger = logging.getLogger("app.quickstart.bootstrap")

DB_WAIT_ENV = "DEER_FLOW_QUICKSTART_DB_WAIT_SECONDS"
DEFAULT_DB_WAIT_SECONDS = 60.0


def db_wait_seconds() -> float:
    """How long to wait for a configured database before giving up."""
    raw = os.getenv(DB_WAIT_ENV, "").strip()
    if not raw:
        return DEFAULT_DB_WAIT_SECONDS
    try:
        return max(float(raw), 0.0)
    except ValueError:
        logger.warning("%s=%r is not a number; using %.0fs", DB_WAIT_ENV, raw, DEFAULT_DB_WAIT_SECONDS)
        return DEFAULT_DB_WAIT_SECONDS


def run() -> int:
    if not config_builder.managed_mode_enabled():
        logger.info("%s is not set; leaving config.yaml alone", config_builder.MANAGED_ENV_VAR)
        return 0

    if not store.wait_until_available(db_wait_seconds()):
        logger.error(
            "The configured database never became available. Refusing to render a config with no providers - restarting is better than a deployment that looks healthy and cannot chat.",
        )
        return 1

    try:
        settings = store.load_strict()
    except store.StoreUnavailableError:
        logger.exception("Could not read the settings store; refusing to render a config that would drop every provider")
        return 1
    except Exception:
        logger.exception("Could not load quickstart settings; continuing with empty settings")
        settings = store.QuickstartSettings()

    try:
        if config_builder.seed_from_environment(settings):
            store.save(settings)
    except Exception:
        # Seeding is a convenience. A store that rejects the write must not stop
        # the deployment - the rendered config below still carries the seeded
        # providers for this process.
        logger.exception("Could not persist providers seeded from the environment")

    try:
        path = config_builder.write(settings)
    except Exception:
        logger.exception("Could not render config.yaml")
        return 1

    model_count = len(config_builder.build_models(settings))
    logger.info(
        "Quickstart bootstrap complete: %s (%d model(s), settings store: %s)",
        path,
        model_count,
        store.backend_name(),
    )
    if model_count == 0:
        logger.warning("No LLM providers are configured yet. Open the app and add one under Settings -> Providers.")
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    sys.exit(run())


if __name__ == "__main__":
    main()
