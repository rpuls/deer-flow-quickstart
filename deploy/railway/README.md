# Deploying DeerFlow on Railway

This directory holds everything the one-click deployment needs: two Dockerfiles,
their build-context ignore lists, the container entrypoints, and a Railway
config file per service.

The deployment is designed around one rule: **no API key is ever required to
deploy.** Bring the app up first, create the admin account in the browser, then
paste provider credentials into Settings → Providers. They are stored in
Postgres (encrypted), so they outlive every redeploy.

## Topology

| Railway service | Built from                          | Public | Notes                                                      |
| --------------- | ----------------------------------- | ------ | ---------------------------------------------------------- |
| `web`           | `deploy/railway/Dockerfile.web`      | yes    | Next.js UI; proxies `/api/*` to the gateway                |
| `gateway`       | `deploy/railway/Dockerfile.gateway`  | no     | FastAPI + agent runtime; renders `config.yaml` at start    |
| `Postgres`      | Railway add-on                       | no     | threads, checkpoints, users, and the provider credentials  |

Redis is optional. Add it only when you raise `GATEWAY_WORKERS` above 1; a
single worker uses the in-process stream bridge.

## Setting it up

1. **Create the project** and add a **Postgres** database.

2. **Add the `gateway` service** from this repository.
   - Leave the root directory at the repository root; the image builds with the
     whole repo as its context.
   - Do **not** give it a public domain.
   - Variables:

     | Variable                      | Value                                             |
     | ----------------------------- | ------------------------------------------------- |
     | `DATABASE_URL`                | `${{Postgres.DATABASE_URL}}`                      |
     | `DEER_FLOW_QUICKSTART_SECRET` | a long random string — encrypts stored API keys   |
     | `GATEWAY_CORS_ORIGINS`        | `https://${{web.RAILWAY_PUBLIC_DOMAIN}}`          |
     | `PORT`                        | `8001`                                            |
     | `RAILWAY_DOCKERFILE_PATH`     | `deploy/railway/Dockerfile.gateway`               |

     Pin `PORT` explicitly: Railway health-checks the port it believes the
     service listens on, and the `web` service below targets `:8001`. Leaving
     it to be inferred is the one way this deployment silently fails to become
     healthy.

3. **Add the `web` service** from the same repository.
   - Leave the root directory at the repository root.
   - Generate a public domain for it. This is the URL people will open.
   - Variables:

     | Variable                              | Value                                                     |
     | ------------------------------------- | --------------------------------------------------------- |
     | `DEER_FLOW_INTERNAL_GATEWAY_BASE_URL` | `http://${{gateway.RAILWAY_PRIVATE_DOMAIN}}:8001`         |
     | `DEER_FLOW_TRUSTED_ORIGINS`           | `https://${{web.RAILWAY_PUBLIC_DOMAIN}}`                  |
     | `RAILWAY_DOCKERFILE_PATH`             | `deploy/railway/Dockerfile.web`                           |

4. **Deploy**, open the public domain, and create the admin account.

5. **Settings → Providers**: paste a key for any provider you already pay for.
   The models appear immediately — the Gateway re-reads its config on the next
   request, so there is nothing to restart.

### Why those two variables matter

`GATEWAY_CORS_ORIGINS` — the browser talks to the `web` domain, so the Gateway
sees an `Origin` header that does not match its own host. Auth POSTs are
rejected as cross-site until that origin is listed.

`DEER_FLOW_INTERNAL_GATEWAY_BASE_URL` — Next.js freezes its `/api/*` proxy
target into the build output, so the image is built against a sentinel host and
`web-entrypoint.sh` substitutes this value at container start. Railway's private
network is IPv6-only, which is why the gateway listens dual-stack
(`app.quickstart.serve`) rather than on `0.0.0.0`.

## Optional variables

| Variable                            | Effect                                                                                   |
| ----------------------------------- | ---------------------------------------------------------------------------------------- |
| `REDIS_URL`                         | Switches the SSE stream bridge to Redis. Required before `GATEWAY_WORKERS` > 1.           |
| `GATEWAY_WORKERS`                   | Uvicorn worker count. Leave at 1 unless Redis is configured.                              |
| `LOG_LEVEL`                         | `debug`, `info`, `warning`, `error`.                                                      |
| `DEER_FLOW_ALLOW_HOST_BASH`         | `1` lets the agent run shell commands inside the gateway container. Off by default; see Security notes. |
| `UV_EXTRAS`                         | Build arg for extra Python extras, e.g. `postgres,redis,ollama`. Defaults to `postgres,redis`. |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, … | Optional. A key found in the environment seeds that provider on first boot; the UI wins from then on. |
| `TAVILY_API_KEY`, `BRAVE_SEARCH_API_KEY`, … | Same, for the web search provider. Search works with no key at all (DuckDuckGo). |

## Publishing / updating the Railway template

Per-service settings (not environment variables):

| Service         | Root Directory | Public domain | Volume                     |
| --------------- | -------------- | ------------- | -------------------------- |
| Web Interface   | `/`            | yes           | -                          |
| Python-backend  | `/`            | **no**        | `/app/.deer-flow`          |
| Postgres        | -              | no            | `/var/lib/postgresql/data` |

Root Directory must be the repository root: both Dockerfiles build with the
repo root as their context. The volume on the backend holds per-thread uploads,
agent workspaces, generated outputs and `memory.json`; conversations themselves
live in Postgres and survive without it.

Which Dockerfile each service builds is selected by the `RAILWAY_DOCKERFILE_PATH`
variable in the blocks below. Railway's template editor has no field for a
config-as-code path, and there is no environment variable for one, so
`gateway.json` / `web.json` in this directory are only read when a service is
created from the dashboard with *Config as code* pointed at them. The images do
not depend on them.

Health check paths are therefore optional here. If the template editor exposes
one, use `/healthz` for the web service and `/health/ready` for the backend;
without them Railway simply routes traffic as soon as the container starts.

Paste these into Railway's raw variable editor, replacing what is there.

**Web Interface**

```
PORT="8080"
PUBLIC_URL="https://${{RAILWAY_PUBLIC_DOMAIN}}"
GITHUB_OAUTH_TOKEN=""
RAILWAY_DOCKERFILE_PATH="deploy/railway/Dockerfile.web"
DEER_FLOW_INTERNAL_GATEWAY_BASE_URL="http://${{Python-backend.RAILWAY_PRIVATE_DOMAIN}}:8001"
DEER_FLOW_TRUSTED_ORIGINS="https://${{RAILWAY_PUBLIC_DOMAIN}}"
```

No `NEXT_PUBLIC_*` variable may be set. Leaving them unset is what keeps the
browser on one origin; a cross-origin API base drops the auth cookies.

**Python-backend**

```
PORT="8001"
RAILWAY_DOCKERFILE_PATH="deploy/railway/Dockerfile.gateway"
DATABASE_URL="${{Postgres.DATABASE_URL}}"
GATEWAY_CORS_ORIGINS="${{\"Web Interface\".PUBLIC_URL}}"
DEER_FLOW_QUICKSTART_SECRET="${{ secret(32, \"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ\") }}"
```

`PORT` must stay `8001` because the frontend targets that port over the private
network. `GATEWAY_CORS_ORIGINS` is not cosmetic: without it the Gateway rejects
login as a cross-site request.

Postgres needs no changes.

### Migrating from the 1.x template

This is a breaking upgrade. The new schema is created alongside the old
`research_projects` tables so an in-place redeploy will not crash, but old
research rows are orphaned and `BASIC_MODEL__*` / `SEARCH_API` /
`RESEARCH_DB_*` / `ALLOWED_ORIGINS` are ignored. Delete them, and tell existing
users to re-add their model provider under Settings -> Providers.

One trap: the 1.x template built the frontend from a `web/` folder, so its web
service has **Root Directory `/web`**. That is a per-service setting, not a
variable, so replacing the variable block alone leaves the build failing at
`unpacking archive` with `lstat .../web: no such file or directory`. Set both
services back to `/`.

## Security notes

- Treat the deployment as trusted-tenant: complete the admin setup immediately
  after the first deploy, before sharing the URL.
- Shell execution is **off** by default (`sandbox.allow_host_bash: false`), which
  is upstream's default because `LocalSandboxProvider` is not an isolation
  boundary. In a single-tenant container the container is the boundary, so
  `DEER_FLOW_ALLOW_HOST_BASH=1` is a reasonable opt-in — and a significant
  capability upgrade for the agent. Do not set it on a deployment whose users
  you would not give a shell to.
- `DEER_FLOW_QUICKSTART_SECRET` encrypts stored provider keys. Losing or
  changing it does not break the app, but every provider has to be re-entered.
- The gateway service must stay private. It has no auth exemption of its own —
  it simply has no reason to be reachable from the internet.

## Testing the same stack locally

`docker/docker-compose.quickstart.yaml` runs the identical images with a local
Postgres:

```bash
docker compose -f docker/docker-compose.quickstart.yaml up -d --build
open http://localhost:3000
```
