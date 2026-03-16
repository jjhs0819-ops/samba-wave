#!/usr/bin/env python3
"""
Reset Test Database Script

This script resets the test database for E2E testing by:
1. Truncating all tables (preserving schema)
2. Optionally seeding test data

Usage:
    # Reset only
    python scripts/reset_test_db.py

    # Reset and seed
    python scripts/reset_test_db.py --seed

    # As HTTP endpoint (for Playwright global-setup)
    POST /api/v1/test/reset-db with X-Test-Secret header
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.core.config import settings
from backend.db.orm import get_write_engine


# Tables to truncate (in order to respect foreign key constraints)
TABLES_TO_TRUNCATE = [
    # Junction/dependent tables first
    "user_access_audit",
    "user_subscription",
    "user_photo",
    "user_document",
    "user_preference",
    "user_lifestyle",
    "user_profile",
    "refresh_token",
    # Main tables last
    "user",
]


async def reset_database(seed: bool = False) -> dict:
    """
    Reset the test database by truncating all tables.

    Args:
        seed: If True, seed test data after truncation

    Returns:
        Dict with reset status and details
    """
    if settings.environment == "production":
        raise RuntimeError("CRITICAL: Cannot reset production database!")

    engine = get_write_engine()
    result = {"truncated_tables": [], "seeded": False, "errors": []}

    async with AsyncSession(engine) as session:
        try:
            # Disable foreign key checks temporarily
            await session.execute(text("SET session_replication_role = 'replica';"))

            for table_name in TABLES_TO_TRUNCATE:
                try:
                    await session.execute(
                        text(f"TRUNCATE TABLE {table_name} CASCADE;")
                    )
                    result["truncated_tables"].append(table_name)
                except Exception as e:
                    # Table might not exist
                    result["errors"].append(f"{table_name}: {str(e)}")

            # Re-enable foreign key checks
            await session.execute(text("SET session_replication_role = 'origin';"))

            await session.commit()

            # Seed test data if requested
            if seed:
                await seed_test_data(session)
                result["seeded"] = True

        except Exception as e:
            await session.rollback()
            raise RuntimeError(f"Database reset failed: {e}") from e

    return result


async def seed_test_data(session: AsyncSession) -> None:
    """
    Seed test data for E2E testing.

    Creates:
    - Standard test user (test-user-001)
    - Premium test user (test-user-002)
    - Admin test user (test-user-003)
    """
    from datetime import datetime, timezone
    from backend.domain.user.model import User
    from backend.domain.user.enums import UserStatusEnum

    test_users = [
        User(
            id="test-user-001",
            firebase_id="test-firebase-001",
            auth_type="google",
            auth_provider_id="test-google-001",
            email="test@example.com",
            phone="01099990001",
            name="Test User",
            gender="male",
            birth_year=1990,
            status=UserStatusEnum.ACTIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        User(
            id="test-user-002",
            firebase_id="test-firebase-002",
            auth_type="kakao",
            auth_provider_id="test-kakao-002",
            email="premium@example.com",
            phone="01099990002",
            name="Premium User",
            gender="female",
            birth_year=1995,
            status=UserStatusEnum.ACTIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        User(
            id="test-user-003",
            firebase_id="test-firebase-003",
            auth_type="apple",
            auth_provider_id="test-apple-003",
            email="admin@example.com",
            phone="01099990003",
            name="Admin User",
            gender="male",
            birth_year=1985,
            status=UserStatusEnum.ACTIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    ]

    for user in test_users:
        session.add(user)

    await session.commit()
    print(f"Seeded {len(test_users)} test users")


async def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Reset test database")
    parser.add_argument(
        "--seed", action="store_true", help="Seed test data after reset"
    )
    args = parser.parse_args()

    print(f"Resetting test database (environment: {settings.environment})...")

    try:
        result = await reset_database(seed=args.seed)
        print(f"Truncated tables: {result['truncated_tables']}")
        if result["errors"]:
            print(f"Warnings: {result['errors']}")
        if result["seeded"]:
            print("Test data seeded successfully")
        print("Database reset complete!")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
