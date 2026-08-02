#!/usr/bin/env python3
"""
Database Migration Runner for Tales Project

Runs the SQL migration files in this directory in order, tracking what has
already been applied in a schema_migrations table.

Works against both SQLite and PostgreSQL. It previously used sqlite3 directly,
which meant migrations could not be applied to a production Postgres deployment
at all. Connections now go through SQLAlchemy, so the target is whatever
DATABASE_URL points at, exactly like the application itself.

Usage:
    python run_migrations.py [--database-url URL | --db-path path/to/tales.db]

Options:
    --database-url: SQLAlchemy URL. Defaults to $DATABASE_URL, then to the local
                    SQLite file.
    --db-path: Path to a SQLite database file (shorthand for a sqlite:/// URL).
    --migration: Specific migration to run (e.g. 001). If omitted, runs all.
    --dry-run: Show what would be executed without running it.
    --no-backup: Skip the pre-migration backup.

Backups are only automatic for SQLite, where the database is a single file. On
PostgreSQL the script refuses to invent a backup strategy and instead prints the
pg_dump command to run first; pass --no-backup once you have taken one.

Examples:
    python run_migrations.py
    python run_migrations.py --migration 003
    python run_migrations.py --database-url postgresql://user@host/tales --dry-run
"""

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path
import shutil

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Migration tracking table. AUTOINCREMENT is SQLite-only and SERIAL is
# Postgres-only, so the identity column is spelled per dialect.
MIGRATION_TABLE_SQL = {
    "sqlite": """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    migration_name VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""",
    "postgresql": """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id SERIAL PRIMARY KEY,
    migration_name VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""",
}


def resolve_database_url(database_url=None, db_path=None):
    """Work out which database to migrate.

    Precedence: explicit --database-url, then --db-path, then $DATABASE_URL,
    then the local SQLite file. The $DATABASE_URL branch is what makes this
    usable against a deployed Postgres instance.
    """
    if database_url:
        return database_url
    if db_path:
        return f"sqlite:///{Path(db_path).resolve()}"

    env_url = os.getenv("DATABASE_URL")
    if env_url:
        # Render and Heroku still hand out the legacy postgres:// scheme.
        if env_url.startswith("postgres://"):
            env_url = env_url.replace("postgres://", "postgresql://", 1)
        return env_url

    default_path = Path(__file__).parent.parent / "tales.db"
    return f"sqlite:///{default_path}"


def sqlite_path_from_url(url):
    """The on-disk path for a SQLite URL, or None for any other dialect."""
    if not url.startswith("sqlite:///"):
        return None
    path = url[len("sqlite:///"):]
    if not path or path.startswith(":memory:") or path.startswith("file:"):
        return None
    return Path(path)


def split_sql_statements(sql):
    """Split a migration file into individual statements.

    sqlite3's executescript() ran a whole file in one call; SQLAlchemy has no
    equivalent, so statements are split here. Line comments are stripped first
    so a semicolon inside a comment cannot split a statement.
    """
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]

def backup_database(db_path):
    """Create a backup of the database."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.stem}.backup_{timestamp}{db_path.suffix}"

    print(f"Creating backup: {backup_path}")
    shutil.copy2(db_path, backup_path)
    print(f"✓ Backup created successfully")
    return backup_path

def get_migration_files():
    """Get all SQL migration files in order."""
    migrations_dir = Path(__file__).parent
    migration_files = sorted(migrations_dir.glob("*.sql"))
    return migration_files

def has_migration_been_applied(conn, migration_name):
    """Check if a migration has already been applied."""
    result = conn.execute(
        text("SELECT COUNT(*) FROM schema_migrations WHERE migration_name = :name"),
        {"name": migration_name},
    )
    return result.scalar() > 0

def mark_migration_applied(conn, migration_name):
    """Mark a migration as applied."""
    conn.execute(
        text("INSERT INTO schema_migrations (migration_name) VALUES (:name)"),
        {"name": migration_name},
    )
    conn.commit()

def run_migration_file(conn, migration_file, dry_run=False):
    """Run a single migration file."""
    migration_name = migration_file.name

    # Check if already applied
    if has_migration_been_applied(conn, migration_name):
        print(f"⊘ Skipping {migration_name} (already applied)")
        return True

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Running migration: {migration_name}")

    # Read migration SQL
    with open(migration_file, 'r') as f:
        sql = f.read()

    if dry_run:
        print(f"Would execute SQL from: {migration_file}")
        print(f"Preview (first 500 chars):\n{sql[:500]}...")
        return True

    try:
        for statement in split_sql_statements(sql):
            # BEGIN/COMMIT in the file would fight SQLAlchemy's own transaction
            # handling, so they are skipped; each file runs in one transaction.
            if statement.upper() in ("BEGIN TRANSACTION", "BEGIN", "COMMIT"):
                continue
            conn.execute(text(statement))

        mark_migration_applied(conn, migration_name)

        print(f"✓ Migration {migration_name} applied successfully")
        return True

    except SQLAlchemyError as e:
        conn.rollback()
        print(f"✗ Migration {migration_name} failed: {e}")
        return False

def verify_database(conn):
    """Verify database integrity after migrations."""
    print("\n" + "="*60)
    print("VERIFICATION: Checking for orphaned data...")
    print("="*60)

    tables_to_check = [
        'queries', 'responses', 'competitors', 'target_descriptors',
        'campaigns', 'cited_sources', 'reports', 'task_status',
        'trends', 'analyses'
    ]

    all_clean = True
    for table in tables_to_check:
        try:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")  # nosec B608 - table is from a hardcoded whitelist, not user input
            ).scalar()

            if count > 0:
                print(f"⚠ WARNING: {table} has {count} records with NULL user_id")
                all_clean = False
            else:
                print(f"✓ {table}: No orphaned records")
        except SQLAlchemyError:
            # Table might not exist yet
            conn.rollback()
            print(f"⊘ {table}: Table does not exist (skipped)")

    if all_clean:
        print("\n✓ All tables are clean - no orphaned data found!")
    else:
        print("\n⚠ Some tables still have orphaned data. Check warnings above.")

    return all_clean

def main():
    parser = argparse.ArgumentParser(
        description="Run database migrations for Tales project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--database-url',
        help='SQLAlchemy URL (default: $DATABASE_URL, then the local SQLite file)'
    )
    parser.add_argument(
        '--db-path',
        help='Path to SQLite database file (shorthand for a sqlite:/// URL)'
    )
    parser.add_argument(
        '--migration',
        help='Specific migration number to run (e.g., 001)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be executed without running it'
    )
    parser.add_argument(
        '--no-backup',
        action='store_true',
        help='Skip database backup before migration'
    )
    parser.add_argument(
        '--verify-only',
        action='store_true',
        help='Only verify database, do not run migrations'
    )

    args = parser.parse_args()

    database_url = resolve_database_url(args.database_url, args.db_path)
    db_path = sqlite_path_from_url(database_url)

    if db_path is not None and not db_path.exists():
        print(f"✗ Database file not found: {db_path}")
        print(f"  Please specify the correct path with --db-path")
        return 1

    engine = create_engine(database_url)
    dialect = engine.dialect.name
    if dialect not in MIGRATION_TABLE_SQL:
        print(f"✗ Unsupported database dialect: {dialect}")
        print(f"  Supported: {', '.join(sorted(MIGRATION_TABLE_SQL))}")
        return 1

    print("="*60)
    print("TALES PROJECT - DATABASE MIGRATION TOOL")
    print("="*60)
    # Never print the URL itself: it carries the password on PostgreSQL.
    print(f"Database: {db_path if db_path else f'{dialect} (from DATABASE_URL)'}")
    print(f"Dialect:  {dialect}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print("="*60)

    conn = engine.connect()

    # Create migration tracking table
    for statement in split_sql_statements(MIGRATION_TABLE_SQL[dialect]):
        conn.execute(text(statement))
    conn.commit()

    # Verify only mode
    if args.verify_only:
        verify_database(conn)
        conn.close()
        return 0

    # Create backup (unless disabled or dry run)
    if not args.no_backup and not args.dry_run:
        if db_path is not None:
            backup_path = backup_database(db_path)
            print(f"Backup saved to: {backup_path}")
        else:
            # A file copy is meaningless for a server-hosted database, and
            # silently skipping the backup would be worse than stopping.
            print("✗ Refusing to run without a backup on a non-SQLite database.")
            print("  Take one first, for example:")
            print("    pg_dump \"$DATABASE_URL\" > tales_backup_"
                  f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql")
            print("  Then re-run with --no-backup.")
            conn.close()
            return 1

    # Get migration files
    migration_files = get_migration_files()

    if not migration_files:
        print("No migration files found in migrations directory")
        return 1

    # Filter to specific migration if requested
    if args.migration:
        migration_files = [
            f for f in migration_files
            if f.name.startswith(args.migration)
        ]
        if not migration_files:
            print(f"✗ Migration {args.migration} not found")
            return 1

    print(f"\nFound {len(migration_files)} migration(s) to process:")
    for mf in migration_files:
        status = "✓ Applied" if has_migration_been_applied(conn, mf.name) else "• Pending"
        print(f"  {status}: {mf.name}")

    # Run migrations
    success = True
    for migration_file in migration_files:
        if not run_migration_file(conn, migration_file, dry_run=args.dry_run):
            success = False
            break

    # Verify database after migrations
    if not args.dry_run and success:
        verify_database(conn)

    # Close connection
    conn.close()

    if success:
        print("\n" + "="*60)
        print("✓ Migration complete!")
        print("="*60)
        return 0
    else:
        print("\n" + "="*60)
        print("✗ Migration failed - database may be in inconsistent state")
        print("  Restore from backup and investigate the error")
        print("="*60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
