# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Monorepo Structure

This is a **monorepo** containing both backend (FastAPI) and frontend (Next.js) applications:

- `backend/` - Python FastAPI backend with PostgreSQL
- `frontend/` - Next.js 15 frontend with TypeScript and Tailwind CSS

## Backend Development

### Prerequisites

- Python 3.12.3 (exact version, see `backend/pyproject.toml`)
- Docker & Docker Compose

### Setup

```bash
cd backend
uv venv
source .venv/bin/activate
uv pip install -e .
uv pip install -e .[dev]  # Install dev dependencies (black, isort, mypy, ruff)
```

### Running the Backend

```bash
# Development server (note: module is backend.main not app.main)
cd backend
uvicorn backend.main:app --reload --port 28080

# Docker Compose (production-like environment)
cd backend
docker-compose up
```

### Code Quality

```bash
cd backend
black .                           # Format code
isort . --profile black          # Sort imports
ruff check --fix .               # Lint with auto-fix
mypy .                           # Type checking
pre-commit run --all-files       # Run all pre-commit hooks
```

### Backend Architecture

**Framework:** FastAPI with async/await pattern using SQLModel + SQLAlchemy

**Database Layer:**

- **Read/Write Separation**: Separate database connections for read and write operations
- Event loop-based caching of engines and sessionmakers in `backend/db/orm.py`
- Session factories:
  - `get_write_session()` / `get_write_session_dependency()` for write operations
  - `get_read_session()` / `get_read_session_dependency()` for read operations
- PostgreSQL with asyncpg driver, SSL required for connections

**Domain-Driven Design:**

- Business logic organized in `backend/domain/{entity}/` directories
- Each domain contains: `model.py` (SQLModel), `service.py` (business logic), `repository.py` (data access)
- Domains: `user`, `auth`, `artist`, `artwork`, `admin`, `curai`, `exhibition`, `message`, `notification`, `subscription`, `shared`

**API Structure:**

- Versioned endpoints under `/api/v1/` prefix
- Routers in `backend/api/v1/routers/`: `auth.py`, `artist.py`, `artwork.py`, `admin.py`, `curai.py`, `exhibition.py`, `message.py`, `notification.py`, `health.py`
- DTOs in `backend/dtos/` for request/response validation
- Main app creation in `backend/main.py` via `create_application()`

**Configuration:**

- Settings in `backend/core/config.py` using Pydantic BaseSettings
- Environment variables required: database credentials (read/write), JWT config
- CORS configured for local development and production domains (qwarty.net)

**Deployment:**

- Docker image: `206404754787.dkr.ecr.ap-northeast-2.amazonaws.com/qwarty-backend:latest`
- Deployed to AWS ECS cluster `qwarty-backend-cluster`
- Auto-deployment on push to `main` branch via GitHub Actions

## Frontend Development

### Prerequisites

- Node.js 20+
- pnpm package manager

### Setup

```bash
cd frontend
pnpm install
```

### Running the Frontend

```bash
cd frontend
pnpm dev          # Development server with Turbopack (http://localhost:3000)
pnpm build        # Production build with Turbopack
pnpm start        # Start production server
pnpm lint         # Run ESLint
```

### Frontend Architecture

**Framework:** Next.js 15 (App Router) with React 19, TypeScript, Tailwind CSS 4

**Project Structure:**

- `src/app/` - Next.js App Router pages and API routes
  - Route groups: `/login`, `/sign-up`, `/artists`, `/artist`, `/account`, `/admin`, `/agent`, `/explore`, `/messages`, `/search`
  - API routes: `/api/upload` (S3 file upload)
- `src/components/` - Reusable React components organized by feature
- `src/lib/` - Core utilities and configurations
  - `api.ts` - API client for backend communication
  - `serverAuth.ts` - Server-side authentication utilities
  - `s3Upload.ts` - AWS S3 upload utilities with compression
  - `emailAuth.ts` - Email authentication utilities
  - `firebase.ts` - Firebase configuration
  - `theme.ts` - MUI theme configuration
- `src/hooks/` - Custom React hooks
- `src/providers/` - React context providers
- `src/utils/` - Utility functions
- `src/types/` - TypeScript type definitions
- `src/const/` - Application constants
- `src/interfaces/` - TypeScript interfaces
- `src/locales/` - Internationalization (i18n) with next-intl

**Key Technologies:**

- **Styling:** Tailwind CSS 4, MUI Material (components), Emotion (CSS-in-JS)
- **State Management:** React hooks and context providers
- **Authentication:** JWT tokens with server-side validation
- **File Upload:** AWS S3 with client-side compression
- **Internationalization:** next-intl for i18n support
- **UI Components:** MUI Material, Lucide React icons

**Configuration:**

- `next.config.ts` - Next.js config with remote image patterns (AWS S3), Turbopack enabled
- `tailwind.config.ts` - Tailwind CSS 4 configuration
- `eslint.config.mjs` - ESLint configuration with TypeScript support
- Environment variables required: API endpoint, Firebase config, AWS credentials, Kakao OAuth

## Development Workflow

### Environment Files

Backend and frontend both require `.env` files:

- `backend/.env` - Database credentials (read/write), JWT config
- `frontend/.env` - API endpoint, Firebase, AWS S3, Kakao OAuth credentials

### Git Workflow

- Main branch: `main` (protected, auto-deploys backend to AWS ECS)
- Create feature branches for development
- Backend deployment triggers automatically on push to `main` via `.github/workflows/deploy-real.yaml`
  - Builds Docker image and pushes to ECR: `206404754787.dkr.ecr.ap-northeast-2.amazonaws.com/qwarty-backend:latest`
  - Deploys to ECS service: `prod-apne2-qwarty-backend-svc` in cluster `qwarty-backend-cluster`
  - Task definition: `backend/prod-apne2-qwarty-backend-task-def.json`

### Key Design Patterns

**Backend:**

- Domain-Driven Design with clear separation of concerns
- Repository pattern for data access
- DTO pattern for API contracts
- Dependency injection via FastAPI's `Depends()`
- Async/await throughout with proper session management

**Frontend:**

- Server-side rendering (SSR) with App Router
- Client/Server component separation
- Server actions for API calls
- Image optimization with S3 upload
- Responsive design with Tailwind CSSs

### Important Notes

- **Backend module path:** Use `backend.main:app` not `app.main:app` when running uvicorn
- **Database sessions:** Always use appropriate read/write session factory from `backend/db/orm.py`
  - Use `get_write_session_dependency()` for FastAPI endpoints that modify data
  - Use `get_read_session_dependency()` for FastAPI endpoints that only read data
- **Frontend API calls:** Centralized in `src/lib/api.ts`
- **Image uploads:** S3 upload uses presigned POST URLs for direct client-side upload
  - Flow: Client → Backend (`POST /api/v1/upload/presigned-url`) → Backend generates presigned POST → Client uploads directly to S3
  - Backend: `backend/utils/s3.py` - `generate_presigned_post()` creates presigned POST with fields and conditions (max 50MB)
  - Frontend: `src/lib/s3Upload.ts` - Handles compression (browser-image-compression), presigned URL request, and S3 upload
  - Images are compressed client-side to WebP format before upload (optional, depending on function used)
  - Supports thumbnail generation: uploads both original and compressed thumbnail in parallel
- **Authentication:** JWT-based, server-side validation in `src/lib/serverAuth.ts`
- **Pre-commit hooks:** Backend uses black, isort, ruff, and other checks via `.pre-commit-config.yaml`

## Testing & Performance Monitoring

### Browser Testing with Chrome DevTools MCP

**IMPORTANT:** Always use **chrome-devtools MCP** for frontend browser testing and performance measurement. Do NOT manually start the dev server with `pnpm dev` for testing.

**Available MCP Tools:**

- `mcp__chrome-devtools__navigate_page` - Navigate to URL
- `mcp__chrome-devtools__take_snapshot` - Take page snapshot (structure)
- `mcp__chrome-devtools__take_screenshot` - Take screenshot
- `mcp__chrome-devtools__click` - Click elements
- `mcp__chrome-devtools__fill` - Fill form inputs
- `mcp__chrome-devtools__list_console_messages` - Check console errors
- `mcp__chrome-devtools__list_network_requests` - Monitor API calls
- `mcp__chrome-devtools__performance_start_trace` - Start performance recording
- `mcp__chrome-devtools__performance_stop_trace` - Stop and analyze performance

### Performance Testing Workflow

**Step 1: Start Dev Server in Background**
If chrome-devtools MCP is alreay running, kill it first.
using chrome-devtools MCP, start dev server in background

**Step 2: Run Browser Tests with chrome-devtools MCP**

```typescript
// Example test flow:
1. Navigate to page: mcp__chrome-devtools__navigate_page({ url: "http://localhost:3000/ko" })
2. Take snapshot: mcp__chrome-devtools__take_snapshot({ verbose: false })
3. Check console: mcp__chrome-devtools__list_console_messages()
4. Start performance trace: mcp__chrome-devtools__performance_start_trace({ reload: true, autoStop: true })
5. Analyze results: Review LCP, FCP, TTI, CLS metrics
6. Take screenshot: mcp__chrome-devtools__take_screenshot({ fullPage: true })
```

**Step 3: Measure Core Web Vitals**

- **LCP (Largest Contentful Paint):** Target <2000ms
- **FCP (First Contentful Paint):** Target <1000ms
- **CLS (Cumulative Layout Shift):** Target <0.1
- **TTI (Time to Interactive):** Target <2500ms
- **TBT (Total Blocking Time):** Target <300ms

### Test Documentation

**Test Plans and Reports:**

- `frontend/tests/browser/` - Browser test documentation
- `frontend/tests/browser/test-reports/` - Test execution reports
- `frontend/docs/performance-baseline.md` - Performance baseline metrics
- `frontend/docs/PERFORMANCE-DASHBOARD.md` - Performance dashboard

**Test Coverage:**

- Home page tests (8 tests)
- Artists page tests (10 tests)
- SearchBar component tests (20 tests)
- Total: 38 automated test cases

### Lighthouse CI (Automated Performance Regression Testing)

**Configuration:** `.lighthouserc.js` in frontend directory
**GitHub Actions:** `.github/workflows/lighthouse-ci.yaml`

**Manual Lighthouse CI Run:**

```bash
cd frontend
pnpm build
npx lhci autorun
```

### Example: Testing Home Page

```bash
# 1. Ensure backend is running
cd backend
uvicorn backend.main:app --reload --port 28080

# 2. Start frontend dev server
cd frontend
pnpm dev

# 3. Use chrome-devtools MCP tools to:
# - Navigate to http://localhost:3000/ko
# - Take snapshot to verify structure
# - Check console messages (expect 0 errors)
# - Start performance trace with reload
# - Review Core Web Vitals
# - Take screenshots for documentation
# - Compare with baseline (frontend/docs/performance-baseline.md)
```

## AI Agent System (Curai)

**Framework:** Pydantic AI with streaming SSE responses

**Architecture:**

- Thread-based conversations with message history persistence
- Agentic search using pre-defined DB tools
