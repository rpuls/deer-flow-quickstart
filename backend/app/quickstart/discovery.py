"""Live model listing and credential checks against a provider's own API.

Hardcoded model ids age badly, so the onboarding UI asks the provider what it
actually serves before the operator picks anything. The same call doubles as
the credential check: a 401 here is the clearest possible "that key is wrong"
signal, and it costs no tokens - unlike a probe completion.

Providers that expose no listing endpoint fall back to the catalog presets;
:data:`app.quickstart.catalog.LLMProviderSpec.discovery` says which is which.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.quickstart.catalog import LLMProviderSpec

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_API_VERSION = "2023-06-01"
GOOGLE_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class DiscoveryError(Exception):
    """A provider call failed in a way the operator needs to see."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class DiscoveredModel:
    id: str
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label or self.id}


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _raise_for_status(response: httpx.Response, provider_label: str) -> None:
    if response.is_success:
        return
    if response.status_code in (401, 403):
        raise DiscoveryError(f"{provider_label} rejected the credential (HTTP {response.status_code}).", status_code=response.status_code)
    if response.status_code == 404:
        raise DiscoveryError(
            f"{provider_label} has no model listing at that URL (HTTP 404). Check the base URL.",
            status_code=response.status_code,
        )
    detail = response.text.strip()
    if len(detail) > 300:
        detail = detail[:300] + "..."
    raise DiscoveryError(f"{provider_label} returned HTTP {response.status_code}: {detail}", status_code=response.status_code)


def _openai_models(payload: Any) -> list[DiscoveredModel]:
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        # Some gateways return a bare list.
        items = payload if isinstance(payload, list) else []
    models: list[DiscoveredModel] = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            models.append(DiscoveredModel(id=str(item["id"]), label=item.get("name") or None))
        elif isinstance(item, str):
            models.append(DiscoveredModel(id=item))
    return models


def _anthropic_models(payload: Any) -> list[DiscoveredModel]:
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [DiscoveredModel(id=str(item["id"]), label=item.get("display_name")) for item in items if isinstance(item, dict) and item.get("id")]


def _google_models(payload: Any) -> list[DiscoveredModel]:
    items = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    models: list[DiscoveredModel] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        methods = item.get("supportedGenerationMethods")
        if isinstance(methods, list) and "generateContent" not in methods:
            continue
        # The API returns "models/gemini-2.5-pro"; config.yaml wants the bare id.
        model_id = str(item["name"]).removeprefix("models/")
        models.append(DiscoveredModel(id=model_id, label=item.get("displayName")))
    return models


def _ollama_models(payload: Any) -> list[DiscoveredModel]:
    items = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [DiscoveredModel(id=str(item["name"])) for item in items if isinstance(item, dict) and item.get("name")]


async def discover_models(spec: LLMProviderSpec, *, api_key: str | None, base_url: str | None) -> list[DiscoveredModel]:
    """List the models a provider currently serves for this credential.

    Raises :class:`DiscoveryError` with an operator-readable message on any
    failure, including a missing endpoint or an unusable credential.
    """
    if spec.discovery == "none":
        raise DiscoveryError(f"{spec.label} does not publish a model list; pick a preset or type a model id.")

    resolved_base = (base_url or spec.default_base_url or "").strip()

    if spec.discovery == "anthropic":
        url = _endpoint(resolved_base or ANTHROPIC_DEFAULT_BASE_URL, "/v1/models")
        headers = {"x-api-key": api_key or "", "anthropic-version": ANTHROPIC_API_VERSION}
        params: dict[str, str] = {"limit": "100"}
        parse = _anthropic_models
    elif spec.discovery == "google":
        url = _endpoint(resolved_base or GOOGLE_DEFAULT_BASE_URL, "/models")
        headers = {"x-goog-api-key": api_key or ""}
        params = {"pageSize": "200"}
        parse = _google_models
    elif spec.discovery == "ollama":
        if not resolved_base:
            raise DiscoveryError("Set the Ollama server URL first.")
        url = _endpoint(resolved_base, "/api/tags")
        headers = {}
        params = {}
        parse = _ollama_models
    else:
        if not resolved_base:
            raise DiscoveryError(f"{spec.label} needs a base URL before its models can be listed.")
        url = _endpoint(resolved_base, "/models")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        params = {}
        parse = _openai_models

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.TimeoutException as exc:
        raise DiscoveryError(f"{spec.label} did not respond within {REQUEST_TIMEOUT.read:.0f}s.") from exc
    except httpx.HTTPError as exc:
        raise DiscoveryError(f"Could not reach {spec.label}: {exc}") from exc

    _raise_for_status(response, spec.label)

    try:
        payload = response.json()
    except ValueError as exc:
        raise DiscoveryError(f"{spec.label} returned a non-JSON model list.") from exc

    models = parse(payload)
    models.sort(key=lambda model: model.id)
    return models
