# Contributing to ClearFrame

Thanks for your interest! ClearFrame is small and approachable on purpose — you can be productive in minutes.

## Setup

```bash
make install     # backend (pip) + frontend (npm)
make seed        # one demo campaign with four sample creatives
make api         # backend  → http://localhost:8000
make web         # frontend → http://localhost:5001
```

Everything runs in **mock mode** with no API key (recorded fixtures stand in for TwelveLabs), so you can
develop the full app offline. Add a TwelveLabs key in **Settings** to run on real videos.

## How it's organized

- `backend/src/decision.py` is the heart — the deterministic policy engine. Changes here need a test.
- `backend/src/pipeline.py` wires the stages; `client.py` is the only thing that talks to TwelveLabs.
- Policies are **config**, not code — edit `backend/config/policies.yaml`.
- The reviewer UI is `frontend/src/ClearframeApp.jsx`.

## Workflow

1. Open an issue describing the change.
2. Branch from `main`; keep changes small and focused.
3. Run the tests: `make test` (and `make demo` to sanity-check the pipeline).
4. Open a PR with a clear description. Screenshots help for UI changes.

## Style

- **Python** — standard library style, type hints where they help, docstrings on modules/public functions.
- **JavaScript/React** — match the surrounding code; keep components readable.
- Touch only what the change needs. No unrelated refactors in the same PR.

## Security

Never commit secrets. `.env`, `.secret_key`, and the SQLite DB are gitignored — keep it that way.
The TwelveLabs key is encrypted at rest and must never be exposed to the browser.
