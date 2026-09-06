"""Render ``config.yaml`` from the shipped example plus environment and UI state.

In managed mode (``DEER_FLOW_QUICKSTART_MANAGED_CONFIG=1``, which every image in
this repo sets) ``config.yaml`` is a **generated artifact**. The sources of
truth are:

1. ``config.example.yaml`` from the repo - the full upstream schema, including
   ``config_version``, so pulling a new upstream release cannot leave the
   deployment on an outdated config file.
2. The process environment - database URL, Redis URL, log level, and any
   provider keys the operator did set as env vars.
3. :mod:`app.quickstart.store` - everything onboarded through the web UI.

Regenerating on every change is what makes UI onboarding work without a
restart: the Gateway re-reads ``config.yaml`` whenever its content signature
changes, and ``models`` is not on the startup-only side of that boundary.

Outside managed mode nothing here runs, so ``make dev`` keeps the hand-written
``config.yaml`` upstream expects.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from app.quickstart import catalog
from app.quickstart.store import LLMProviderSettings, ModelSettings, QuickstartSettings, ToolProviderSettings

logger = logging.getLogger(__name__)

MANAGED_ENV_VAR = "DEER_FLOW_QUICKSTART_MANAGED_CONFIG"

# Providers that can be seeded straight from an environment variable. Env vars
# stay supported - they are just never *required*. A provider already present in
# the store always wins, so a UI edit is never undone by a stale env var.
ENV_SEEDED_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("google", "GEMINI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("xai", "XAI_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("moonshot", "MOONSHOT_API_KEY"),
    ("volcengine", "VOLCENGINE_API_KEY"),
    ("zai", "ZAI_API_KEY"),
    ("dashscope", "DASHSCOPE_API_KEY"),
    ("siliconflow", "SILICONFLOW_API_KEY"),
    ("together", "TOGETHER_API_KEY"),
    ("fireworks", "FIREWORKS_API_KEY"),
    ("cerebras", "CEREBRAS_API_KEY"),
    ("perplexity", "PERPLEXITY_API_KEY"),
    ("deepinfra", "DEEPINFRA_API_KEY"),
    ("nebius", "NEBIUS_API_KEY"),
    ("novita", "NOVITA_API_KEY"),
    ("minimax", "MINIMAX_API_KEY"),
    ("stepfun", "STEPFUN_API_KEY"),
    ("github_models", "GITHUB_MODELS_TOKEN"),
)

ENV_SEEDED_SEARCH: tuple[tuple[str, str], ...] = (
    ("tavily", "TAVILY_API_KEY"),
    ("brave", "BRAVE_SEARCH_API_KEY"),
    ("exa", "EXA_API_KEY"),
    ("serper", "SERPER_API_KEY"),
    ("serply", "SERPLY_API_KEY"),
    ("firecrawl", "FIRECRAWL_API_KEY"),
    ("groundroute", "GROUNDROUTE_API_KEY"),
)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def managed_mode_enabled() -> bool:
    return _env_flag(MANAGED_ENV_VAR)


def project_root() -> Path:
    root = os.getenv("DEER_FLOW_PROJECT_ROOT", "").strip()
    return Path(root).resolve() if root else Path.cwd().resolve()


def example_config_path() -> Path:
    """Locate ``config.example.yaml``, which is the schema baseline."""
    override = os.getenv("DEER_FLOW_QUICKSTART_EXAMPLE_CONFIG", "").strip()
    if override:
        return Path(override).resolve()
    root = project_root()
    for candidate in (root / "config.example.yaml", root.parent / "config.example.yaml"):
        if candidate.is_file():
            return candidate
    return root / "config.example.yaml"


def target_config_path() -> Path:
    """Where the rendered config is written.

    Matches the resolution order the harness uses, so the file we write is the
    file it reads.
    """
    configured = os.getenv("DEER_FLOW_CONFIG_PATH", "").strip()
    return Path(configured).resolve() if configured else project_root() / "config.yaml"


# ---------------------------------------------------------------------------
# Overlay construction
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge. Lists are replaced wholesale, not concatenated."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def environment_overlay() -> dict[str, Any]:
    """Infrastructure wiring derived from the platform's own env vars."""
    overlay: dict[str, Any] = {}

    database_var = next(
        (name for name in ("DEER_FLOW_DATABASE_URL", "DATABASE_URL") if os.getenv(name, "").strip()),
        None,
    )
    database_url = os.getenv(database_var, "").strip() if database_var else ""
    if database_url.startswith(("postgres://", "postgresql://", "postgresql+")):
        # `$VAR` indirection keeps the credential out of the rendered file;
        # AppConfig.resolve_env_variables expands it at load time.
        overlay["database"] = {"backend": "postgres", "postgres_url": f"${database_var}"}
    else:
        # Anything else - including a SQLite DATABASE_URL, which a few PaaS
        # add-ons hand out - keeps the file-backed default. DeerFlow's SQLite
        # mode wants a directory, not a URL, so the URL cannot be forwarded.
        if database_url:
            logger.info("%s is not a PostgreSQL URL; using the SQLite backend for the app database", database_var)
        overlay["database"] = {"backend": "sqlite", "sqlite_dir": ".deer-flow/data"}

    redis_url = _first_env("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "REDIS_URL")
    if redis_url:
        var_name = "DEER_FLOW_STREAM_BRIDGE_REDIS_URL" if os.getenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", "").strip() else "REDIS_URL"
        overlay["stream_bridge"] = {"type": "redis", "redis_url": f"${var_name}"}

    log_level = _first_env("DEER_FLOW_LOG_LEVEL", "LOG_LEVEL")
    if log_level:
        overlay["log_level"] = log_level.lower()

    # Upstream ships `allow_host_bash: false` because LocalSandboxProvider is
    # not an isolation boundary inside a shared machine. In a single-tenant
    # container the container *is* the boundary, and an agent that cannot run a
    # command is heavily degraded - so this is an explicit, documented opt-in
    # rather than a silently flipped default.
    if _env_flag("DEER_FLOW_ALLOW_HOST_BASH"):
        overlay["sandbox"] = {"allow_host_bash": True}

    return overlay


def _model_entry(spec: catalog.LLMProviderSpec, provider: LLMProviderSettings, model: ModelSettings) -> dict[str, Any]:
    """Build one ``models[]`` entry for a (provider, model) pair."""
    entry: dict[str, Any] = {
        "name": catalog.model_entry_name(spec.id, model.id),
        "display_name": f"{model.label or model.id} ({spec.label})",
        "use": spec.use,
        "model": model.id,
        **spec.extra_config,
    }

    if spec.requires_api_key or provider.api_key:
        if provider.api_key:
            entry[spec.api_key_field] = provider.api_key
    base_url = provider.base_url or spec.default_base_url
    if spec.base_url_field and base_url:
        entry[spec.base_url_field] = base_url

    if model.context_window:
        entry["context_window"] = model.context_window
    if model.max_tokens:
        entry["max_tokens"] = model.max_tokens
    entry["supports_vision"] = bool(model.supports_vision)

    if model.supports_thinking and spec.thinking != "none":
        entry["supports_thinking"] = True
        entry.update(catalog.thinking_config(spec.thinking))
    else:
        entry["supports_thinking"] = False
        # Drop toggles inherited from extra_config: advertising a disabled
        # thinking payload for a model that does not reason confuses the UI.
        entry.pop("when_thinking_enabled", None)
        entry.pop("when_thinking_disabled", None)
        entry.pop("reasoning", None)

    return entry


def build_models(settings: QuickstartSettings) -> list[dict[str, Any]]:
    """Every ``models[]`` entry implied by the stored provider settings."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for provider in settings.llm_providers:
        if not provider.enabled:
            continue
        spec = catalog.LLM_PROVIDERS_BY_ID.get(provider.provider_id)
        if spec is None:
            logger.warning("Stored provider %r is not in the catalog; skipping it", provider.provider_id)
            continue
        if spec.requires_api_key and not provider.api_key:
            logger.warning("Provider %r has no usable API key; skipping it", provider.provider_id)
            continue
        for model in provider.models:
            entry = _model_entry(spec, provider, model)
            if entry["name"] in seen:
                continue
            seen.add(entry["name"])
            entries.append(entry)

    if settings.default_model:
        # models[0] is DeerFlow's default, so ordering is the selection.
        entries.sort(key=lambda entry: entry["name"] != settings.default_model)
    return entries


def _tool_entry(spec: catalog.ToolProviderSpec, tool_settings: ToolProviderSettings) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": spec.tool_name,
        "group": "web",
        "use": spec.use,
        **spec.extra_config,
    }
    if tool_settings.api_key:
        entry[spec.api_key_field] = tool_settings.api_key
    base_url = tool_settings.base_url or spec.default_base_url
    if spec.base_url_field and base_url:
        entry[spec.base_url_field] = base_url
    return entry


def _apply_tool_override(tools: list[Any], entry: dict[str, Any]) -> list[Any]:
    """Replace the configured provider for one tool name, keeping list order."""
    replaced = False
    result: list[Any] = []
    for tool in tools:
        if isinstance(tool, dict) and tool.get("name") == entry["name"]:
            if replaced:
                continue  # duplicate names: upstream keeps the first, so drop the rest
            result.append(entry)
            replaced = True
        else:
            result.append(tool)
    if not replaced:
        result.append(entry)
    return result


def apply_settings_overlay(config: dict[str, Any], settings: QuickstartSettings) -> dict[str, Any]:
    """Fold the onboarded providers into a loaded config document."""
    config = dict(config)
    config["models"] = build_models(settings)

    tools = config.get("tools")
    tools = list(tools) if isinstance(tools, list) else []

    if settings.search:
        spec = catalog.SEARCH_PROVIDERS_BY_ID.get(settings.search.provider_id)
        if spec is not None:
            tools = _apply_tool_override(tools, _tool_entry(spec, settings.search))
    if settings.fetch:
        spec = catalog.FETCH_PROVIDERS_BY_ID.get(settings.fetch.provider_id)
        if spec is not None:
            tools = _apply_tool_override(tools, _tool_entry(spec, settings.fetch))

    config["tools"] = tools
    return config


# ---------------------------------------------------------------------------
# Environment seeding
# ---------------------------------------------------------------------------


def seed_from_environment(settings: QuickstartSettings) -> bool:
    """Adopt provider keys that were supplied as environment variables.

    Returns True when the settings changed and should be persisted. Providers
    the operator already configured through the UI are never touched, so this
    can run on every boot without fighting the UI.
    """
    changed = False

    for provider_id, env_var in ENV_SEEDED_PROVIDERS:
        api_key = os.getenv(env_var, "").strip()
        if not api_key or settings.provider(provider_id) is not None:
            continue
        spec = catalog.LLM_PROVIDERS_BY_ID.get(provider_id)
        if spec is None or not spec.presets:
            continue
        settings.upsert_provider(
            LLMProviderSettings(
                provider_id=provider_id,
                api_key=api_key,
                base_url=None,
                models=[
                    ModelSettings(
                        id=preset.id,
                        label=preset.label,
                        context_window=preset.context_window,
                        max_tokens=preset.max_tokens,
                        supports_vision=preset.supports_vision,
                        supports_thinking=preset.supports_thinking,
                    )
                    for preset in spec.presets
                ],
            )
        )
        logger.info("Seeded LLM provider %r from %s", provider_id, env_var)
        changed = True

    if settings.search is None:
        for provider_id, env_var in ENV_SEEDED_SEARCH:
            api_key = os.getenv(env_var, "").strip()
            if not api_key:
                continue
            settings.search = ToolProviderSettings(provider_id=provider_id, api_key=api_key)
            logger.info("Seeded search provider %r from %s", provider_id, env_var)
            changed = True
            break

    return changed


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def load_example_config() -> dict[str, Any]:
    path = example_config_path()
    if not path.is_file():
        raise FileNotFoundError(f"config.example.yaml not found at {path}; quickstart cannot render a config file")
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def render(settings: QuickstartSettings) -> str:
    """Produce the full YAML document for the current settings."""
    config = load_example_config()
    config = _deep_merge(config, environment_overlay())
    config = apply_settings_overlay(config, settings)

    header = (
        "# GENERATED FILE - do not edit by hand.\n"
        "#\n"
        "# Rendered by app.quickstart.config_builder from config.example.yaml plus\n"
        "# the environment and the providers onboarded in the web UI. Any manual\n"
        "# edit is lost the next time a provider is added or removed.\n"
        "#\n"
        "# To hand-manage this file instead, unset "
        f"{MANAGED_ENV_VAR}.\n\n"
    )
    body = yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False, width=120)
    return header + body


def write(settings: QuickstartSettings) -> Path:
    """Render and atomically replace the config file. Returns its path."""
    path = target_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(render(settings), encoding="utf-8")
    temporary.replace(path)
    logger.info("Rendered %s with %d model(s)", path, len(build_models(settings)))
    return path
