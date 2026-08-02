#!/usr/bin/env python3
"""
Import brand data from a Tales export file.

Usage:
    # Inside Docker container:
    docker compose exec app python scripts/admin/import_brand_data.py --file pppl_data.json --admin-email admin@pppl.gov

    # Local development:
    python scripts/admin/import_brand_data.py --file pppl_data.json --admin-email admin@example.com

This script imports data exported by export_brand_data.py:
- Brand configuration
- Queries
- Competitors
- Descriptors
- Collection batches
- Responses with analysis data
- Reports

All data is assigned to the specified admin user.
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    BrandInfo, Query, Response, Competitor, TargetDescriptor,
    CollectionBatch, Report, User
)


def get_database_url():
    """Get database URL from environment."""
    url = os.getenv("DATABASE_URL")
    if not url:
        # Try SQLite fallback for local dev
        db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "tales.db"
        )
        if os.path.exists(db_path):
            return f"sqlite:///{db_path}"
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    return url


def parse_datetime(dt_string):
    """Parse ISO datetime string to datetime object."""
    if not dt_string:
        return None
    try:
        # Handle ISO format with or without microseconds
        if '.' in dt_string:
            return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        return datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
    except ValueError:
        # Try alternate formats
        for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
            try:
                return datetime.strptime(dt_string, fmt)
            except ValueError:
                continue
        return None


def resolve_grounded(recorded, timestamp, grounded_from):
    """How a response being imported was collected.

    Precedence is deliberate: a value recorded at collection time always wins
    over a date-based inference, because it is a fact and the inference is a
    guess about a whole deployment. The guess only fills in rows that have
    nothing recorded at all.

    Returns None when neither is available. None means "unknown", not
    "ungrounded", and every consumer of this column has to keep them apart, or
    an entire imported history would appear to have been collected one way when
    nobody actually knows.
    """
    if recorded is not None:
        return bool(recorded)
    if grounded_from is None or timestamp is None:
        return None
    return timestamp >= grounded_from


def import_brand_data(import_file: str, admin_email: str, dry_run: bool = False,
                      grounded_from=None):
    """Import brand data from JSON export file.

    grounded_from is a datetime, or None. See resolve_grounded.
    """

    # Load export file
    if not os.path.exists(import_file):
        print(f"ERROR: Import file not found: {import_file}")
        sys.exit(1)

    with open(import_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"\n{'='*60}")
    print("TALES DATA IMPORT")
    print(f"{'='*60}")
    print(f"Import file: {import_file}")
    print(f"Exported at: {data['export_info'].get('exported_at', 'unknown')}")
    print(f"Source: {data['export_info'].get('source_system', 'unknown')}")
    print(f"Original owner: {data['export_info'].get('original_owner_email', 'unknown')}")
    print()

    # Show what will be imported
    print("Data to import:")
    print(f"  Brand: {data['brand']['name']}")
    print(f"  Queries: {len(data.get('queries', []))}")
    print(f"  Competitors: {len(data.get('competitors', []))}")
    print(f"  Descriptors: {len(data.get('descriptors', []))}")
    print(f"  Collection Batches: {len(data.get('collection_batches', []))}")
    print(f"  Responses: {len(data.get('responses', []))}")
    print(f"  Reports: {len(data.get('reports', []))}")
    print()

    if dry_run:
        print("DRY RUN MODE - No changes will be made")
        return

    # Connect to database
    database_url = get_database_url()
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Find the admin user
        admin = session.query(User).filter(User.email == admin_email).first()
        if not admin:
            print(f"ERROR: Admin user not found: {admin_email}")
            print("\nAvailable users:")
            users = session.query(User).filter(User.is_admin == True).all()
            for u in users:
                print(f"  - {u.email} (Admin: {u.is_admin})")
            sys.exit(1)

        print(f"Assigning all data to: {admin.email} (ID: {admin.id})")

        # Check if brand already exists
        existing_brand = session.query(BrandInfo).filter(
            BrandInfo.brand_name == data['brand']['name'],
            BrandInfo.user_id == admin.id
        ).first()

        if existing_brand:
            print(f"\nWARNING: Brand '{data['brand']['name']}' already exists for this user!")
            response = input("Do you want to skip importing the brand and just add responses? (y/n): ")
            if response.lower() != 'y':
                print("Import cancelled.")
                sys.exit(0)
            brand = existing_brand
            print(f"Using existing brand (ID: {brand.id})")
        else:
            # Create brand
            brand = BrandInfo(
                user_id=admin.id,
                tenant_id=admin.tenant_id,
                brand_name=data['brand']['name'],
                website_url=data['brand'].get('website_url'),
                industry=data['brand'].get('industry'),
                description=data['brand'].get('description'),
                strategic_messages=data['brand'].get('strategic_messages'),
                is_active=True
            )
            session.add(brand)
            session.flush()  # Get the brand ID
            print(f"Created brand: {brand.brand_name} (ID: {brand.id})")

        # Import queries
        query_count = 0
        for q_data in data.get('queries', []):
            # Check if query already exists
            existing = session.query(Query).filter(
                Query.brand_id == brand.id,
                Query.query_id == q_data['query_id']
            ).first()
            if existing:
                continue

            query = Query(
                user_id=admin.id,
                brand_id=brand.id,
                query_id=q_data['query_id'],
                query_text=q_data['query_text'],
                category=q_data.get('category'),
                priority=q_data.get('priority'),
                target_outcome=q_data.get('target_outcome'),
                brand_in_query=q_data.get('brand_in_query', False),
                active=q_data.get('active', True),
                notes=q_data.get('notes'),
                created_at=parse_datetime(q_data.get('created_at')) or datetime.utcnow()
            )
            session.add(query)
            query_count += 1
        print(f"Imported {query_count} queries")

        # Import competitors
        comp_count = 0
        for c_data in data.get('competitors', []):
            # Check if competitor already exists
            existing = session.query(Competitor).filter(
                Competitor.brand_id == brand.id,
                Competitor.organization == c_data['organization']
            ).first()
            if existing:
                continue

            comp = Competitor(
                user_id=admin.id,
                brand_id=brand.id,
                organization=c_data['organization'],
                type=c_data.get('type'),
                focus_area=c_data.get('focus_area'),
                track=c_data.get('track', True),
                key_descriptors=c_data.get('key_descriptors'),
                website=c_data.get('website'),
                notes=c_data.get('notes')
            )
            session.add(comp)
            comp_count += 1
        print(f"Imported {comp_count} competitors")

        # Import descriptors
        desc_count = 0
        for d_data in data.get('descriptors', []):
            # Check if descriptor already exists
            existing = session.query(TargetDescriptor).filter(
                TargetDescriptor.brand_id == brand.id,
                TargetDescriptor.descriptor == d_data['descriptor']
            ).first()
            if existing:
                continue

            desc = TargetDescriptor(
                user_id=admin.id,
                brand_id=brand.id,
                descriptor=d_data['descriptor'],
                is_target=d_data.get('is_target', True),
                current_ownership=d_data.get('current_ownership'),
                priority=d_data.get('priority'),
                notes=d_data.get('notes')
            )
            session.add(desc)
            desc_count += 1
        print(f"Imported {desc_count} descriptors")

        # Import collection batches and build name->id mapping
        batch_name_to_id = {}
        batch_count = 0
        for b_data in data.get('collection_batches', []):
            # Check if batch already exists
            existing = session.query(CollectionBatch).filter(
                CollectionBatch.brand_id == brand.id,
                CollectionBatch.batch_name == b_data['batch_name']
            ).first()
            if existing:
                batch_name_to_id[b_data['batch_name']] = existing.id
                continue

            batch = CollectionBatch(
                user_id=admin.id,
                brand_id=brand.id,
                batch_name=b_data['batch_name'],
                description=b_data.get('description'),
                started_at=parse_datetime(b_data.get('started_at')) or datetime.utcnow(),
                completed_at=parse_datetime(b_data.get('completed_at')),
                status=b_data.get('status', 'completed'),
                total_queries=b_data.get('total_queries', 0),
                total_responses=b_data.get('total_responses', 0),
                platforms=b_data.get('platforms'),
                notes=b_data.get('notes')
            )
            session.add(batch)
            session.flush()  # Get the batch ID
            batch_name_to_id[b_data['batch_name']] = batch.id
            batch_count += 1
        print(f"Imported {batch_count} collection batches")

        # Import responses (the big one)
        response_count = 0
        skipped_responses = 0
        grounded_count = 0
        ungrounded_count = 0
        unknown_grounding_count = 0
        for r_data in data.get('responses', []):
            # Check for duplicate (same query, platform, timestamp)
            timestamp = parse_datetime(r_data.get('timestamp'))
            existing = session.query(Response).filter(
                Response.brand_id == brand.id,
                Response.query_id == r_data['query_id'],
                Response.platform == r_data['platform'],
                Response.timestamp == timestamp
            ).first()
            if existing:
                skipped_responses += 1
                continue

            # Get batch ID from name
            batch_id = None
            if r_data.get('batch_name'):
                batch_id = batch_name_to_id.get(r_data['batch_name'])

            response = Response(
                user_id=admin.id,
                brand_id=brand.id,
                batch_id=batch_id,
                query_id=r_data['query_id'],
                query_text=r_data.get('query_text'),
                platform=r_data['platform'],
                response_text=r_data['response_text'],
                timestamp=timestamp or datetime.utcnow(),
                # Analysis fields
                brand_mentioned=r_data.get('brand_mentioned'),
                brand_position=r_data.get('brand_position'),
                sentiment=r_data.get('sentiment'),
                descriptors=r_data.get('descriptors'),
                competitors=r_data.get('competitors'),
                sources=r_data.get('sources'),
                campaign_period=r_data.get('campaign_period'),
                notes=r_data.get('notes'),
                analyzed_at=parse_datetime(r_data.get('analyzed_at')),
                collected_grounded=resolve_grounded(
                    r_data.get('collected_grounded'), timestamp, grounded_from),
            )
            session.add(response)
            response_count += 1
            if response.collected_grounded is True:
                grounded_count += 1
            elif response.collected_grounded is False:
                ungrounded_count += 1
            else:
                unknown_grounding_count += 1

            # Commit in batches to avoid memory issues
            if response_count % 500 == 0:
                session.commit()
                print(f"  ... imported {response_count} responses")

        print(f"Imported {response_count} responses (skipped {skipped_responses} duplicates)")
        print(f"  Grounded: {grounded_count}, ungrounded: {ungrounded_count}, "
              f"unknown: {unknown_grounding_count}")
        if grounded_count and ungrounded_count:
            # Saying this at import time, once, is much cheaper than having
            # someone investigate the step change six weeks later and conclude
            # the brand's visibility genuinely jumped.
            print("  NOTE: this history spans a change in collection method. "
                  "Trend lines are not comparable across that boundary, and a "
                  "comparison straddling it will show a step that is method, "
                  "not reputation.")
        if unknown_grounding_count and not (grounded_count or ungrounded_count):
            print("  NOTE: how these responses were collected was not recorded. "
                  "Pass --grounded-from YYYY-MM-DD if the switch date is known.")

        # Import reports
        report_count = 0
        for r_data in data.get('reports', []):
            # Check if report already exists
            existing = session.query(Report).filter(
                Report.brand_id == brand.id,
                Report.title == r_data['title']
            ).first()
            if existing:
                continue

            report = Report(
                user_id=admin.id,
                brand_id=brand.id,
                title=r_data['title'],
                report_content=r_data['report_content'],
                report_type=r_data.get('report_type', 'monthly'),
                period_label=r_data.get('period_label'),
                start_date=parse_datetime(r_data.get('start_date')),
                end_date=parse_datetime(r_data.get('end_date')),
                total_responses=r_data.get('total_responses', 0),
                mention_rate=r_data.get('mention_rate'),
                google_doc_url=r_data.get('google_doc_url'),
                created_at=parse_datetime(r_data.get('created_at')) or datetime.utcnow()
            )
            session.add(report)
            report_count += 1
        print(f"Imported {report_count} reports")

        # Commit all changes
        session.commit()

        print(f"\n{'='*60}")
        print("IMPORT COMPLETE")
        print(f"{'='*60}")
        print(f"Brand: {brand.brand_name}")
        print(f"Owner: {admin.email}")
        print(f"\nThe brand is now available in Tales.")
        print("Log in and select this brand to view the imported data.")

    except Exception as e:
        session.rollback()
        print(f"\nERROR during import: {e}")
        raise
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Import brand data from a Tales export file"
    )
    parser.add_argument(
        "--file", "-f",
        required=True,
        help="JSON export file to import"
    )
    parser.add_argument(
        "--admin-email", "-a",
        required=True,
        help="Email of the admin user to assign data to"
    )
    parser.add_argument(
        "--grounded-from",
        metavar="YYYY-MM-DD",
        help=("Date the source deployment switched on web search grounding. "
              "Responses collected on or after it are marked grounded, earlier "
              "ones ungrounded. Only applied to responses whose export does not "
              "already record it. Omit and they stay unknown, which is the "
              "honest default: grounded and ungrounded answers measure "
              "different things, so guessing here would fabricate the "
              "provenance of the whole history.")
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview import without making changes"
    )

    args = parser.parse_args()
    grounded_from = None
    if args.grounded_from:
        try:
            grounded_from = datetime.strptime(args.grounded_from, "%Y-%m-%d")
        except ValueError:
            print(f"ERROR: --grounded-from must be YYYY-MM-DD, got {args.grounded_from!r}")
            sys.exit(1)

    import_brand_data(args.file, args.admin_email, args.dry_run, grounded_from)


if __name__ == "__main__":
    main()
