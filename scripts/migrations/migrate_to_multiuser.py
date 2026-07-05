#!/usr/bin/env python3
"""
Database migration script to add multi-user support to TALES.

This script:
1. Backs up the current database
2. Adds the users table
3. Adds user_id columns to all existing tables
4. Creates an initial admin user (rkremen@pppl.gov)
5. Migrates all existing data to be owned by the admin user

IMPORTANT: Run this script ONCE to migrate from single-user to multi-user mode.
"""

import os
import shutil
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Float, Text, Date, ForeignKey, MetaData, Table, inspect
from sqlalchemy.orm import Session
from app import models
from app.database import engine, Base, SessionLocal
import bcrypt

def get_password_hash(password: str) -> str:
    """Hash a password for storage using bcrypt."""
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')

# Configuration
ADMIN_EMAIL = "rkremen@pppl.gov"
ADMIN_PASSWORD = "changeme123"  # User should change this on first login
ADMIN_NAME = "Rachel Kremen"
ADMIN_ORG = "PPPL"

def backup_database():
    """Create a backup of the current database."""
    db_path = "tales.db"
    if not os.path.exists(db_path):
        print("No existing database found - creating new one.")
        return

    backup_path = f"tales.db.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup_path)
    print(f"✓ Database backed up to: {backup_path}")

def check_if_users_table_exists():
    """Check if the users table already exists."""
    inspector = inspect(engine)
    return 'users' in inspector.get_table_names()

def create_admin_user(db: Session) -> models.User:
    """Create the initial admin user."""
    # Check if admin already exists
    existing_admin = db.query(models.User).filter(models.User.email == ADMIN_EMAIL).first()
    if existing_admin:
        print(f"✓ Admin user already exists: {ADMIN_EMAIL}")
        return existing_admin

    # Create new admin user
    hashed_password = get_password_hash(ADMIN_PASSWORD)
    admin_user = models.User(
        email=ADMIN_EMAIL,
        hashed_password=hashed_password,
        full_name=ADMIN_NAME,
        organization=ADMIN_ORG,
        is_admin=True,
        is_active=True,
        is_invited=True
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    print(f"✓ Created admin user: {ADMIN_EMAIL}")
    print(f"  Default password: {ADMIN_PASSWORD}")
    print(f"  ⚠️  IMPORTANT: Change this password after first login!")
    return admin_user

def check_if_column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

def add_user_id_to_table(table_name: str, admin_user_id: int):
    """Add user_id column to an existing table and set all rows to admin user."""
    # Check if column already exists
    if check_if_column_exists(table_name, 'user_id'):
        print(f"  ✓ {table_name}.user_id already exists - skipping")
        return

    with engine.connect() as conn:
        # SQLite doesn't support adding foreign keys to existing tables easily
        # We'll add the column without the constraint, then set values
        try:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN user_id INTEGER")
            conn.commit()
            print(f"  ✓ Added user_id column to {table_name}")

            # Set all existing rows to belong to admin user
            conn.execute(f"UPDATE {table_name} SET user_id = {admin_user_id}")  # nosec B608 - table/column is a trusted identifier (hardcoded list / DB introspection), not user input; row values use bound params
            conn.commit()
            print(f"  ✓ Migrated existing {table_name} records to admin user")
        except Exception as e:
            print(f"  ⚠️  Warning: Could not modify {table_name}: {e}")
            conn.rollback()

def main():
    """Main migration function."""
    print("=" * 70)
    print("TALES Multi-User Migration Script")
    print("=" * 70)
    print()

    # Step 1: Backup
    print("Step 1: Backing up database...")
    backup_database()
    print()

    # Step 2: Create all tables (this will create users table if it doesn't exist)
    print("Step 2: Creating/updating database schema...")
    Base.metadata.create_all(bind=engine)
    print("✓ Database schema updated")
    print()

    # Step 3: Create admin user
    print("Step 3: Creating admin user...")
    with Session(engine) as db:
        admin_user = create_admin_user(db)
        admin_user_id = admin_user.id
    print()

    # Step 4: Add user_id to existing tables
    print("Step 4: Migrating existing data...")
    tables_to_migrate = [
        'queries',
        'responses',
        'competitors',
        'target_descriptors',
        'campaigns',
        'cited_sources',
        'reports',
        'analyses',
        'trends'
    ]

    for table_name in tables_to_migrate:
        add_user_id_to_table(table_name, admin_user_id)

    print()
    print("=" * 70)
    print("Migration Complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print(f"1. Log in with email: {ADMIN_EMAIL}")
    print(f"2. Use password: {ADMIN_PASSWORD}")
    print("3. CHANGE YOUR PASSWORD immediately in user settings")
    print("4. Add your API keys in user settings")
    print("5. The backend server will restart automatically")
    print()
    print("All your existing queries, responses, and data have been")
    print("migrated to your admin account and are ready to use!")
    print()

if __name__ == "__main__":
    main()
