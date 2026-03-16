# Little-Boy Backend

Backend API service for the Little-Boy application.

## Setup

```bash
# Create virtual environment
uv venv

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
uv pip install -e .

# Start the development server
uvicorn app.main:app --reload --port 28900
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

## Project Structure

```
backend/
├── app/               # Application code
│   ├── api/          # API endpoints
│   ├── core/         # Core configuration
│   ├── db/           # Database models and repositories
│   └── services/     # Business logic services
├── alembic/          # Database migrations
├── infrastructure/   # Infrastructure as code
├── scripts/          # Utility scripts
└── tests/           # Test suite
```

## API Documentation

Once running, API documentation is available at:

- Swagger UI: http://localhost:8000/docs
