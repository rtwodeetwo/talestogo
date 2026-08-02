#!/usr/bin/env python3
"""
Export brand data for migration to a new Tales deployment.

Usage:
    python scripts/admin/export_brand_data.py --brand "Princeton Plasma Physics Laboratory" --output pppl_data.json

This script exports all data associated with a brand:
- Brand configuration (name, description, aliases)
- Queries
- Competitors
- Descriptors
- Collection batches
- Responses with analysis data
- Reports

The output JSON can be imported into a fresh Tales deployment using import_brand_data.py
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.orm import defer, sessionmaker

from app.models import (
    BrandInfo, Query, Response, Competitor, TargetDescriptor,
    CollectionBatch, Report, User
)


def get_database_url():
    """Get database URL from environment or use default."""
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable not set")
        print("Set it to your production database connection string")
        sys.exit(1)
    return url


def serialize_datetime(obj):
    """JSON serializer for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def export_brand_data(brand_name: str, output_file: str):
    """Export all data for a brand to JSON."""

    # Connect to database
    database_url = get_database_url()
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Find the brand
        brand = session.query(BrandInfo).filter(
            BrandInfo.brand_name.ilike(f"%{brand_name}%")
        ).first()

        if not brand:
            print(f"ERROR: Brand '{brand_name}' not found")
            print("\nAvailable brands:")
            all_brands = session.query(BrandInfo).all()
            for b in all_brands:
                print(f"  - {b.brand_name} (ID: {b.id})")
            sys.exit(1)

        print(f"Found brand: {brand.brand_name} (ID: {brand.id})")

        # Get the brand owner info
        owner = session.query(User).filter(User.id == brand.user_id).first()
        owner_email = owner.email if owner else "unknown"

        # Export data structure
        export_data = {
            "export_info": {
                "exported_at": datetime.utcnow().isoformat(),
                "source_system": "Tales Production",
                "tales_version": "1.0.0",
                "brand_id": brand.id,
                "original_owner_email": owner_email
            },
            "brand": {
                "name": brand.brand_name,
                "website_url": brand.website_url,
                "industry": brand.industry,
                "description": brand.description,
                "strategic_messages": brand.strategic_messages
            },
            "queries": [],
            "competitors": [],
            "descriptors": [],
            "collection_batches": [],
            "responses": [],
            "reports": []
        }

        # Export queries
        queries = session.query(Query).filter(Query.brand_id == brand.id).all()
        print(f"Exporting {len(queries)} queries...")
        for q in queries:
            export_data["queries"].append({
                "query_id": q.query_id,
                "query_text": q.query_text,
                "category": q.category,
                "priority": q.priority,
                "target_outcome": q.target_outcome,
                "brand_in_query": q.brand_in_query,
                "active": q.active,
                "notes": q.notes,
                "created_at": q.created_at.isoformat() if q.created_at else None
            })

        # Export competitors
        competitors = session.query(Competitor).filter(Competitor.brand_id == brand.id).all()
        print(f"Exporting {len(competitors)} competitors...")
        for c in competitors:
            export_data["competitors"].append({
                "organization": c.organization,
                "type": c.type,
                "focus_area": c.focus_area,
                "track": c.track,
                "key_descriptors": c.key_descriptors,
                "website": c.website,
                "notes": c.notes
            })

        # Export descriptors
        descriptors = session.query(TargetDescriptor).filter(TargetDescriptor.brand_id == brand.id).all()
        print(f"Exporting {len(descriptors)} descriptors...")
        for d in descriptors:
            export_data["descriptors"].append({
                "descriptor": d.descriptor,
                "is_target": d.is_target,
                "current_ownership": d.current_ownership,
                "priority": d.priority,
                "notes": d.notes
            })

        # Export collection batches
        batches = session.query(CollectionBatch).filter(CollectionBatch.brand_id == brand.id).all()
        print(f"Exporting {len(batches)} collection batches...")
        batch_id_map = {}  # Map old batch IDs to batch names for responses
        for b in batches:
            batch_id_map[b.id] = b.batch_name
            export_data["collection_batches"].append({
                "batch_name": b.batch_name,
                "description": b.description,
                "started_at": b.started_at.isoformat() if b.started_at else None,
                "completed_at": b.completed_at.isoformat() if b.completed_at else None,
                "status": b.status,
                "total_queries": b.total_queries,
                "total_responses": b.total_responses,
                "platforms": b.platforms,
                "notes": b.notes
            })

        # Export responses (this is the big one)
        # This script is routinely pointed at an OLDER deployment's database in
        # order to migrate out of it, so a column this codebase knows about may
        # simply not be there. Asking for it anyway turns the whole export into
        # an "column does not exist" error. Defer what is missing instead, and
        # record the absence honestly as "unknown" rather than guessing a value.
        source_columns = {
            column["name"] for column in sa_inspect(engine).get_columns("responses")
        }
        has_grounded_column = "collected_grounded" in source_columns
        if not has_grounded_column:
            print("  Note: source database has no collected_grounded column; "
                  "responses will export with grounding unknown.")

        response_query = session.query(Response).filter(Response.brand_id == brand.id)
        if not has_grounded_column:
            response_query = response_query.options(defer(Response.collected_grounded))
        responses = response_query.all()
        print(f"Exporting {len(responses)} responses...")
        for r in responses:
            export_data["responses"].append({
                "query_id": r.query_id,
                "query_text": r.query_text,
                "platform": r.platform,
                "response_text": r.response_text,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "batch_name": batch_id_map.get(r.batch_id),
                # Analysis fields
                "brand_mentioned": r.brand_mentioned,
                "brand_position": r.brand_position,
                "sentiment": r.sentiment,
                "descriptors": r.descriptors,
                "competitors": r.competitors,
                "sources": r.sources,
                "campaign_period": r.campaign_period,
                "notes": r.notes,
                "analyzed_at": r.analyzed_at.isoformat() if r.analyzed_at else None,
                # None means "not recorded", which the importer must not read as
                # False. See --grounded-from in import_brand_data.py for how a
                # known switch date is applied to rows that predate the column.
                "collected_grounded": (
                    r.collected_grounded if has_grounded_column else None),
            })

        # Export reports
        reports = session.query(Report).filter(Report.brand_id == brand.id).all()
        print(f"Exporting {len(reports)} reports...")
        for r in reports:
            export_data["reports"].append({
                "title": r.title,
                "report_content": r.report_content,
                "report_type": r.report_type,
                "period_label": r.period_label,
                "start_date": r.start_date.isoformat() if r.start_date else None,
                "end_date": r.end_date.isoformat() if r.end_date else None,
                "total_responses": r.total_responses,
                "mention_rate": r.mention_rate,
                "google_doc_url": r.google_doc_url,
                "created_at": r.created_at.isoformat() if r.created_at else None
            })

        # Write to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, default=serialize_datetime, ensure_ascii=False)

        print(f"\n{'='*60}")
        print("EXPORT COMPLETE")
        print(f"{'='*60}")
        print(f"Brand: {brand.brand_name}")
        print(f"Queries: {len(export_data['queries'])}")
        print(f"Competitors: {len(export_data['competitors'])}")
        print(f"Descriptors: {len(export_data['descriptors'])}")
        print(f"Collection Batches: {len(export_data['collection_batches'])}")
        print(f"Responses: {len(export_data['responses'])}")
        print(f"Reports: {len(export_data['reports'])}")
        print(f"\nOutput: {output_file}")
        print(f"File size: {os.path.getsize(output_file) / 1024:.1f} KB")

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Export brand data for migration to a new Tales deployment"
    )
    parser.add_argument(
        "--brand", "-b",
        required=True,
        help="Brand name to export (partial match supported)"
    )
    parser.add_argument(
        "--output", "-o",
        default="brand_export.json",
        help="Output JSON file path (default: brand_export.json)"
    )

    args = parser.parse_args()
    export_brand_data(args.brand, args.output)


if __name__ == "__main__":
    main()
