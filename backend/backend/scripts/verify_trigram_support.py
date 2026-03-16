"""Pre-flight verification script for pg_trgm trigram index support.

Run this script before applying the trigram index migration to verify:
1. pg_trgm extension is available
2. Korean text trigram generation works correctly
3. Database locale supports UTF-8

Usage:
    cd backend
    python -m backend.scripts.verify_trigram_support
"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.orm import get_write_session


async def verify_extension_available(session: AsyncSession) -> bool:
    """Check if pg_trgm extension is available."""
    result = await session.execute(
        text("SELECT * FROM pg_available_extensions WHERE name = 'pg_trgm'")
    )
    row = result.fetchone()
    if row:
        print(f"✅ pg_trgm extension available (version: {row[2]})")
        return True
    else:
        print("❌ pg_trgm extension NOT available")
        return False


async def verify_database_locale(session: AsyncSession) -> bool:
    """Check database locale for Korean text support."""
    result = await session.execute(
        text(
            """
            SELECT
                current_database() as db,
                pg_encoding_to_char(encoding) as encoding,
                datcollate as collate,
                datctype as ctype
            FROM pg_database
            WHERE datname = current_database()
        """
        )
    )
    row = result.fetchone()
    if row:
        db, encoding, collate, ctype = row
        print(f"📊 Database: {db}")
        print(f"   Encoding: {encoding}")
        print(f"   Collate: {collate}")
        print(f"   Ctype: {ctype}")

        # Check if locale is C (problematic for Korean)
        if ctype == "C" or ctype == "POSIX":
            print(
                "⚠️  WARNING: LC_CTYPE is 'C' - Korean trigrams may not work correctly!"
            )
            print("   Consider using UTF-8 locale (e.g., en_US.UTF-8, ko_KR.UTF-8)")
            return False

        if "UTF" in encoding.upper():
            print("✅ UTF-8 encoding detected - Korean text supported")
            return True
        else:
            print(f"⚠️  WARNING: Non-UTF8 encoding ({encoding}) may cause issues")
            return False
    return False


async def verify_korean_trigrams(session: AsyncSession) -> bool:
    """Test trigram generation with Korean text."""
    # First, temporarily enable extension for testing
    await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await session.commit()

    test_cases = [
        ("김", "Single syllable"),
        ("김철", "Two syllables"),
        ("김철수", "Three syllables (threshold)"),
        ("010", "Phone prefix"),
        ("01012345678", "Full phone number"),
    ]

    print("\n📝 Korean Trigram Generation Test:")
    all_passed = True

    for test_input, description in test_cases:
        result = await session.execute(
            text("SELECT show_trgm(:input)"), {"input": test_input}
        )
        trigrams = result.scalar()

        if trigrams:
            trigram_count = len(trigrams.split('","'))
            print(f"   '{test_input}' ({description}): {trigram_count} trigrams")
            if len(test_input) >= 3 and trigram_count < 3:
                print("      ⚠️  Warning: Expected more trigrams for 3+ char input")
        else:
            print(f"   '{test_input}': ❌ No trigrams generated")
            all_passed = False

    return all_passed


async def verify_ilike_with_index(session: AsyncSession) -> bool:
    """Test that ILIKE queries can use trigram index."""
    # Create a temporary test
    print("\n🔍 ILIKE Index Usage Test:")

    result = await session.execute(
        text(
            """
            EXPLAIN (FORMAT TEXT)
            SELECT * FROM "user"
            WHERE name ILIKE '%테스트%'
            AND deleted_at IS NULL
        """
        )
    )
    plan = "\n".join([row[0] for row in result.fetchall()])

    # Before index creation, it should show Seq Scan
    if "Seq Scan" in plan:
        print("   Current: Sequential Scan (expected before index creation)")
        print("   After index: Should show 'Bitmap Index Scan on idx_user_name_trgm'")
        return True
    elif "idx_user_name_trgm" in plan:
        print("   ✅ Trigram index already in use!")
        return True
    else:
        print(f"   Query plan: {plan[:200]}...")
        return True


async def main():
    """Run all verification checks."""
    print("=" * 60)
    print("🔧 pg_trgm Trigram Index Pre-flight Verification")
    print("=" * 60)

    async with get_write_session() as session:
        results = []

        # 1. Check extension availability
        print("\n[1/4] Checking pg_trgm extension availability...")
        results.append(await verify_extension_available(session))

        # 2. Check database locale
        print("\n[2/4] Checking database locale...")
        results.append(await verify_database_locale(session))

        # 3. Test Korean trigrams
        print("\n[3/4] Testing Korean trigram generation...")
        results.append(await verify_korean_trigrams(session))

        # 4. Test ILIKE query plan
        print("\n[4/4] Testing ILIKE query plan...")
        results.append(await verify_ilike_with_index(session))

    # Summary
    print("\n" + "=" * 60)
    if all(results):
        print("✅ All pre-flight checks PASSED")
        print("   You can proceed with the trigram index migration.")
        return 0
    else:
        print("⚠️  Some checks had warnings or failed")
        print("   Review the output above before proceeding.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
