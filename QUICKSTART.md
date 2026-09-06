# deer-flow-quickstart

A deployment-focused fork of [DeerFlow](https://github.com/bytedance/deer-flow) 2.x.

Upstream DeerFlow is configured through a `config.yaml` on disk and `$ENV_VAR`
references for every credential. That is the right design for a repository you
clone and edit — and the wrong one for a platform where you click *Deploy* and
get a URL. This fork closes that gap without changing how DeerFlow works.

## What this fork adds

**Deploy first, add keys later.** The app boots with zero credentials. Web
search still works (DuckDuckGo needs no key), so the only thing missing is a
model — and you add that from the UI.

**A provider catalog in the app.** 31 LLM providers, 10 web-search providers and
4 page-fetch providers, each with the right LangChain class, endpoint,
credential field name and thinking/vision flags already filled in. Includes the
ones most people already pay for: OpenAI, Anthropic, Google, OpenRouter, Groq,
xAI, Mistral, DeepSeek, Moonshot, Together, Fireworks, Cerebras, Perplexity,
Azure OpenAI, GitHub Models, plus local Ollama, LM Studio and vLLM, plus a
generic "any OpenAI-compatible endpoint" entry.

**Live model discovery.** Hardcoded model ids rot. The Providers page asks your
provider what it currently serves and lists that, so a new model release is
usable the day it ships without waiting on this repo.

**Credentials that survive a redeploy.** They are encrypted with
`DEER_FLOW_QUICKSTART_SECRET` and stored in the same Postgres the app already
uses — not on the container filesystem, which most platforms throw away.

**No restart when you change providers.** DeerFlow re-reads `config.yaml` when
its content changes, and `models` is on the hot-reload side of that boundary. A
saved provider is usable on the next request.

Everything else is upstream, untouched: the agent runtime, sandbox, subagents,
memory, skills, MCP, IM channels, and the whole UI.

## Deploy on Railway

See **[deploy/railway/README.md](./deploy/railway/README.md)** for the full
walkthrough. The short version: a Postgres add-on, a private `gateway` service
and a public `web` service, three environment variables, no API keys.

## Run it locally

```bash
docker compose -f docker/docker-compose.quickstart.yaml up -d --build
open http://localhost:3000
```

Same images, same entrypoints, same start-up path as the cloud deployment, with
a local Postgres. Create the admin account, then open **Settings → Providers**.

To develop against the upstream workflow instead (hand-written `config.yaml`,
hot reload, `make dev`), follow [the upstream README](./README.md) — nothing in
this fork interferes with it. The generated-config behaviour is opt-in via
`DEER_FLOW_QUICKSTART_MANAGED_CONFIG=1`, which only the images here set.

## How it works

```
config.example.yaml ─┐
environment  ────────┼──> app.quickstart.config_builder ──> config.yaml ──> Gateway
settings store ──────┘                                          ▲
      ▲                                                          │
      └── /api/quickstart/*  ←── Settings → Providers  ───────────┘ (hot reload)
```

- **`backend/app/quickstart/catalog.py`** — the provider list and how each one
  maps onto a `models[]` entry.
- **`backend/app/quickstart/store.py`** — durable settings. Postgres when a
  `DATABASE_URL` exists, a JSON file otherwise.
- **`backend/app/quickstart/config_builder.py`** — renders `config.yaml` from
  `config.example.yaml` plus the environment plus the store. Deriving from the
  example means an upstream schema bump (including `config_version`) is picked
  up automatically.
- **`backend/app/quickstart/bootstrap.py`** — runs once before uvicorn starts.
- **`backend/app/quickstart/router.py`** — the admin-only `/api/quickstart/*` API.
- **`backend/app/quickstart/serve.py`** — dual-stack listener, because Railway's
  private network is IPv6-only and asyncio's `::` bind is IPv6-only too.
- **`frontend/src/components/workspace/settings/providers-settings-page.tsx`** —
  the Providers page.

Environment variables still work. Any provider key found in the environment
seeds that provider on first boot; anything configured in the UI wins from then
on, so a stale env var can never undo a UI change.

## Tests

```bash
# Backend unit tests for the onboarding layer
cd backend && uv run pytest tests/test_quickstart.py

# Frontend component/flow tests (mocked backend, fast)
cd frontend && pnpm exec playwright test tests/e2e/quickstart-providers.spec.ts

# Full-stack onboarding against a real Gateway + Postgres
make quickstart-up
make quickstart-e2e
```

The full-stack suite drives a real deployment: it creates the admin account,
adds a provider through the UI, and asserts the model shows up in `/api/models`
without a restart. It needs no provider credentials — the key it uses is a
placeholder, because nothing in the suite calls a model.

## Keeping up with upstream

The fork is a merge, not a rewrite. Fork-owned code lives in paths upstream does
not use:

```
backend/app/quickstart/**      deploy/railway/**
frontend/src/core/quickstart/**    docker/docker-compose.quickstart.yaml
frontend/src/components/workspace/settings/providers-settings-page.tsx
frontend/src/components/workspace/provider-setup-banner.tsx
frontend/src/app/healthz/route.ts
backend/tests/test_quickstart.py
frontend/tests/e2e/quickstart-providers.spec.ts
frontend/tests/e2e-quickstart/**
```

Upstream files touched, and only barely:

| File                                   | Change                                            |
| -------------------------------------- | ------------------------------------------------- |
| `backend/app/gateway/app.py`            | one import, one `include_router`                  |
| `frontend/.../settings/settings-dialog.tsx` | registers the Providers page                  |
| `frontend/.../workspace-settings-deep-link.tsx` | allows `?settings=providers`              |
| `frontend/src/app/workspace/workspace-content.tsx` | renders the onboarding banner          |
| `frontend/src/core/i18n/locales/*`      | one section label, in `en` and `zh`               |
| `README.md`                             | the fork callout at the top                        |

So `git merge upstream/main` should stay cheap.
