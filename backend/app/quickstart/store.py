"""Durable storage for what the operator configured through the web UI.

Two backends, picked automatically:

- **SQL** when a database URL is available (``DEER_FLOW_QUICKSTART_DB_URL``,
  else ``DATABASE_URL``). This is the one that matters for PaaS deployments:
  the container filesystem is thrown away on every redeploy, the database is
  not. One small table, created on demand, owned entirely by this fork - it is
  deliberately *not* part of the upstream Alembic chain so pulling new upstream
  revisions never conflicts with it.
- **File** at ``$DEER_FLOW_HOME/quickstart-settings.json`` otherwise, so
  ``docker compose up`` and bare local runs work with no database at all.

Everything here is synchronous SQLAlchemy on purpose: it also runs from the
pre-start bootstrap, before any event loop exists. Callers inside the Gateway
must wrap these functions in ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, delete, insert, select, update
from sqlalchemy.engine import Engine

from app.quickstart import crypto

logger = logging.getLogger(__name__)

SETTINGS_KEY = "default"
TABLE_NAME = "deerflow_quickstart_settings"

_metadata = MetaData()
_settings_table = Table(
    TABLE_NAME,
    _metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", String(64), nullable=False),
)

_engine_lock = threading.Lock()
_engine: Engine | None = None
_engine_url: str | None = None


@dataclass
class ModelSettings:
    """One model the operator enabled for a provider."""

    id: str
    label: str | None = None
    context_window: int | None = None
    max_tokens: int | None = None
    supports_vision: bool = False
    supports_thinking: bool = False


@dataclass
class LLMProviderSettings:
    """Credentials plus the enabled models for a single LLM provider."""

    provider_id: str
    api_key: str | None = None
    base_url: str | None = None
    models: list[ModelSettings] = field(default_factory=list)
    enabled: bool = True


@dataclass
class ToolProviderSettings:
    """Credentials for the provider backing one built-in tool."""

    provider_id: str
    api_key: str | None = None
    base_url: str | None = None


@dataclass
class QuickstartSettings:
    """The complete onboarding state."""

    llm_providers: list[LLMProviderSettings] = field(default_factory=list)
    search: ToolProviderSettings | None = None
    fetch: ToolProviderSettings | None = None
    # ``models[].name`` of the model the UI should preselect.
    default_model: str | None = None

    def provider(self, provider_id: str) -> LLMProviderSettings | None:
        return next((p for p in self.llm_providers if p.provider_id == provider_id), None)

    def upsert_provider(self, settings: LLMProviderSettings) -> None:
        for index, existing in enumerate(self.llm_providers):
            if existing.provider_id == settings.provider_id:
                self.llm_providers[index] = settings
                return
        self.llm_providers.append(settings)

    def remove_provider(self, provider_id: str) -> bool:
        before = len(self.llm_providers)
        self.llm_providers = [p for p in self.llm_providers if p.provider_id != provider_id]
        return len(self.llm_providers) != before


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize(settings: QuickstartSettings) -> str:
    payload: dict[str, Any] = {
        "version": 1,
        "default_model": settings.default_model,
        "llm_providers": [
            {
                **asdict(provider),
                "api_key": crypto.encrypt(provider.api_key),
            }
            for provider in settings.llm_providers
        ],
        "search": ({**asdict(settings.search), "api_key": crypto.encrypt(settings.search.api_key)} if settings.search else None),
        "fetch": ({**asdict(settings.fetch), "api_key": crypto.encrypt(settings.fetch.api_key)} if settings.fetch else None),
    }
    return json.dumps(payload, ensure_ascii=False)


def _tool_from_dict(raw: Any) -> ToolProviderSettings | None:
    if not isinstance(raw, dict) or not raw.get("provider_id"):
        return None
    return ToolProviderSettings(
        provider_id=str(raw["provider_id"]),
        api_key=crypto.decrypt(raw.get("api_key")),
        base_url=raw.get("base_url"),
    )


def _deserialize(raw_text: str) -> QuickstartSettings:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.exception("Quickstart settings are not valid JSON; starting from empty settings")
        return QuickstartSettings()
    if not isinstance(payload, dict):
        return QuickstartSettings()

    providers: list[LLMProviderSettings] = []
    for raw in payload.get("llm_providers") or []:
        if not isinstance(raw, dict) or not raw.get("provider_id"):
            continue
        models = [
            ModelSettings(
                id=str(model.get("id")),
                label=model.get("label"),
                context_window=model.get("context_window"),
                max_tokens=model.get("max_tokens"),
                supports_vision=bool(model.get("supports_vision")),
                supports_thinking=bool(model.get("supports_thinking")),
            )
            for model in raw.get("models") or []
            if isinstance(model, dict) and model.get("id")
        ]
        providers.append(
            LLMProviderSettings(
                provider_id=str(raw["provider_id"]),
                api_key=crypto.decrypt(raw.get("api_key")),
                base_url=raw.get("base_url"),
                models=models,
                enabled=bool(raw.get("enabled", True)),
            )
        )

    return QuickstartSettings(
        llm_providers=providers,
        search=_tool_from_dict(payload.get("search")),
        fetch=_tool_from_dict(payload.get("fetch")),
        default_model=payload.get("default_model"),
    )


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def normalize_database_url(url: str) -> str:
    """Return a URL SQLAlchemy's synchronous psycopg driver accepts.

    Managed Postgres add-ons hand out ``postgres://`` and ``postgresql://``
    URLs, and the app elsewhere uses the asyncpg driver. This store is
    synchronous, so it pins ``postgresql+psycopg``.
    """
    for prefix in ("postgres://", "postgresql://", "postgresql+asyncpg://", "postgresql+pg8000://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    if url.startswith("sqlite+aiosqlite://"):
        return "sqlite://" + url[len("sqlite+aiosqlite://") :]
    return url


def database_url() -> str | None:
    """The database this store should use, or ``None`` for the file backend."""
    for name in ("DEER_FLOW_QUICKSTART_DB_URL", "DATABASE_URL"):
        raw = os.getenv(name, "").strip()
        if raw:
            return normalize_database_url(raw)
    return None


def settings_file_path() -> Path:
    home = os.getenv("DEER_FLOW_HOME", "").strip()
    base = Path(home) if home else Path(os.getenv("DEER_FLOW_PROJECT_ROOT", ".")) / ".deer-flow"
    return base / "quickstart-settings.json"


def _prepare_sqlite_directory(url: str) -> None:
    """Create the parent directory of a file-backed SQLite database."""
    if not url.startswith("sqlite"):
        return
    _, _, path_part = url.partition(":///")
    if not path_part or path_part.startswith(":memory:"):
        return
    Path(path_part.split("?", 1)[0]).parent.mkdir(parents=True, exist_ok=True)


def _get_engine(url: str) -> Engine:
    global _engine, _engine_url
    with _engine_lock:
        if _engine is not None and _engine_url == url:
            return _engine
        if _engine is not None:
            _engine.dispose()
            _engine = None
            _engine_url = None
        _prepare_sqlite_directory(url)
        # Deliberately tiny: this store is read on config renders and written on
        # operator actions, not on the request hot path.
        engine = create_engine(url, pool_size=2, max_overflow=2, pool_pre_ping=True, pool_recycle=300, future=True)
        try:
            # Cache only after the schema exists. Caching a half-initialised
            # engine would leave every later call querying a missing table for
            # the rest of the process lifetime.
            _metadata.create_all(engine, tables=[_settings_table], checkfirst=True)
        except Exception:
            engine.dispose()
            raise
        _engine = engine
        _engine_url = url
        return engine


def backend_name() -> str:
    return "database" if database_url() else "file"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load() -> QuickstartSettings:
    """Read the stored settings. Never raises - an unreachable database yields
    empty settings so the Gateway still boots and the UI can explain itself."""
    url = database_url()
    if url:
        try:
            engine = _get_engine(url)
            with engine.connect() as connection:
                row = connection.execute(select(_settings_table.c.value).where(_settings_table.c.key == SETTINGS_KEY)).first()
            return _deserialize(row[0]) if row else QuickstartSettings()
        except Exception:
            logger.exception("Could not read quickstart settings from the database; falling back to the file store")

    path = settings_file_path()
    try:
        if path.is_file():
            return _deserialize(path.read_text(encoding="utf-8"))
    except OSError:
        logger.exception("Could not read %s", path)
    return QuickstartSettings()


def save(settings: QuickstartSettings) -> None:
    """Persist the settings. Raises on failure - the UI must not report success
    for a write that did not land."""
    payload = _serialize(settings)
    now = datetime.now(UTC).isoformat()
    url = database_url()
    if url:
        engine = _get_engine(url)
        with engine.begin() as connection:
            updated = connection.execute(update(_settings_table).where(_settings_table.c.key == SETTINGS_KEY).values(value=payload, updated_at=now)).rowcount
            if not updated:
                connection.execute(insert(_settings_table).values(key=SETTINGS_KEY, value=payload, updated_at=now))
        return

    path = settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def clear() -> None:
    """Drop all stored settings. Used by tests and by ``reset`` in the UI."""
    url = database_url()
    if url:
        engine = _get_engine(url)
        with engine.begin() as connection:
            connection.execute(delete(_settings_table).where(_settings_table.c.key == SETTINGS_KEY))
        return
    path = settings_file_path()
    if path.is_file():
        path.unlink()


def dispose() -> None:
    """Release the engine. Called from tests and on Gateway shutdown."""
    global _engine, _engine_url
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _engine_url = None
