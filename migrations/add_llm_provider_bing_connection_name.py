#!/usr/bin/env python3
"""
Migration: Add bing_connection_name column to llm_providers table.

Required to support Azure AI Foundry Agents (azure_foundry_agents api_type).
The column stores the Foundry project connection name for Grounding with Bing
Search. Other api_types ignore it — it stays NULL.

Run with: python migrations/add_llm_provider_bing_connection_name.py
Rollback: python migrations/add_llm_provider_bing_connection_name.py --rollback
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from app.database import engine


COLUMN_NAME = "bing_connection_name"
TABLE_NAME = "llm_providers"


def column_exists() -> bool:
    inspector = inspect(engine)
    if TABLE_NAME not in inspector.get_table_names():
        return False
    return any(c["name"] == COLUMN_NAME for c in inspector.get_columns(TABLE_NAME))


def run_migration():
    print(f"Adding {COLUMN_NAME} column to {TABLE_NAME}...")

    if column_exists():
        print(f"   ✓ Column '{COLUMN_NAME}' already exists. Nothing to do.")
        return

    with engine.begin() as conn:
        conn.execute(text(
            f"ALTER TABLE {TABLE_NAME} ADD COLUMN {COLUMN_NAME} VARCHAR(200)"
        ))

    if column_exists():
        print(f"   ✓ Column '{COLUMN_NAME}' added successfully.")
    else:
        print(f"   ⚠️  Column add reported success but inspector did not find it.")


def rollback_migration():
    print(f"Dropping {COLUMN_NAME} column from {TABLE_NAME}...")

    if not column_exists():
        print(f"   ✓ Column '{COLUMN_NAME}' does not exist. Nothing to rollback.")
        return

    dialect = engine.dialect.name
    if dialect == "sqlite":
        print(
            "   ⚠️  SQLite cannot DROP COLUMN reliably. Skipping. "
            "Recreate the table manually if needed."
        )
        return

    with engine.begin() as conn:
        conn.execute(text(
            f"ALTER TABLE {TABLE_NAME} DROP COLUMN {COLUMN_NAME}"
        ))
    print(f"   ✓ Column '{COLUMN_NAME}' dropped.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Add bing_connection_name column to llm_providers")
    parser.add_argument("--rollback", action="store_true", help="Drop the column instead")
    args = parser.parse_args()

    if args.rollback:
        rollback_migration()
    else:
        run_migration()
