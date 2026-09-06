"""Pre-start hook that materializes ``config.yaml`` before the Gateway boots.

``python -m app.quickstart.bootstrap`` is the first thing the container
entrypoint runs. It exists because ``create_app()`` tolerates a missing
``config.yaml`` but the Gateway lifespan does not - so on a fresh one-click
deployment, with no config file and no API keys anywhere, something has to
write a valid config before uvicorn starts.

It is deliberately hard to fail: if the settings store is unreachable, it still
renders a config from ``config.example.yaml`` plus the environment, so the
Gateway boots with zero models and the operator can onboard from the web UI.
"""

from __future__ import annotations

import logging
import sys

from app.quickstart import config_builder, store

logger = logging.getLogger("app.quickstart.bootstrap")


def run() -> int:
    if not config_builder.managed_mode_enabled():
        logger.info("%s is not set; leaving config.yaml alone", config_builder.MANAGED_ENV_VAR)
        return 0

    try:
        settings = store.load()
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
