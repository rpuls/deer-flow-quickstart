"""Tests for the fork's zero-env-var onboarding layer (``app.quickstart``).

The contract these pin down is the one a one-click deployment depends on:

* a deployment with no credentials anywhere still renders a valid config;
* a credential added through the API lands in ``config.yaml`` in the exact
  shape the model factory expects for that provider family;
* credentials survive a restart, and are not readable from the stored row;
* environment variables still work, and never fight the UI.

They run without a database, a network, or the agent runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.quickstart import catalog, config_builder, crypto, store

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def quickstart_env(tmp_path, monkeypatch):
    """Point the store and the renderer at a throwaway directory."""
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(REPO_ROOT))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("DEER_FLOW_QUICKSTART_MANAGED_CONFIG", "1")
    monkeypatch.setenv("DEER_FLOW_QUICKSTART_SECRET", "unit-test-secret")
    monkeypatch.delenv("DEER_FLOW_QUICKSTART_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    for _, env_var in (*config_builder.ENV_SEEDED_PROVIDERS, *config_builder.ENV_SEEDED_SEARCH):
        monkeypatch.delenv(env_var, raising=False)
    store.dispose()
    yield tmp_path
    store.dispose()


def _model_named(document: dict, name: str) -> dict:
    return next(entry for entry in document["models"] if entry["name"] == name)


def _render(settings: store.QuickstartSettings) -> dict:
    return yaml.safe_load(config_builder.render(settings))


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_catalog_ids_are_unique_and_serializable():
    for group in (catalog.LLM_PROVIDERS, catalog.SEARCH_PROVIDERS, catalog.FETCH_PROVIDERS):
        ids = [spec.id for spec in group]
        assert len(ids) == len(set(ids)), f"duplicate provider id in {ids}"
    # The catalog crosses the wire as JSON on every settings page load.
    json.dumps(catalog.catalog_payload())


def test_catalog_specs_are_internally_consistent():
    for spec in catalog.LLM_PROVIDERS:
        assert ":" in spec.use, f"{spec.id}: `use` must be module:Class"
        if spec.requires_base_url:
            assert spec.base_url_field, f"{spec.id}: requires a base URL but declares no field for it"
        if not spec.requires_base_url and spec.base_url_field and spec.default_base_url is None:
            # Anthropic is the deliberate exception: its SDK knows its own
            # endpoint, so the field exists only as an override.
            assert spec.id == "anthropic", f"{spec.id}: optional base URL with no default"


def test_model_entry_names_are_unique_per_provider_and_model():
    assert catalog.model_entry_name("openrouter", "deepseek/deepseek-chat") != catalog.model_entry_name("deepseek", "deepseek-chat")
    assert catalog.model_entry_name("openai", "gpt-4.1") == "openai-gpt-4-1"


# ---------------------------------------------------------------------------
# Credential storage
# ---------------------------------------------------------------------------


def test_credentials_round_trip_and_are_encrypted_at_rest(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id="openai",
            api_key="sk-super-secret-value",
            models=[store.ModelSettings(id="gpt-4.1", label="GPT-4.1")],
        )
    )
    store.save(settings)

    raw = store.settings_file_path().read_text(encoding="utf-8")
    assert "sk-super-secret-value" not in raw
    assert store.load().provider("openai").api_key == "sk-super-secret-value"


def test_unreadable_ciphertext_is_reported_as_missing(quickstart_env, monkeypatch):
    settings = store.QuickstartSettings()
    settings.upsert_provider(store.LLMProviderSettings(provider_id="openai", api_key="sk-rotated-away"))
    store.save(settings)

    # A rotated secret must degrade to "re-enter the key", not crash the boot.
    monkeypatch.setenv("DEER_FLOW_QUICKSTART_SECRET", "a-different-secret")
    assert store.load().provider("openai").api_key is None


def test_masking_never_reveals_more_than_the_last_four():
    assert crypto.mask("sk-abcdefghijklmnop") == "********mnop"
    assert crypto.mask("abc") == "***"
    assert crypto.mask(None) is None


def test_corrupt_settings_do_not_break_loading(quickstart_env):
    path = store.settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert store.load().llm_providers == []


# ---------------------------------------------------------------------------
# Config rendering
# ---------------------------------------------------------------------------


def test_empty_settings_still_render_a_valid_config(quickstart_env):
    document = _render(store.QuickstartSettings())
    # config_version comes from config.example.yaml, so an upstream bump can
    # never leave a generated config behind.
    assert document["config_version"] == yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))["config_version"]
    assert document["models"] == []
    # DuckDuckGo search survives with no key, which is what makes a
    # credential-free first boot useful at all.
    assert any(tool.get("name") == "web_search" for tool in document["tools"])


def test_anthropic_entry_carries_the_anthropic_thinking_shape(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id="anthropic",
            api_key="sk-ant-key",
            models=[store.ModelSettings(id="claude-sonnet-4-5", label="Sonnet", supports_thinking=True, max_tokens=16000)],
        )
    )
    entry = _model_named(_render(settings), "anthropic-claude-sonnet-4-5")

    assert entry["use"] == "langchain_anthropic:ChatAnthropic"
    assert entry["api_key"] == "sk-ant-key"
    assert entry["supports_thinking"] is True
    # The Anthropic API rejects thinking without a budget, so the shape matters.
    assert entry["when_thinking_enabled"]["thinking"]["budget_tokens"] == 4096
    assert entry["when_thinking_enabled"]["thinking"]["budget_tokens"] < entry["max_tokens"]


def test_deepseek_entry_uses_api_base_not_base_url(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id="deepseek",
            api_key="sk-ds",
            models=[store.ModelSettings(id="deepseek-chat")],
        )
    )
    entry = _model_named(_render(settings), "deepseek-deepseek-chat")

    # ChatDeepSeek declares `api_base`; sending `base_url` would be silently
    # diverted into model_kwargs and blow up at request time.
    assert entry["api_base"] == "https://api.deepseek.com/v1"
    assert "base_url" not in entry


def test_google_entry_uses_the_gemini_api_key_field(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id="google",
            api_key="gemini-key",
            models=[store.ModelSettings(id="gemini-2.5-pro")],
        )
    )
    entry = _model_named(_render(settings), "google-gemini-2-5-pro")

    assert entry["gemini_api_key"] == "gemini-key"
    assert "api_key" not in entry


def test_non_thinking_model_does_not_advertise_thinking_toggles(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id="deepseek",
            api_key="sk-ds",
            models=[store.ModelSettings(id="deepseek-chat", supports_thinking=False)],
        )
    )
    entry = _model_named(_render(settings), "deepseek-deepseek-chat")

    assert entry["supports_thinking"] is False
    assert "when_thinking_enabled" not in entry
    assert "when_thinking_disabled" not in entry


def test_provider_without_a_key_is_skipped(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(store.LLMProviderSettings(provider_id="openai", api_key=None, models=[store.ModelSettings(id="gpt-4.1")]))
    assert config_builder.build_models(settings) == []


def test_disabled_provider_contributes_no_models(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id="openai",
            api_key="sk-x",
            enabled=False,
            models=[store.ModelSettings(id="gpt-4.1")],
        )
    )
    assert config_builder.build_models(settings) == []


def test_default_model_is_ordered_first(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id="openai",
            api_key="sk-x",
            models=[store.ModelSettings(id="gpt-4.1"), store.ModelSettings(id="gpt-4o")],
        )
    )
    settings.default_model = "openai-gpt-4o"
    # DeerFlow treats models[0] as the default, so ordering is the mechanism.
    assert config_builder.build_models(settings)[0]["name"] == "openai-gpt-4o"


def test_search_override_replaces_the_default_tool_exactly_once(quickstart_env):
    settings = store.QuickstartSettings()
    settings.search = store.ToolProviderSettings(provider_id="tavily", api_key="tvly-key")
    document = _render(settings)

    search_tools = [tool for tool in document["tools"] if tool.get("name") == "web_search"]
    assert len(search_tools) == 1
    assert search_tools[0]["use"] == "deerflow.community.tavily.tools:web_search_tool"
    assert search_tools[0]["api_key"] == "tvly-key"


def test_self_hosted_search_provider_carries_its_url(quickstart_env):
    settings = store.QuickstartSettings()
    settings.search = store.ToolProviderSettings(provider_id="searxng", base_url="http://searxng.internal:8080")
    search_tool = next(tool for tool in _render(settings)["tools"] if tool.get("name") == "web_search")

    assert search_tool["base_url"] == "http://searxng.internal:8080"
    assert "api_key" not in search_tool


# ---------------------------------------------------------------------------
# Environment overlay
# ---------------------------------------------------------------------------


def test_postgres_url_becomes_an_indirect_reference(quickstart_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/deerflow")
    overlay = config_builder.environment_overlay()

    assert overlay["database"]["backend"] == "postgres"
    # The rendered file must not contain the password itself.
    assert overlay["database"]["postgres_url"] == "$DATABASE_URL"


def test_non_postgres_database_url_falls_back_to_sqlite(quickstart_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/app.db")
    assert config_builder.environment_overlay()["database"]["backend"] == "sqlite"


def test_redis_url_switches_the_stream_bridge(quickstart_env, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")
    overlay = config_builder.environment_overlay()

    assert overlay["stream_bridge"] == {"type": "redis", "redis_url": "$REDIS_URL"}


def test_no_redis_leaves_the_default_memory_bridge(quickstart_env):
    assert "stream_bridge" not in config_builder.environment_overlay()


def test_host_bash_stays_off_unless_explicitly_enabled(quickstart_env):
    document = _render(store.QuickstartSettings())
    assert document["sandbox"]["allow_host_bash"] is False


def test_host_bash_can_be_opted_into(quickstart_env, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_ALLOW_HOST_BASH", "1")
    document = _render(store.QuickstartSettings())

    assert document["sandbox"]["allow_host_bash"] is True
    # The overlay must not clobber the rest of the sandbox section.
    assert document["sandbox"]["use"] == "deerflow.sandbox.local:LocalSandboxProvider"


# ---------------------------------------------------------------------------
# Environment seeding
# ---------------------------------------------------------------------------


def test_environment_keys_seed_providers(quickstart_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-from-env")
    settings = store.QuickstartSettings()

    assert config_builder.seed_from_environment(settings) is True
    assert settings.provider("openai").api_key == "sk-from-env"
    assert settings.provider("openai").models, "seeding must select the provider's presets"
    assert settings.search.provider_id == "tavily"


def test_seeding_never_overwrites_what_the_ui_configured(quickstart_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    settings = store.QuickstartSettings()
    settings.upsert_provider(store.LLMProviderSettings(provider_id="openai", api_key="sk-from-ui", models=[store.ModelSettings(id="gpt-4o")]))

    assert config_builder.seed_from_environment(settings) is False
    assert settings.provider("openai").api_key == "sk-from-ui"


def test_seeding_is_idempotent(quickstart_env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    settings = store.QuickstartSettings()

    config_builder.seed_from_environment(settings)
    assert config_builder.seed_from_environment(settings) is False
    assert len(settings.llm_providers) == 1


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_writes_a_config_for_a_credential_free_deployment(quickstart_env):
    from app.quickstart import bootstrap

    assert bootstrap.run() == 0

    document = yaml.safe_load(config_builder.target_config_path().read_text(encoding="utf-8"))
    assert document["models"] == []
    assert document["sandbox"]["use"] == "deerflow.sandbox.local:LocalSandboxProvider"


def test_bootstrap_is_a_no_op_outside_managed_mode(quickstart_env, monkeypatch):
    from app.quickstart import bootstrap

    monkeypatch.delenv("DEER_FLOW_QUICKSTART_MANAGED_CONFIG")
    assert bootstrap.run() == 0
    assert not config_builder.target_config_path().exists()


# ---------------------------------------------------------------------------
# Startup resilience
# ---------------------------------------------------------------------------


def _unreachable(_url):
    raise OSError("connection refused")


def test_load_degrades_quietly_but_load_strict_reports_an_unreachable_database(quickstart_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/deerflow")
    monkeypatch.setattr(store, "_get_engine", _unreachable)

    # A request must never 500 because the store blinked...
    assert store.load() == store.QuickstartSettings()
    # ...but the pre-start renderer has to tell "no providers are configured"
    # apart from "the providers could not be read".
    with pytest.raises(store.StoreUnavailableError):
        store.load_strict()


def test_load_strict_reads_the_file_store_when_no_database_is_configured(quickstart_env):
    settings = store.QuickstartSettings()
    settings.upsert_provider(
        store.LLMProviderSettings(
            provider_id="openai",
            api_key="sk-file-backed",
            models=[store.ModelSettings(id="gpt-4.1")],
        )
    )
    store.save(settings)

    assert store.load_strict().provider("openai").api_key == "sk-file-backed"


def test_wait_until_available_is_a_no_op_without_a_database(quickstart_env):
    assert store.wait_until_available(0.0) is True


def test_wait_until_available_gives_up_on_a_database_that_never_answers(quickstart_env, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/deerflow")
    monkeypatch.setattr(store, "_get_engine", _unreachable)

    assert store.wait_until_available(0.0) is False


def test_wait_until_available_retries_a_database_that_is_still_starting(quickstart_env, monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_QUICKSTART_DB_URL", f"sqlite:///{(tmp_path / 'settings.db').as_posix()}")
    real_get_engine = store._get_engine
    attempts = {"count": 0}

    def flaky(url):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise OSError("the database system is starting up")
        return real_get_engine(url)

    monkeypatch.setattr(store, "_get_engine", flaky)

    assert store.wait_until_available(30.0, interval=0.01) is True
    assert attempts["count"] == 3


def test_bootstrap_fails_rather_than_publish_a_config_that_lost_every_provider(quickstart_env, monkeypatch):
    from app.quickstart import bootstrap

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/deerflow")
    monkeypatch.setenv(bootstrap.DB_WAIT_ENV, "0")
    monkeypatch.setattr(store, "_get_engine", _unreachable)

    assert bootstrap.run() == 1
    # The half that matters: a deployment that cannot read its providers must
    # not boot advertising none of them.
    assert not config_builder.target_config_path().exists()


def test_db_wait_seconds_survives_a_nonsense_value(quickstart_env, monkeypatch):
    from app.quickstart import bootstrap

    monkeypatch.setenv(bootstrap.DB_WAIT_ENV, "soon")
    assert bootstrap.db_wait_seconds() == bootstrap.DEFAULT_DB_WAIT_SECONDS

    monkeypatch.setenv(bootstrap.DB_WAIT_ENV, "5")
    assert bootstrap.db_wait_seconds() == 5.0
