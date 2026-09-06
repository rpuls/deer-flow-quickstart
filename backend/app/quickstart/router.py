"""``/api/quickstart/*`` - onboarding API for the web UI.

Every write here ends the same way: persist to the settings store, then
re-render ``config.yaml``. Because ``models`` sits on the hot-reload side of the
config boundary, the next request already sees the new models - adding a
provider in the UI needs no restart.

All routes are admin-only, matching the other configuration surfaces
(``channels``, ``integrations``, ``mcp``). The store is synchronous, so every
call into it goes through ``asyncio.to_thread`` to keep the event loop clean.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import require_admin_user
from app.quickstart import catalog, config_builder, crypto, store
from app.quickstart.discovery import DiscoveryError, discover_models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quickstart", tags=["quickstart"])

_ADMIN_REQUIRED_DETAIL = "Administrator privileges are required to change provider configuration."


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ModelPayload(BaseModel):
    id: str = Field(..., min_length=1, description="Provider-side model id, e.g. gpt-4.1")
    label: str | None = None
    context_window: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    supports_vision: bool = False
    supports_thinking: bool = False


class LLMProviderPayload(BaseModel):
    # Omitted or null means "keep the stored key"; the UI never round-trips a
    # real credential, only its mask.
    api_key: str | None = None
    base_url: str | None = None
    models: list[ModelPayload] = Field(default_factory=list)
    enabled: bool = True


class ToolProviderPayload(BaseModel):
    provider_id: str = Field(..., min_length=1)
    api_key: str | None = None
    base_url: str | None = None


class CredentialProbePayload(BaseModel):
    api_key: str | None = None
    base_url: str | None = None


class DefaultModelPayload(BaseModel):
    model_name: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load() -> store.QuickstartSettings:
    return await asyncio.to_thread(store.load)


async def _persist(settings: store.QuickstartSettings) -> None:
    """Save the settings and re-render config.yaml, in that order.

    The save is the durable step; the render is what makes the change visible.
    A render failure is surfaced as a 500 because the operator's change did not
    actually take effect, even though it was stored.
    """

    def _write() -> None:
        store.save(settings)
        if config_builder.managed_mode_enabled():
            config_builder.write(settings)

    try:
        await asyncio.to_thread(_write)
    except Exception as exc:
        logger.exception("Could not apply quickstart settings")
        raise HTTPException(status_code=500, detail=f"Could not apply the change: {exc}") from exc


def _provider_view(provider: store.LLMProviderSettings) -> dict[str, Any]:
    spec = catalog.LLM_PROVIDERS_BY_ID.get(provider.provider_id)
    return {
        "provider_id": provider.provider_id,
        "label": spec.label if spec else provider.provider_id,
        "enabled": provider.enabled,
        "base_url": provider.base_url or (spec.default_base_url if spec else None),
        "api_key_masked": crypto.mask(provider.api_key),
        "has_api_key": bool(provider.api_key),
        "known_provider": spec is not None,
        "models": [
            {
                "id": model.id,
                "label": model.label,
                "name": catalog.model_entry_name(provider.provider_id, model.id),
                "context_window": model.context_window,
                "max_tokens": model.max_tokens,
                "supports_vision": model.supports_vision,
                "supports_thinking": model.supports_thinking,
            }
            for model in provider.models
        ],
    }


def _tool_view(tool: store.ToolProviderSettings | None, specs: dict[str, catalog.ToolProviderSpec]) -> dict[str, Any] | None:
    if tool is None:
        return None
    spec = specs.get(tool.provider_id)
    return {
        "provider_id": tool.provider_id,
        "label": spec.label if spec else tool.provider_id,
        "base_url": tool.base_url or (spec.default_base_url if spec else None),
        "api_key_masked": crypto.mask(tool.api_key),
        "has_api_key": bool(tool.api_key),
        "known_provider": spec is not None,
    }


def _require_spec(provider_id: str) -> catalog.LLMProviderSpec:
    spec = catalog.LLM_PROVIDERS_BY_ID.get(provider_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown LLM provider {provider_id!r}.")
    return spec


def _resolve_credentials(
    spec: catalog.LLMProviderSpec,
    submitted_key: str | None,
    submitted_base_url: str | None,
    stored: store.LLMProviderSettings | None,
) -> tuple[str | None, str | None]:
    """Merge a probe/update payload with what is already stored."""
    api_key = (submitted_key or "").strip() or (stored.api_key if stored else None)
    base_url = (submitted_base_url or "").strip() or (stored.base_url if stored else None)
    if spec.requires_api_key and not api_key:
        raise HTTPException(status_code=400, detail=f"{spec.label} needs an API key.")
    if spec.requires_base_url and not (base_url or spec.default_base_url):
        raise HTTPException(status_code=400, detail=f"{spec.label} needs a base URL.")
    return api_key, base_url


# ---------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------


@router.get("/catalog", summary="Providers the onboarding UI can offer")
async def get_catalog(request: Request) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    return catalog.catalog_payload()


@router.get("/status", summary="Onboarding status for the current deployment")
async def get_status(request: Request) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    settings = await _load()
    models = config_builder.build_models(settings)
    return {
        "managed_config": config_builder.managed_mode_enabled(),
        "settings_backend": store.backend_name(),
        "credentials_encrypted": crypto.encrypt("probe") != "probe",
        "model_count": len(models),
        "needs_onboarding": len(models) == 0,
        "default_model": settings.default_model or (models[0]["name"] if models else None),
        "providers": [_provider_view(provider) for provider in settings.llm_providers],
        "search": _tool_view(settings.search, catalog.SEARCH_PROVIDERS_BY_ID),
        "fetch": _tool_view(settings.fetch, catalog.FETCH_PROVIDERS_BY_ID),
    }


# ---------------------------------------------------------------------------
# LLM provider routes
# ---------------------------------------------------------------------------


@router.put("/llm/{provider_id}", summary="Add or update an LLM provider")
async def put_llm_provider(request: Request, provider_id: str, body: LLMProviderPayload) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    spec = _require_spec(provider_id)

    settings = await _load()
    stored = settings.provider(provider_id)
    api_key, base_url = _resolve_credentials(spec, body.api_key, body.base_url, stored)

    if not body.models:
        raise HTTPException(status_code=400, detail="Select at least one model for this provider.")

    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id=provider_id,
            api_key=api_key,
            base_url=base_url,
            enabled=body.enabled,
            models=[
                store.ModelSettings(
                    id=model.id.strip(),
                    label=model.label,
                    context_window=model.context_window,
                    max_tokens=model.max_tokens,
                    supports_vision=model.supports_vision,
                    # A provider that cannot reason cannot have a reasoning model.
                    supports_thinking=model.supports_thinking and spec.thinking != "none",
                )
                for model in body.models
                if model.id.strip()
            ],
        )
    )
    await _persist(settings)
    return await get_status(request)


@router.delete("/llm/{provider_id}", summary="Remove an LLM provider")
async def delete_llm_provider(request: Request, provider_id: str) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    settings = await _load()
    if not settings.remove_provider(provider_id):
        raise HTTPException(status_code=404, detail=f"Provider {provider_id!r} is not configured.")
    # A default pointing at a model that no longer exists would pin the UI to a
    # missing entry, so clear it and let models[0] win again.
    remaining = {entry["name"] for entry in config_builder.build_models(settings)}
    if settings.default_model not in remaining:
        settings.default_model = None
    await _persist(settings)
    return await get_status(request)


@router.post("/llm/{provider_id}/discover", summary="List the models a provider currently serves")
async def discover_provider_models(request: Request, provider_id: str, body: CredentialProbePayload) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    spec = _require_spec(provider_id)

    settings = await _load()
    api_key, base_url = _resolve_credentials(spec, body.api_key, body.base_url, settings.provider(provider_id))

    try:
        models = await discover_models(spec, api_key=api_key, base_url=base_url)
    except DiscoveryError as exc:
        # 502: the failure is upstream, not in this request. 400 would make the
        # UI blame the operator's input for, say, a provider outage.
        status_code = 400 if exc.status_code in (401, 403) else 502
        raise HTTPException(status_code=status_code, detail=exc.message) from exc

    return {"provider_id": provider_id, "models": [model.to_dict() for model in models]}


@router.post("/llm/{provider_id}/verify", summary="Check a credential without saving it")
async def verify_provider(request: Request, provider_id: str, body: CredentialProbePayload) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    spec = _require_spec(provider_id)

    settings = await _load()
    api_key, base_url = _resolve_credentials(spec, body.api_key, body.base_url, settings.provider(provider_id))

    if spec.discovery == "none":
        return {
            "ok": True,
            "verified": False,
            "detail": f"{spec.label} offers no listing endpoint, so the credential cannot be checked before the first run.",
        }

    try:
        models = await discover_models(spec, api_key=api_key, base_url=base_url)
    except DiscoveryError as exc:
        return {"ok": False, "verified": True, "detail": exc.message}
    return {"ok": True, "verified": True, "detail": f"Reached {spec.label}; {len(models)} model(s) available."}


@router.put("/default-model", summary="Pick the model the chat UI preselects")
async def put_default_model(request: Request, body: DefaultModelPayload) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    settings = await _load()
    if body.model_name:
        available = {entry["name"] for entry in config_builder.build_models(settings)}
        if body.model_name not in available:
            raise HTTPException(status_code=400, detail=f"Model {body.model_name!r} is not configured.")
    settings.default_model = body.model_name or None
    await _persist(settings)
    return await get_status(request)


# ---------------------------------------------------------------------------
# Tool provider routes
# ---------------------------------------------------------------------------


async def _put_tool_provider(
    request: Request,
    body: ToolProviderPayload,
    specs: dict[str, catalog.ToolProviderSpec],
    slot: str,
) -> dict[str, Any]:
    spec = specs.get(body.provider_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {body.provider_id!r}.")

    settings = await _load()
    previous = getattr(settings, slot)
    reuse_key = previous.api_key if previous and previous.provider_id == body.provider_id else None
    api_key = (body.api_key or "").strip() or reuse_key
    base_url = (body.base_url or "").strip() or (previous.base_url if previous and previous.provider_id == body.provider_id else None)

    if spec.requires_api_key and not api_key:
        raise HTTPException(status_code=400, detail=f"{spec.label} needs an API key.")
    if spec.requires_base_url and not (base_url or spec.default_base_url):
        raise HTTPException(status_code=400, detail=f"{spec.label} needs a URL.")

    setattr(settings, slot, store.ToolProviderSettings(provider_id=body.provider_id, api_key=api_key, base_url=base_url))
    await _persist(settings)
    return await get_status(request)


@router.put("/search", summary="Choose the web search provider")
async def put_search_provider(request: Request, body: ToolProviderPayload) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    return await _put_tool_provider(request, body, catalog.SEARCH_PROVIDERS_BY_ID, "search")


@router.delete("/search", summary="Fall back to the default web search provider")
async def delete_search_provider(request: Request) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    settings = await _load()
    settings.search = None
    await _persist(settings)
    return await get_status(request)


@router.put("/fetch", summary="Choose the web fetch provider")
async def put_fetch_provider(request: Request, body: ToolProviderPayload) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    return await _put_tool_provider(request, body, catalog.FETCH_PROVIDERS_BY_ID, "fetch")


@router.delete("/fetch", summary="Fall back to the default web fetch provider")
async def delete_fetch_provider(request: Request) -> dict[str, Any]:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    settings = await _load()
    settings.fetch = None
    await _persist(settings)
    return await get_status(request)
