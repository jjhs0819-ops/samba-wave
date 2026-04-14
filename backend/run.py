"""Local development server runner."""

import argparse

import uvicorn

from backend.main import app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=28080)
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    uvicorn.run(
        "backend.main:app" if args.reload else app,
        host="127.0.0.1",
        port=args.port,
        reload=args.reload,
        reload_dirs=["backend"] if args.reload else None,
    )
