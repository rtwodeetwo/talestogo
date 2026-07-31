#!/usr/bin/env python3
"""
Sync production data to localhost for testing.

This script copies data from the production database to your local database,
filtering by specific tenants. It's useful for testing multi-tenant features.

Features:
- Automatically handles schema differences between production and local databases
- Resets all user passwords to "test123" for security
- Clears API keys and invitation tokens
- Works with both PostgreSQL and SQLite local databases
- Deletes local users by email to avoid conflicts

Usage:
    # Sync specific tenants
    python scripts/admin/sync_prod_to_localhost.py --tenants "Princeton University" "Solstice HC"

    # Sync all tenants
    python scripts/admin/sync_prod_to_localhost.py --all

    # Dry run to see what would be synced
    python scripts/admin/sync_prod_to_localhost.py --tenants "Solstice HC" --dry-run

Note: All synced users will have password "test123"
"""

import os
import sys
import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import datetime

# Production database URL from environment
PROD_DB_URL = os.getenv("PROD_DATABASE_URL") or os.getenv("DATABASE_URL")
if not PROD_DB_URL:
    raise RuntimeError("PROD_DATABASE_URL or DATABASE_URL environment variable is not set")

# Local database URL (PostgreSQL by default)
LOCAL_DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost/tales_db")

# Tables to sync in dependency order
TABLES_TO_SYNC = [
    'tenants',
    'users',
    'brand_info',
    'queries',
    'target_descriptors',
    'competitors',
    'responses',
    'collection_batches',
    'scheduled_tasks',
    'persona_generations',
    'personas',
]

# Default test password for all synced users (for security)
DEFAULT_TEST_PASSWORD = "bcrypt_hash_of_test123"  # You should hash "test123" with bcrypt


class DataSyncer:
    def __init__(self, prod_url, local_url, dry_run=False):
        self.prod_engine = create_engine(prod_url)
        self.local_engine = create_engine(local_url)
        self.dry_run = dry_run

        # Detect database types
        self.is_sqlite = 'sqlite' in local_url.lower()

        ProdSession = sessionmaker(bind=self.prod_engine)
        LocalSession = sessionmaker(bind=self.local_engine)

        self.prod_session = ProdSession()
        self.local_session = LocalSession()

    def table_has_column(self, table_name, column_name, session=None):
        """Check if a table has a specific column (database-agnostic)."""
        if session is None:
            session = self.local_session

        try:
            # Try to query the column - if it fails, column doesn't exist
            query = f"SELECT {column_name} FROM {table_name} LIMIT 0"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
            session.execute(text(query))
            return True
        except Exception:
            # Rollback the failed transaction
            session.rollback()
            return False

    def get_tenant_ids(self, tenant_names):
        """Get tenant IDs from production database."""
        if not tenant_names:
            return []

        placeholders = ','.join([f":name{i}" for i in range(len(tenant_names))])
        query = f"SELECT id, tenant_name FROM tenants WHERE tenant_name IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
        params = {f"name{i}": name for i, name in enumerate(tenant_names)}

        result = self.prod_session.execute(text(query), params)
        tenants = result.fetchall()

        print(f"\nFound {len(tenants)} tenant(s) in production:")
        for tid, tname in tenants:
            print(f"  - {tname} (ID: {tid})")

        return [tid for tid, _ in tenants]

    def clear_local_data(self, tenant_ids):
        """Clear existing data for specified tenants from local database."""
        if self.dry_run:
            print("\n[DRY RUN] Would clear local data for tenants:", tenant_ids)
            return

        print("\nClearing local data for selected tenants...")

        # Get emails of users in these tenants from production
        # We'll also delete local users with matching emails regardless of their tenant
        user_emails = []
        if tenant_ids:
            placeholders = ','.join([f":id{i}" for i in range(len(tenant_ids))])
            email_query = f"SELECT DISTINCT email FROM users WHERE tenant_id IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
            params = {f"id{i}": tid for i, tid in enumerate(tenant_ids)}
            result = self.prod_session.execute(text(email_query), params)
            user_emails = [row[0] for row in result.fetchall()]

        # Delete in reverse order to respect foreign keys
        for table in reversed(TABLES_TO_SYNC):
            if table == 'tenants':
                if tenant_ids:
                    placeholders = ','.join([f":id{i}" for i in range(len(tenant_ids))])
                    query = f"DELETE FROM {table} WHERE id IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
                    params = {f"id{i}": tid for i, tid in enumerate(tenant_ids)}
                    self.local_session.execute(text(query), params)
            elif table == 'users':
                # Delete by email to handle users who might exist in different tenants locally
                if user_emails:
                    placeholders = ','.join([f":email{i}" for i in range(len(user_emails))])
                    query = f"DELETE FROM {table} WHERE email IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
                    params = {f"email{i}": email for i, email in enumerate(user_emails)}
                    self.local_session.execute(text(query), params)
            else:
                # For other tables, delete based on user_id
                # Get local user IDs for users with matching emails
                if user_emails:
                    # Get local user IDs for these emails
                    placeholders = ','.join([f":email{i}" for i in range(len(user_emails))])
                    user_query = f"SELECT id FROM users WHERE email IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
                    params = {f"email{i}": email for i, email in enumerate(user_emails)}
                    result = self.local_session.execute(text(user_query), params)
                    local_user_ids = [row[0] for row in result.fetchall()]

                    if local_user_ids:
                        # Check if table has user_id column
                        if self.table_has_column(table, 'user_id'):
                            placeholders = ','.join([f":uid{i}" for i in range(len(local_user_ids))])
                            query = f"DELETE FROM {table} WHERE user_id IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
                            params = {f"uid{i}": uid for i, uid in enumerate(local_user_ids)}
                            self.local_session.execute(text(query), params)

        self.local_session.commit()
        print("Local data cleared.")

    def sync_tenants(self, tenant_ids):
        """Sync tenant records."""
        if not tenant_ids:
            print("\nSkipping tenant sync (no tenants specified)")
            return

        placeholders = ','.join([f":id{i}" for i in range(len(tenant_ids))])
        query = f"SELECT * FROM tenants WHERE id IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
        params = {f"id{i}": tid for i, tid in enumerate(tenant_ids)}

        result = self.prod_session.execute(text(query), params)
        rows = result.fetchall()
        columns = result.keys()

        print(f"\nSyncing {len(rows)} tenant(s)...")

        if self.dry_run:
            print(f"[DRY RUN] Would sync {len(rows)} tenant records")
            return

        # Get columns that exist in local database
        local_columns = set()
        try:
            sample_query = "SELECT * FROM tenants LIMIT 0"
            result = self.local_session.execute(text(sample_query))
            local_columns = set(result.keys())
        except Exception:
            print("  Warning: Could not determine local schema for tenants")
            return

        for row in rows:
            row_dict = dict(zip(columns, row))
            # Only include columns that exist in local database
            filtered_dict = {k: v for k, v in row_dict.items() if k in local_columns}
            cols = ', '.join(filtered_dict.keys())
            vals = ', '.join([f":{col}" for col in filtered_dict.keys()])
            insert_query = f"INSERT INTO tenants ({cols}) VALUES ({vals})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
            self.local_session.execute(text(insert_query), filtered_dict)

        self.local_session.commit()
        print(f"Synced {len(rows)} tenant(s).")

    def sync_users(self, tenant_ids):
        """Sync user records with password reset."""
        if not tenant_ids:
            print("\nSkipping user sync (no tenants specified)")
            return

        placeholders = ','.join([f":id{i}" for i in range(len(tenant_ids))])
        query = f"SELECT * FROM users WHERE tenant_id IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
        params = {f"id{i}": tid for i, tid in enumerate(tenant_ids)}

        result = self.prod_session.execute(text(query), params)
        rows = result.fetchall()
        columns = result.keys()

        print(f"\nSyncing {len(rows)} user(s)...")

        if self.dry_run:
            print(f"[DRY RUN] Would sync {len(rows)} user records (passwords reset to 'test123')")
            return

        # Pre-computed bcrypt hash for "test123"
        # Generated with: passlib.hash.bcrypt.hash("test123")
        # Deliberately public: this overwrites every synced user's password so a
        # copy of prod data is unusable for logging in anywhere but localhost.
        # nosemgrep: generic.secrets.security.detected-bcrypt-hash.detected-bcrypt-hash
        test_password_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5NU2eL2eZ.gqC"

        # Get columns that exist in local database
        local_columns = set()
        try:
            sample_query = "SELECT * FROM users LIMIT 0"
            result = self.local_session.execute(text(sample_query))
            local_columns = set(result.keys())
        except Exception:
            print("  Warning: Could not determine local schema for users")
            return

        for row in rows:
            row_dict = dict(zip(columns, row))
            # Reset password for security
            row_dict['hashed_password'] = test_password_hash
            # Clear API keys for security
            if 'openai_api_key_encrypted' in row_dict:
                row_dict['openai_api_key_encrypted'] = None
            if 'anthropic_api_key_encrypted' in row_dict:
                row_dict['anthropic_api_key_encrypted'] = None
            if 'gemini_api_key_encrypted' in row_dict:
                row_dict['gemini_api_key_encrypted'] = None
            if 'perplexity_api_key_encrypted' in row_dict:
                row_dict['perplexity_api_key_encrypted'] = None
            # Clear invitation tokens
            if 'invitation_token' in row_dict:
                row_dict['invitation_token'] = None

            # Only include columns that exist in local database
            filtered_dict = {k: v for k, v in row_dict.items() if k in local_columns}

            cols = ', '.join(filtered_dict.keys())
            vals = ', '.join([f":{col}" for col in filtered_dict.keys()])
            insert_query = f"INSERT INTO users ({cols}) VALUES ({vals})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
            self.local_session.execute(text(insert_query), filtered_dict)

        self.local_session.commit()
        print(f"Synced {len(rows)} user(s). All passwords reset to 'test123'.")

    def sync_table(self, table_name, tenant_ids):
        """Sync a specific table filtered by tenant users."""
        if not tenant_ids:
            return

        # Get user IDs for these tenants
        placeholders = ','.join([f":id{i}" for i in range(len(tenant_ids))])
        user_query = f"SELECT id FROM users WHERE tenant_id IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
        params = {f"id{i}": tid for i, tid in enumerate(tenant_ids)}
        result = self.prod_session.execute(text(user_query), params)
        user_ids = [row[0] for row in result.fetchall()]

        if not user_ids:
            print(f"\nSkipping {table_name} (no users found for selected tenants)")
            return

        # Check if table has user_id column (check production database)
        if not self.table_has_column(table_name, 'user_id', session=self.prod_session):
            print(f"\nSkipping {table_name} (no user_id column)")
            return

        # Fetch data
        placeholders = ','.join([f":uid{i}" for i in range(len(user_ids))])
        query = f"SELECT * FROM {table_name} WHERE user_id IN ({placeholders})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
        params = {f"uid{i}": uid for i, uid in enumerate(user_ids)}

        result = self.prod_session.execute(text(query), params)
        rows = result.fetchall()
        columns = result.keys()

        if not rows:
            print(f"\nNo data to sync for {table_name}")
            return

        print(f"\nSyncing {len(rows)} record(s) from {table_name}...")

        if self.dry_run:
            print(f"[DRY RUN] Would sync {len(rows)} records from {table_name}")
            return

        # Get columns that exist in local database
        local_columns = set()
        try:
            sample_query = f"SELECT * FROM {table_name} LIMIT 0"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
            result = self.local_session.execute(text(sample_query))
            local_columns = set(result.keys())
        except Exception:
            print(f"  Warning: Could not determine local schema for {table_name}")
            return

        success_count = 0
        for row in rows:
            row_dict = dict(zip(columns, row))
            # Only include columns that exist in local database
            filtered_dict = {k: v for k, v in row_dict.items() if k in local_columns}

            if not filtered_dict:
                print(f"  Warning: No matching columns for {table_name}")
                continue

            cols = ', '.join(filtered_dict.keys())
            vals = ', '.join([f":{col}" for col in filtered_dict.keys()])
            insert_query = f"INSERT INTO {table_name} ({cols}) VALUES ({vals})"  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
            try:
                self.local_session.execute(text(insert_query), filtered_dict)
                self.local_session.commit()  # Commit after each successful insert
                success_count += 1
            except Exception as e:
                self.local_session.rollback()  # Rollback failed insert
                # Only print first error to avoid spam
                if success_count == 0:
                    print(f"  Warning: Failed to insert record into {table_name}: {e}")
                continue

        print(f"Synced {success_count} record(s) from {table_name}.")

    def sync_all(self, tenant_names=None):
        """Sync all data for specified tenants."""
        print("=" * 60)
        print("DATA SYNC: Production → Localhost")
        print("=" * 60)

        if self.dry_run:
            print("\n*** DRY RUN MODE - No changes will be made ***\n")

        # Get tenant IDs
        tenant_ids = []
        if tenant_names:
            tenant_ids = self.get_tenant_ids(tenant_names)
            if not tenant_ids:
                print(f"\nError: No tenants found matching {tenant_names}")
                return

        # Clear existing local data
        self.clear_local_data(tenant_ids)

        # Sync tenants
        self.sync_tenants(tenant_ids)

        # Sync users
        self.sync_users(tenant_ids)

        # Sync other tables
        for table in TABLES_TO_SYNC:
            if table not in ['tenants', 'users']:
                self.sync_table(table, tenant_ids)

        print("\n" + "=" * 60)
        print("Sync complete!")
        print("=" * 60)
        if not self.dry_run:
            print("\nAll synced users have password: test123")
            print("You can now test with localhost data.")

    def close(self):
        """Close database connections."""
        self.prod_session.close()
        self.local_session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Sync production data to localhost for testing"
    )
    parser.add_argument(
        '--tenants',
        nargs='+',
        help='Tenant names to sync (e.g., "Princeton University" "Solstice HC")'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Sync all tenants (use with caution)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be synced without making changes'
    )

    args = parser.parse_args()

    if not args.tenants and not args.all:
        print("Error: Must specify --tenants or --all")
        parser.print_help()
        sys.exit(1)

    tenant_names = args.tenants if args.tenants else None

    syncer = DataSyncer(PROD_DB_URL, LOCAL_DB_URL, dry_run=args.dry_run)

    try:
        syncer.sync_all(tenant_names)
    finally:
        syncer.close()


if __name__ == "__main__":
    main()
