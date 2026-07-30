#!/usr/bin/env python3
"""
Migration: Add fiscal_year_start_month to brand_info

Adds a per-brand fiscal-year start month that drives Quarter-over-Quarter
labeling on the Key Metrics dashboard:
  - 1  = calendar year (default): quarters labeled "Q2 2026"
  - 10 = US federal fiscal year (Oct 1): quarters labeled "FY2026 Q3"

The value should be quarter-aligned (1, 4, 7, or 10) so fiscal quarters line up
with calendar quarter boundaries (the dashboard's date windows use those
boundaries; only the labels change). Set the value per brand through the brand
settings API after running this migration.

Note: the app's startup DDL in app/main.py also adds this column automatically
on deploy, so running this script manually is only needed when you want the
column in place before deploying the new code.

Usage:
    DATABASE_URL="your_db_url" python3 migrations/add_fiscal_year_start_month.py
    DATABASE_URL="..." python3 migrations/add_fiscal_year_start_month.py --rollback
"""

import os
import sys
from sqlalchemy import create_engine, text


def run_migration(database_url: str):
    engine = create_engine(database_url)

    print("=" * 70)
    print("MIGRATION: Add fiscal_year_start_month to brand_info")
    print("=" * 70)
    print(f"Database: {database_url.split('@')[1] if '@' in database_url else 'local'}")
    print("=" * 70 + "\n")

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            print("Step 1: Adding fiscal_year_start_month column...")
            conn.execute(text("""
                ALTER TABLE brand_info
                ADD COLUMN IF NOT EXISTS fiscal_year_start_month INTEGER NOT NULL DEFAULT 1
            """))
            print("  Added fiscal_year_start_month (default 1 = calendar year)\n")

            trans.commit()
            print("=" * 70)
            print("MIGRATION COMPLETED SUCCESSFULLY")
            print("=" * 70)
        except Exception as e:
            trans.rollback()
            print(f"\nERROR: {str(e)}")
            print("Migration rolled back - no changes made")
            raise


def run_rollback(database_url: str):
    engine = create_engine(database_url)
    print("ROLLBACK: Removing fiscal_year_start_month from brand_info")
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("""
                ALTER TABLE brand_info DROP COLUMN IF EXISTS fiscal_year_start_month
            """))
            trans.commit()
            print("Rollback completed successfully")
        except Exception as e:
            trans.rollback()
            print(f"Rollback failed: {str(e)}")
            raise


if __name__ == '__main__':
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == '--rollback':
        run_rollback(database_url)
    else:
        run_migration(database_url)
