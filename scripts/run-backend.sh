#!/usr/bin/env bash
cd "$(dirname "$0")/../backend"
source .venv/Scripts/activate
uvicorn backend.main:app --reload --port 28080
exec bash
