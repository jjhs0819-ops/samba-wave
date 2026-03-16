#!/usr/bin/env python3
"""
Initialize Test Database Script

This script initializes the test database by:
1. Connecting to the test database
2. Running all Alembic migrations
3. Optionally seeding initial test data

Usage:
    # Initialize with migrations only
    python scripts/init_test_db.py

    # Initialize and seed test data
    python scripts/init_test_db.py --seed

    # Force recreate (drop all and migrate)
    python scripts/init_test_db.py --recreate
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_alembic_migrations() -> bool:
    """
    Run Alembic migrations using subprocess.

    Returns:
        True if migrations successful, False otherwise
    """
    backend_dir = Path(__file__).parent.parent

    # Ensure we're using the test environment
    env = os.environ.copy()

    # Load .env.test if it exists
    env_test_path = backend_dir / ".env.test"
    if env_test_path.exists():
        print(f"Loading environment from {env_test_path}")
        with open(env_test_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()

    try:
        # Run alembic upgrade head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=backend_dir,
            env=env,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Alembic migration failed:")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            return False

        print("Alembic migrations completed successfully")
        print(result.stdout)
        return True

    except FileNotFoundError:
        print("ERROR: alembic command not found. Install with: pip install alembic")
        return False
    except Exception as e:
        print(f"ERROR running migrations: {e}")
        return False


def run_alembic_downgrade() -> bool:
    """
    Downgrade all Alembic migrations (drop all tables).

    Returns:
        True if downgrade successful, False otherwise
    """
    backend_dir = Path(__file__).parent.parent

    env = os.environ.copy()
    env_test_path = backend_dir / ".env.test"
    if env_test_path.exists():
        with open(env_test_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()

    try:
        result = subprocess.run(
            ["alembic", "downgrade", "base"],
            cwd=backend_dir,
            env=env,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Alembic downgrade failed:")
            print(f"stderr: {result.stderr}")
            return False

        print("Alembic downgrade completed")
        return True

    except Exception as e:
        print(f"ERROR running downgrade: {e}")
        return False


async def verify_database_connection() -> bool:
    """
    Verify that we can connect to the test database.

    Returns:
        True if connection successful, False otherwise
    """
    from backend.core.config import settings
    from backend.db.orm import get_write_engine
    from sqlalchemy import text
    from sqlmodel.ext.asyncio.session import AsyncSession

    print(f"Connecting to database: {settings.write_db_host}:{settings.write_db_port}/{settings.write_db_name}")

    try:
        engine = get_write_engine()
        async with AsyncSession(engine) as session:
            result = await session.execute(text("SELECT 1"))
            result.fetchone()
            print("Database connection verified")
            return True
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}")
        return False


async def seed_test_data() -> bool:
    """
    Seed test data using the reset_test_db module.

    Returns:
        True if seeding successful, False otherwise
    """
    try:
        from backend.scripts.reset_test_db import reset_database

        result = await reset_database(seed=True)
        print(f"Test data seeded: {result}")
        return True
    except Exception as e:
        print(f"ERROR seeding test data: {e}")
        return False


async def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Initialize test database")
    parser.add_argument(
        "--seed", action="store_true", help="Seed test data after initialization"
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop all tables and recreate (downgrade + upgrade)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify database connection without running migrations",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Test Database Initialization")
    print("=" * 60)

    # Step 1: Verify database connection
    if not await verify_database_connection():
        print("\nERROR: Cannot connect to database. Is the test-db container running?")
        print("Try: docker-compose -f docker-compose.test.yaml up -d test-db")
        sys.exit(1)

    if args.verify_only:
        print("\nConnection verified. Exiting (--verify-only mode)")
        sys.exit(0)

    # Step 2: Recreate if requested
    if args.recreate:
        print("\n-- Dropping all tables (downgrade to base)...")
        if not run_alembic_downgrade():
            print("WARNING: Downgrade failed, continuing with upgrade...")

    # Step 3: Run migrations
    print("\n-- Running Alembic migrations...")
    if not run_alembic_migrations():
        print("\nERROR: Migration failed")
        sys.exit(1)

    # Step 4: Seed test data if requested
    if args.seed:
        print("\n-- Seeding test data...")
        if not await seed_test_data():
            print("\nWARNING: Seeding failed, but migrations succeeded")

    print("\n" + "=" * 60)
    print("Test database initialization complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
