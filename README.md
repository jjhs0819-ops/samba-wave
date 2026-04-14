# Samba Wave

Monorepo for the Samba Wave platform.

## Apps

- `frontend/`: Next.js web app
- `backend/`: FastAPI API and background lifecycle bootstrap
- `extension/`: Chrome extension service worker and content scripts
- `extension-web/`: web-facing extension variant
- `docs/`: product, ops, and integration docs

## Local Development

```bash
npm run dev
```

This starts:

- frontend on `http://localhost:3000`
- backend on `http://localhost:28080`

Backend tests use the pinned backend virtualenv:

```bash
npm run test:backend
```

## Current Entry Points

- Backend: `backend/backend/main.py`
- Backend app assembly: `backend/backend/app_factory.py`
- Backend lifecycle hooks: `backend/backend/lifecycle.py`
- Frontend app layout: `frontend/src/app/layout.tsx`
- Samba frontend shell: `frontend/src/app/samba/layout.tsx`
- Extension worker: `extension/background.js`

## Runtime Notes

- Backend local and production runtime are pinned to Python `3.12.3`.
- Local backend commands should use `backend/.venv/Scripts/python`.
