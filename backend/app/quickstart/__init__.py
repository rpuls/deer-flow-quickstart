"""Quickstart: zero-env-var onboarding for one-click deployments.

This package is fork-specific (deer-flow-quickstart). It exists so a DeerFlow
instance can be deployed to a PaaS such as Railway with **no API keys set as
environment variables**, and then be onboarded entirely from the web UI:

- :mod:`catalog` describes the LLM / search / fetch providers the UI offers.
- :mod:`store` persists what the operator configured (database first, file
  fallback), so a redeploy on an ephemeral filesystem keeps the credentials.
- :mod:`config_builder` renders ``config.yaml`` from ``config.example.yaml``
  plus an overlay derived from the environment and the stored settings.
- :mod:`bootstrap` runs that render once before the Gateway process starts.
- :mod:`router` exposes ``/api/quickstart/*`` so the UI can read the catalog
  and write credentials.

Everything here is additive: the only upstream files it touches are the
Gateway app (one ``include_router`` call) and the settings dialog registration
on the frontend, which keeps future upstream merges cheap.
"""
