#!/usr/bin/env python3
"""
Response Collection Script for TALES Project
Queries the LLM platforms configured in Admin → LLM Providers and records responses.
"""

import os
import sys
from datetime import datetime
from typing import List, Dict, Optional
import time

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(override=True)

# Add project root to path for imports
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app import models, crud
from app.services.llm_provider_manager import LLMProviderManager, ProviderConfig
from app.services.generic_llm_client import GenericLLMClient, LLMAPIError, LLMConfigurationError

# Retrieval-only provider types — skipped during regular query collection.
COLLECTION_SKIP_TYPES = ("bing_v7",)


class ResponseCollector:
    """Collects responses from AI platforms."""

    def __init__(self, db: Session, user_id: int, brand_id: Optional[int] = None, task_status_id: Optional[int] = None):
        self.db = db
        self.user_id = user_id
        self.brand_id = brand_id
        self.task_status_id = task_status_id
        self.batch_id = None  # Will be set when collection starts

        # Load LLM providers from the database/env via the provider manager.
        user = db.query(models.User).filter(models.User.id == user_id).first()
        tenant_id = user.tenant_id if user else None

        self.provider_manager = LLMProviderManager(db, tenant_id)
        self.dynamic_providers: List[ProviderConfig] = self.provider_manager.get_enabled_providers()

        if not self.dynamic_providers:
            print(
                "⚠️  No LLM providers are enabled. Configure at least one in "
                "Admin → LLM Providers (and ensure its API key env var is set)."
            )
        else:
            source = "database" if self.provider_manager.is_using_database_providers() else "environment defaults"
            print(f"✓ Using {len(self.dynamic_providers)} LLM provider(s) from {source}")
            for p in self.dynamic_providers:
                print(f"  - {p.display_name} ({p.api_type})")

    def update_task_progress(self, processed: int, total: int, message: str = ""):
        """Update task status progress in database."""
        if not self.task_status_id:
            return

        try:
            task = self.db.query(models.TaskStatus).filter(
                models.TaskStatus.id == self.task_status_id
            ).first()

            if task:
                task.processed_items = processed
                task.total_items = total
                task.progress = int((processed / total) * 100) if total > 0 else 0
                if message:
                    task.message = message
                self.db.commit()
        except Exception as e:
            print(f"  Warning: Could not update task progress: {e}")

    def log_platform_error(self, platform: str, error_msg: str, query_text: str = ""):
        """Log platform API error to task status for debugging."""
        if not self.task_status_id:
            return

        try:
            task = self.db.query(models.TaskStatus).filter(
                models.TaskStatus.id == self.task_status_id
            ).first()

            if task:
                # Append error to existing error_message
                timestamp = datetime.utcnow().strftime("%H:%M:%S")
                new_error = f"[{timestamp}] {platform}: {error_msg}"
                if query_text:
                    new_error += f" (Query: {query_text[:50]}...)"

                if task.error_message:
                    task.error_message += f"\n{new_error}"
                else:
                    task.error_message = new_error

                self.db.commit()
        except Exception as e:
            print(f"  Warning: Could not log platform error: {e}")

    def query_with_provider(self, provider: ProviderConfig, query_text: str) -> Optional[str]:
        """
        Query an LLM using the GenericLLMClient with a configured provider.

        Providers flagged supports_web_search collect with fresh web search
        grounding so responses reflect what real users see in the consumer apps,
        not stale training data. Grounded answers cite recent events and are
        longer, so we give them a larger token budget. If a provider is flagged
        for web search but its api_type doesn't actually support grounding, we
        fall back to an ungrounded call rather than failing the query.
        """
        try:
            if provider.supports_web_search:
                try:
                    response_text = provider.call_with_web_search(
                        query_text, max_tokens=4096, temperature=0.7
                    )
                except LLMConfigurationError:
                    response_text = provider.call(query_text, max_tokens=1000, temperature=0.7)
            else:
                response_text = provider.call(query_text, max_tokens=1000, temperature=0.7)
            return response_text
        except LLMAPIError as e:
            error_msg = f"{provider.display_name} API error: {str(e)}"
            print(f"  ✗ {error_msg}")
            self.log_platform_error(provider.display_name, error_msg, query_text)
            return None
        except LLMConfigurationError as e:
            error_msg = f"{provider.display_name} configuration error: {str(e)}"
            print(f"  ✗ {error_msg}")
            self.log_platform_error(provider.display_name, error_msg, query_text)
            return None
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            error_msg = f"{provider.display_name} unexpected error: {type(e).__name__}: {e}\n{tb}"
            print(f"  ✗ {error_msg}")
            self.log_platform_error(provider.display_name, error_msg, query_text)
            return None

    def save_response(self, query_id: str, query_text: str, platform: str,
                     response_text: str) -> models.Response:
        """Save a response to the database."""
        # Sanitize for PostgreSQL: strip null bytes and invalid surrogates
        clean_text = response_text.replace("\x00", "").encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace") if response_text else response_text

        response = models.Response(
            user_id=self.user_id,
            brand_id=self.brand_id,
            batch_id=self.batch_id,
            query_id=query_id,
            query_text=query_text,
            platform=platform,
            response_text=clean_text,
            timestamp=datetime.utcnow()
        )
        self.db.add(response)
        self.db.commit()
        self.db.refresh(response)
        return response

    def collect_for_query(self, query: models.Query, platforms: List[str] = None) -> Dict[str, bool]:
        """Collect responses for a single query across configured providers."""
        results = {}
        print(f"\n📝 Query {query.query_id}: {query.query_text[:60]}...")

        if not self.dynamic_providers:
            print("  ✗ No LLM providers configured; skipping.")
            return results

        # If the caller passed a platforms filter, intersect by display_name.
        for provider in self.dynamic_providers:
            if not provider.is_enabled:
                continue
            if provider.api_type in COLLECTION_SKIP_TYPES:
                continue
            if platforms is not None and provider.display_name not in platforms:
                continue

            print(f"  → {provider.display_name}...", end=" ", flush=True)

            response_text = self.query_with_provider(provider, query.query_text)

            if response_text:
                self.save_response(query.query_id, query.query_text, provider.display_name, response_text)
                print(f"✓ ({len(response_text)} chars)")
                results[provider.display_name] = True
            else:
                print("✗ No response")
                results[provider.display_name] = False

            # Rate limiting - be nice to APIs
            time.sleep(1)

        return results

    def _mark_batch_failed(self, error_message: str):
        """Mark the current batch as failed with error details."""
        if not self.batch_id:
            return
        try:
            self.db.rollback()
            batch = self.db.query(models.CollectionBatch).filter(
                models.CollectionBatch.id == self.batch_id
            ).first()
            if batch and batch.status != 'completed':
                batch.status = 'failed'
                batch.completed_at = datetime.utcnow()
                self.db.commit()
        except Exception:
            pass

    def _mark_task_failed(self, error_message: str):
        """Mark the task status as failed with full error details."""
        if not self.task_status_id:
            return
        try:
            self.db.rollback()
            task = self.db.query(models.TaskStatus).filter(
                models.TaskStatus.id == self.task_status_id
            ).first()
            if task and task.status != 'completed':
                task.status = "failed"
                task.error_message = error_message
                task.completed_at = datetime.utcnow()
                self.db.commit()
        except Exception:
            pass

    def collect_all(self, limit: Optional[int] = None, platforms: List[str] = None) -> Dict[str, int]:
        """Collect responses for all active queries for this user and brand."""
        query = self.db.query(models.Query).filter(
            models.Query.user_id == self.user_id,
            models.Query.active == True
        )

        # Filter by brand_id if specified
        if self.brand_id:
            query = query.filter(models.Query.brand_id == self.brand_id)

        queries = query.all()

        if limit:
            queries = queries[:limit]

        # Determine platforms to use - dynamic providers take precedence
        # bing_v7 is retrieval-only (no LLM) — exclude from collection count.
        if self.dynamic_providers:
            platforms_list = [p.display_name for p in self.dynamic_providers if p.is_enabled and p.api_type not in COLLECTION_SKIP_TYPES]
        else:
            platforms_list = platforms or ['ChatGPT', 'Claude', 'Gemini', 'Perplexity']

        # Use session-based naming to ensure uniqueness and prevent midnight-crossing issues
        # The batch name includes both date and time to create a unique session identifier
        # Frontend will display this by start date in EST for user-friendly identification
        batch_start_time = datetime.utcnow()
        batch_name = f"Collection {batch_start_time.strftime('%Y-%m-%d %H:%M:%S')}"

        batch = models.CollectionBatch(
            user_id=self.user_id,
            brand_id=self.brand_id,
            batch_name=batch_name,
            description=f"Automated collection of {len(queries)} queries across {len(platforms_list)} platforms",
            platforms=', '.join(platforms_list),
            started_at=batch_start_time,
            status='in_progress',
            total_queries=0,
            total_responses=0
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        self.batch_id = batch.id

        print(f"\n{'='*60}")
        print(f"Response Collection Started")
        print(f"Batch ID: {self.batch_id} - {batch_name}")
        print(f"{'='*60}")
        print(f"Queries to process: {len(queries)}")
        print(f"Platforms: {platforms_list}")
        print(f"{'='*60}")

        # Initialize stats with dynamic platform names
        stats = {
            'total_queries': len(queries),
            'successful': 0,
            'failed': 0,
        }
        for platform_name in platforms_list:
            stats[platform_name] = 0

        # Calculate total items (queries × platforms)
        total_items = len(queries) * len(platforms_list)
        processed_count = 0

        try:
            for idx, query in enumerate(queries, 1):
                # Update progress before processing query
                self.update_task_progress(
                    processed_count,
                    total_items,
                    f"Collecting responses for query {idx}/{len(queries)}"
                )

                results = self.collect_for_query(query, platforms)

                if any(results.values()):
                    stats['successful'] += 1
                else:
                    stats['failed'] += 1

                for platform, success in results.items():
                    if success:
                        stats[platform] += 1
                    processed_count += 1

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            error_msg = (
                f"Collection crashed at query {processed_count}/{total_items}: "
                f"{type(e).__name__}: {e}\n\nTraceback:\n{tb}"
            )
            print(f"\n❌ {error_msg}", file=sys.stderr)
            self._mark_task_failed(error_msg)
            self._mark_batch_failed(error_msg)
            raise

        # Mark task as complete
        self.update_task_progress(total_items, total_items, "Collection completed")

        # Complete the batch - calculate total_responses from dynamic platforms
        total_responses = sum(stats.get(p, 0) for p in platforms_list)
        batch = self.db.query(models.CollectionBatch).filter(
            models.CollectionBatch.id == self.batch_id
        ).first()

        if batch:
            batch.completed_at = datetime.utcnow()
            batch.status = 'completed'
            batch.total_responses = total_responses
            batch.total_queries = stats['total_queries']
            self.db.commit()

        print(f"\n{'='*60}")
        print(f"Collection Summary")
        print(f"{'='*60}")
        print(f"  • Batch ID: {self.batch_id}")
        print(f"  • Total queries processed: {stats['total_queries']}")
        print(f"  • Total responses collected: {total_responses}")
        print(f"  • Successful: {stats['successful']}")
        print(f"  • Failed: {stats['failed']}")
        for platform_name in platforms_list:
            print(f"  • {platform_name} responses: {stats.get(platform_name, 0)}")
        print(f"{'='*60}\n")

        # Store batch_id in stats for auto-trigger use
        stats['batch_id'] = self.batch_id
        stats['total_responses'] = total_responses

        return stats


def main():
    """Main function to run response collection."""
    import argparse

    parser = argparse.ArgumentParser(description='TALES Response Collection Tool')
    parser.add_argument('user_id', type=int, nargs='?', help='User ID to collect responses for')
    parser.add_argument('--brand-id', type=int, help='Brand ID to collect responses for')
    parser.add_argument('--task-id', type=int, help='Task Status ID for progress tracking')
    args = parser.parse_args()

    print("\n🚀 TALES Response Collection Tool\n")

    # Get user_id from command line argument or prompt
    user_id = args.user_id
    brand_id = args.brand_id

    if user_id:
        print(f"Running collection for user_id: {user_id}")
        if brand_id:
            print(f"Brand ID: {brand_id}")
    else:
        # Interactive mode - show available users
        db_temp = SessionLocal()
        users = db_temp.query(models.User).filter(models.User.is_active == True).all()
        db_temp.close()

        if not users:
            print("❌ No active users found in database!")
            sys.exit(1)

        print("Available users:")
        for user in users:
            print(f"  {user.id}: {user.email} ({user.full_name or 'No name'})")

        user_input = input(f"\nEnter user_id [1]: ").strip() or "1"
        try:
            user_id = int(user_input)
        except ValueError:
            print("❌ Invalid user_id. Must be an integer.")
            sys.exit(1)

    # Sanity-check that at least one provider env var is set. The provider
    # manager will re-validate at construction time; this is just an early
    # friendly error before opening a DB connection.
    known_env_vars = [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
        "GOOGLE_API_KEY", "PERPLEXITY_API_KEY", "AZURE_OPENAI_API_KEY",
    ]
    if not any(os.getenv(v) for v in known_env_vars):
        print("\n❌ ERROR: No LLM provider API keys found in environment.")
        print("\nSet at least one of:")
        for v in known_env_vars:
            print(f"  {v}=...")
        print("\nThen configure the provider in Admin → LLM Providers.")
        sys.exit(1)

    print()

    # Create database session
    db = SessionLocal()
    collector = None

    try:
        # Verify user exists
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            print(f"❌ User with id {user_id} not found!")
            sys.exit(1)

        print(f"Collection for: {user.email} ({user.full_name or 'No name'})\n")

        # Initialize collector with user_id, brand_id, and task_id
        collector = ResponseCollector(db, user_id, brand_id, args.task_id)

        # Check if we have queries for this user/brand
        query_query = db.query(models.Query).filter(
            models.Query.user_id == user_id,
            models.Query.active == True
        )
        if brand_id:
            query_query = query_query.filter(models.Query.brand_id == brand_id)

        query_count = query_query.count()
        if query_count == 0:
            print("❌ No active queries found in database!")
            print("Please add queries through the web interface at http://localhost:5173/manage/queries")
            sys.exit(1)

        print(f"Found {query_count} active queries\n")

        # If running in automated mode (with task_id), skip interactive prompts
        limit = None
        if args.task_id:
            # Automated mode - always collect all queries
            print("Running in automated mode - collecting ALL queries")
        else:
            # Interactive mode - prompt for what to do
            print("Options:")
            print("  1. Collect responses for ALL queries (recommended for first run)")
            print("  2. Test with first 3 queries only")
            print("  3. Custom number of queries")

            choice = input("\nEnter choice (1-3) [1]: ").strip() or "1"

            if choice == "2":
                limit = 3
            elif choice == "3":
                limit = int(input("How many queries? "))

        # Collect responses
        stats = collector.collect_all(limit=limit)

        # Show next steps
        print("\n✅ Collection complete!")
        print("\nNext steps:")
        print("  1. View responses at http://localhost:5173/data/responses")
        print("  2. Analyze responses (coming soon)")
        print("  3. Check dashboard at http://localhost:5173/")

    except KeyboardInterrupt:
        print("\n\n⚠️  Collection interrupted by user")
        if collector:
            collector._mark_task_failed("Collection interrupted by user")
            collector._mark_batch_failed("Collection interrupted by user")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        error_msg = f"{type(e).__name__}: {e}\n\nTraceback:\n{tb}"
        print(f"\n❌ Collection failed: {error_msg}", file=sys.stderr)

        if collector:
            collector._mark_task_failed(error_msg)
            collector._mark_batch_failed(error_msg)

        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
