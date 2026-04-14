# Samba Wave Backend

FastAPI backend for the Samba Wave operations platform.

## Local Run

```bash
cd backend
uv venv
uv pip install -e .[dev]
.venv/Scripts/python run.py --reload --port 28080
```

Root workspace shortcut:

```bash
npm run dev
```

Backend tests should also use the pinned virtualenv interpreter:

```bash
cd backend
.venv/Scripts/python -m pytest
```

Or from the repo root:

```bash
npm run test:backend
```

## Structure

```text
backend/
  backend/
    main.py          # Thin entrypoint
    app_factory.py   # FastAPI app assembly
    lifecycle.py     # Startup/shutdown hooks
    api/v1/routers/  # HTTP routers
    domain/          # Business domains
    db/              # Engine/session management
    core/            # Settings
  alembic/           # DB migrations
  pyproject.toml     # Python deps and tooling
```

## Notes

- Main app entry is `backend.main:app`.
- Development docs endpoints are enabled only outside production.
- Startup runs operational bootstrap work in `backend/lifecycle.py`, so treat app startup as more than plain API boot.
- Runtime is pinned to Python `3.12.3` in local `.venv`, Docker, and startup validation.
