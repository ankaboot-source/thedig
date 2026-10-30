# AGENTS.md — TheDig

## 1. What this repo is

TheDig is an enrichment service that takes a person's name and email and returns public profile data (job title, company, social links, etc.). It respects opt-out by design: persons with `#OptOut` in their social profiles are not enriched. See `README.md` for the full product description, features, and licensing.

## 2. Run and test

**Docker (compose v2 — this is what prod runs):**

```bash
docker compose up -d
```

Requires a `.env` file — copy `default.env` and fill in the keys (its comments link to each provider's signup page). API docs at `http://localhost:8080/docs`.

**Local dev with `uv`:**

```bash
uv venv .venv
uv sync --frozen --extra vision
uv run patchright install chrome   # browser automation for anti-bot targets
uv run uvicorn main:app --reload
```

**Tests:**

```bash
uv run pytest thedig/tests
```

**Lint:**

```bash
uv run ruff check .
```

Formatting and type checks are defined in the hatch `lint` env in `pyproject.toml`; pre-commit runs the hygiene hooks in `.pre-commit-config.yaml`.

## 3. HTTP contract

The API authenticates with the `X-API-KEY` header.

**Endpoints:**

- `POST /person/` — single-person enrichment. Body is `EnrichPersonRequest` (`email` + `name` mandatory; optional `homeLocation`, `alternateName`, `givenName`, `familyName`, `image[]`, `jobTitle[]`, `worksFor[]`, `sameAs[]`, `identifier[]`, `url`). Returns `EnrichPersonResponse`.
- `POST /person/bulk?endpoint={webhook}` — enqueues a bulk job; body is an array of `{name, email}`. Returns a token string.

`EnrichPersonResponse.statusCode === 203` with empty `sameAs` is treated as "no enrichment found".

## 4. Deployment

This repo does not deploy itself. Its workflows send cross-repo `repository_dispatch` events consumed by the operator's deploy repository:

- `.github/workflows/deployment-trigger-qa.yml` — on push to `main` or manual; sends `trigger-qa-thedig`.
- `.github/workflows/deployment-trigger-prod.yml` — on published release or manual; sends `trigger-prod-thedig`.

## 5. Hard rules

- **Never commit real API keys.** `default.env` is a template; use key names only (e.g., `API_KEYS`, `BING_API_KEY`).
- **Respect the opt-out path.** If `OptOut` is true, do not return enriched data.
- **Do not change the request/response shape** without a major bump and changelog entry; this is a public API.
