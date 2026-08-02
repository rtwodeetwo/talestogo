import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, Float, Text, Date,
    MetaData, Table, create_engine, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
# Import Base from your database setup file
from .database import Base


# === Tenant Model (for multi-tenancy) ===
class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    tenant_name = Column(String(200), nullable=False)
    subdomain = Column(String(100), unique=True, nullable=True)
    logo_url = Column(Text, nullable=True)
    primary_color = Column(String(7), default='#75C9C8')
    secondary_color = Column(String(7), default='#665775')
    custom_domain = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

# === User Model (for authentication and multi-tenancy) ===
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)  # Nullable for OAuth users
    full_name = Column(String(200))
    organization = Column(String(200))  # The brand/org they're tracking (e.g., "PPPL", "MIT", etc.)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False)  # Must be approved by admin to use system
    is_invited = Column(Boolean, default=False)  # Has received invite email
    # Invitation fields
    invitation_token = Column(String(500), nullable=True, unique=True, index=True)  # JWT token for invite link
    invitation_expires_at = Column(DateTime, nullable=True)  # When the invitation expires
    # OAuth fields
    google_id = Column(String(255), unique=True, index=True, nullable=True)  # Google OAuth ID
    microsoft_id = Column(String(255), unique=True, index=True, nullable=True)  # Microsoft OAuth ID
    oauth_provider = Column(String(50), nullable=True)  # 'google', 'microsoft', etc.
    picture_url = Column(String(500), nullable=True)  # Profile picture URL from OAuth
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    last_login = Column(DateTime, nullable=True)  # Last successful login timestamp

class Query(Base):
    __tablename__ = "queries"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)  # Multi-brand support
    # Using String(10) assuming format like Q001 up to Q9999999
    query_id = Column(String(10), index=True, nullable=False)  # No longer globally unique - unique per user+brand
    query_text = Column(Text, nullable=False)
    category = Column(String(100))
    priority = Column(String(20)) # High, Medium, Low
    target_outcome = Column(Text)
    brand_in_query = Column(Boolean, default=False)  # True if brand name is IN the query text
    active = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Composite indexes for performance optimization
    __table_args__ = (
        Index('idx_query_brand_branded', 'brand_id', 'brand_in_query'),
        Index('idx_query_compound_lookup', 'query_id', 'user_id', 'brand_id'),
    )

class Response(Base):
    __tablename__ = "responses"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)  # Multi-brand support
    batch_id = Column(Integer, ForeignKey("collection_batches.id"), nullable=True, index=True)  # Collection batch tracking
    # No Foreign Key constraint, just index for faster lookups by query_id
    query_id = Column(String(10), index=True, nullable=False)
    query_text = Column(Text) # Denormalized
    platform = Column(String(100), index=True, nullable=False)
    response_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    # Analysis fields
    brand_mentioned = Column(String(10)) # Yes, No, Indirect
    brand_position = Column(String(20)) # Leader, Top 3, Featured, Listed, Not Mentioned
    sentiment = Column(String(20)) # Very Positive, Positive, Neutral, Negative, Mixed
    descriptors = Column(Text) # Comma-separated
    competitors = Column(Text) # Comma-separated
    sources = Column(Text) # Comma-separated
    campaign_period = Column(String(100))
    notes = Column(Text) # Analysis notes
    analyzed_at = Column(DateTime, nullable=True, index=True) # Index to quickly find unanalyzed

    # Composite indexes for performance optimization
    __table_args__ = (
        # Critical index for multi-tenant + multi-brand + batch filtering (used in every analytics query)
        Index('idx_response_user_brand_batch', 'user_id', 'brand_id', 'batch_id'),
        # For sentiment analysis queries that filter by both sentiment and brand_mentioned
        Index('idx_response_sentiment_mentioned', 'sentiment', 'brand_mentioned'),
        # For positioning breakdown queries
        Index('idx_response_position_mentioned', 'brand_position', 'brand_mentioned'),
        # For time-based queries with user filtering (trends, date ranges)
        Index('idx_response_timestamp_user', 'timestamp', 'user_id', 'brand_id'),
        # For JOIN operations with Query table on query_id lookups
        Index('idx_response_query_lookup', 'query_id', 'user_id', 'brand_id'),
    )

class Competitor(Base):
    __tablename__ = "competitors"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)  # Multi-brand support
    organization = Column(String(200), nullable=False, index=True)
    type = Column(String(100)) # National Lab, University, Private Company
    focus_area = Column(Text)
    track = Column(Boolean, default=True) # Include in SoV calcs?
    key_descriptors = Column(Text)
    website = Column(String(500))
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class TargetDescriptor(Base):
    __tablename__ = "target_descriptors"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)  # Multi-brand support
    descriptor = Column(String(200), nullable=False, index=True)
    is_target = Column(Boolean, default=True)
    current_ownership = Column(String(200)) # Who 'owns' this term now
    priority = Column(String(20)) # High, Medium, Low
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class CollectionBatch(Base):
    __tablename__ = "collection_batches"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)
    batch_name = Column(String(200), nullable=False)
    description = Column(Text)
    started_at = Column(DateTime, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default='in_progress')  # in_progress, completed, failed
    total_queries = Column(Integer, default=0)
    total_responses = Column(Integer, default=0)
    platforms = Column(Text)  # Comma-separated list of platforms used
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class BatchAnalytics(Base):
    """
    Cached analytics for each collection batch.
    Stores pre-computed metrics to avoid reprocessing responses.
    """
    __tablename__ = "batch_analytics"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=False, index=True)
    batch_id = Column(Integer, ForeignKey("collection_batches.id"), nullable=False, unique=True, index=True)

    # Collection date (from batch)
    collection_date = Column(DateTime, nullable=False, index=True)

    # Overall metrics. total_responses is the metric DENOMINATOR: analyzed,
    # valid-enum, non-branded responses. Rows excluded from it are counted
    # separately below rather than folded into not_mentioned_count.
    total_responses = Column(Integer, default=0)

    # Rows in the batch that never made it into total_responses, so a failed
    # collection or analysis pass is visible instead of looking like a drop in
    # brand visibility.
    analyzed_count = Column(Integer, default=0)
    unanalyzed_count = Column(Integer, default=0)
    invalid_count = Column(Integer, default=0)

    # Brand mentions (excluding brand_in_query responses)
    mention_count = Column(Integer, default=0)         # Yes + Indirect, organic
    direct_mention_count = Column(Integer, default=0)  # Yes only, organic
    mention_rate = Column(Float, default=0.0)

    # Positioning breakdown. These five must sum to total_responses; 'Top 3' was
    # missing before, so they could not.
    leader_count = Column(Integer, default=0)
    top3_count = Column(Integer, default=0)
    featured_count = Column(Integer, default=0)
    listed_count = Column(Integer, default=0)
    not_mentioned_count = Column(Integer, default=0)

    # Sentiment breakdown. These divide by sentiment_base_count, NOT by
    # mention_count. Different population: sentiment deliberately includes
    # answers to questions that named the brand, and excludes direct mentions
    # carrying no sentiment value. Dividing by mention_count (which includes
    # Indirect mentions that have no sentiment) is why the slices never summed
    # to 100 before.
    sentiment_base_count = Column(Integer, default=0)
    very_positive_count = Column(Integer, default=0)
    positive_count = Column(Integer, default=0)
    neutral_count = Column(Integer, default=0)
    negative_count = Column(Integer, default=0)
    very_negative_count = Column(Integer, default=0)
    mixed_count = Column(Integer, default=0)

    # Share of voice (JSON storing {org_name: count})
    sov_data = Column(Text, nullable=True)  # JSON string

    # Descriptor usage (JSON storing {descriptor: count})
    descriptor_data = Column(Text, nullable=True)  # JSON string

    # Metadata. metrics_version tags which definition wrote this row, so a stale
    # row left over from the pre-audit implementation is distinguishable from a
    # recomputed one.
    metrics_version = Column(String(16), nullable=True)
    computed_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)  # Multi-brand support
    campaign_name = Column(String(200), nullable=False, index=True)
    start_date = Column(Date)
    end_date = Column(Date)
    status = Column(String(50)) # Active, Completed, Planned
    target_narrative = Column(Text)
    key_messages = Column(Text)
    success_metrics = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class CitedSource(Base):
    __tablename__ = "cited_sources"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)  # Multi-brand support
    source_name = Column(String(200), nullable=False, index=True)
    source_type = Column(String(100)) # News, Academic, Official, Social, Reference
    authority_level = Column(String(20)) # High, Medium, Low
    brand_coverage = Column(Text) # Notes on quality of coverage
    last_cited = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

# Note: DashboardMetrics table is omitted - we'll calculate these on-demand or cache them.
# Storing them directly can lead to stale data unless updated rigorously.

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)  # Multi-brand support
    title = Column(String(200), nullable=False)
    report_content = Column(Text, nullable=False) # Full markdown content
    report_type = Column(String(20), nullable=False, default='monthly')  # 'monthly', 'quarterly', 'annual', or 'all_data'
    period_label = Column(String(100), nullable=True)  # e.g., "January 2026", "Q1 2026", "2025 Annual Report"
    start_date = Column(DateTime, nullable=True) # Analysis period start
    end_date = Column(DateTime, nullable=True) # Analysis period end
    total_responses = Column(Integer, default=0)
    mention_rate = Column(Float, nullable=True)
    google_doc_url = Column(String(500), nullable=True) # Export URL
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class AnalysisHistory(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    analysis_type = Column(String(50), nullable=False) # Full, ShareOfVoice, Campaign
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    # Storing report content directly for simplicity, could store URLs instead
    executive_summary = Column(Text)
    recommendations = Column(Text) # Might store as JSON later
    full_analysis_text = Column(Text) # The raw markdown from the LLM
    report_url = Column(String(500)) # Link to generated Google Doc
    # presentation_url = Column(String(500)) # Removed as per requirement
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Trend(Base):
    __tablename__ = "trends"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-tenancy
    # E.g., '2025-10-14' for week, '2025-10' for month
    period = Column(String(20), nullable=False, index=True)
    grouping = Column(String(10), nullable=False, index=True) # 'week' or 'month'
    mention_rate = Column(Float)
    share_of_voice = Column(Float)
    avg_visibility_score = Column(Float) # Numeric score 0-5
    sentiment_rate = Column(Float) # Pct positive
    descriptor_match_rate = Column(Float)
    response_count = Column(Integer)
    pppl_mention_count = Column(Integer)
    calculated_at = Column(DateTime, default=datetime.datetime.utcnow)
    # Add unique constraint for period+grouping+user_id if needed by DB
    # __table_args__ = (UniqueConstraint('period', 'grouping', 'user_id', name='uq_period_grouping_user'),)

class Configuration(Base):
    __tablename__ = "configuration"
    key = Column(String(100), primary_key=True)
    value = Column(Text)
    # encrypted = Column(Boolean, default=False) # Removed for simplicity with SQLite
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class LLMProvider(Base):
    """
    Configurable LLM provider for tenant deployments.

    Stores provider configuration (model, colors, etc.) for data collection,
    analysis, and report generation. Supports up to 6 LLMs per installation
    (4 default + 2 custom).

    API keys are read from environment variables, not stored in database.
    For default providers (ChatGPT, Claude, Gemini, Perplexity), keys come
    from standard env vars (OPENAI_API_KEY, etc.). Custom providers specify
    their env var name via the env_var_name column.
    """
    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)  # Nullable for global/default providers

    # Provider identification
    provider_key = Column(String(50), nullable=False)  # Unique identifier: "chatgpt", "claude", "gemini", "perplexity"
    display_name = Column(String(100), nullable=False)  # Shown in UI: "ChatGPT", "Claude 3.5"

    # API configuration
    api_type = Column(String(50), nullable=False)  # "openai", "anthropic", "google", "openai_compatible", "azure"
    api_endpoint = Column(String(500), nullable=True)  # Custom endpoint for OpenAI-compatible / Azure resource URL
    model_name = Column(String(100), nullable=False)  # e.g., "gpt-4o", "claude-3-haiku-20240307"; for Azure, this is the deployment name
    env_var_name = Column(String(100), nullable=True)  # Custom env var name for non-default providers (e.g., "MISTRAL_API_KEY")
    api_version = Column(String(50), nullable=True)  # Azure OpenAI api_version (e.g., "2024-10-21" or "2024-12-01-preview"); unused for other api_types
    bing_connection_name = Column(String(200), nullable=True)  # Foundry project connection name for Bing Grounding

    # Display settings
    color = Column(String(7), default="#666666")  # Hex color for charts
    sort_order = Column(Integer, default=0)  # Display order in UI

    # Feature flags
    is_enabled = Column(Boolean, default=True)  # Whether to collect from this LLM
    use_for_analysis = Column(Boolean, default=False)  # Designate one LLM for response analysis
    supports_web_search = Column(Boolean, default=False)  # For State of the LLMs feature (Gemini/Perplexity)

    # Metadata
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'provider_key', name='uq_tenant_provider_key'),
        Index('idx_llm_provider_tenant_enabled', 'tenant_id', 'is_enabled'),
    )


class BrandInfo(Base):
    __tablename__ = "brand_info"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Multi-brand support: user can have up to 20 brands
    brand_name = Column(String(200), nullable=False)
    website_url = Column(String(500), nullable=True)
    industry = Column(String(200), nullable=True)
    description = Column(Text, nullable=True)  # Brand blurb for analysis
    strategic_messages = Column(Text, nullable=True)  # Key messages/narratives you want people to say
    is_active = Column(Boolean, default=True)  # Which brand is currently active for the user
    fiscal_year_start_month = Column(Integer, nullable=False, default=1, server_default='1')  # 1, 4, 7, or 10; 1 = calendar year, 10 = US federal fiscal year. Drives quarter labels only.
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class BrandShare(Base):
    __tablename__ = "brand_shares"
    __table_args__ = (
        UniqueConstraint('brand_id', 'user_id', name='uq_brand_shares_brand_user'),
    )
    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brand_info.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)  # User being granted access
    shared_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # User who shared
    permission_level = Column(String(20), default='edit')  # 'edit' or 'view' (currently only 'edit' supported)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class TaskStatus(Base):
    __tablename__ = "task_status"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=True, index=True)
    task_type = Column(String(50), nullable=False)  # 'analysis', 'report_generation', 'collection'
    status = Column(String(20), nullable=False, index=True)  # 'running', 'completed', 'failed', 'cancelled'
    progress = Column(Integer, default=0)  # 0-100 percentage
    total_items = Column(Integer, default=0)  # Total items to process
    processed_items = Column(Integer, default=0)  # Items processed so far
    message = Column(Text, nullable=True)  # Current status message
    error_message = Column(Text, nullable=True)  # Error details if failed
    process_id = Column(Integer, nullable=True)  # Process ID for subprocess management
    started_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    brand_id = Column(Integer, ForeignKey("brand_info.id", ondelete="CASCADE"), nullable=False, index=True)

    # Collection schedule configuration
    collection_frequency = Column(String(20), nullable=False, default='monthly')  # 'weekly' or 'monthly'
    # DEPRECATED: schedule_type kept for backward compatibility during migration
    schedule_type = Column(String(20), nullable=True)  # 'first_day', 'middle', 'last_day' (legacy)
    is_enabled = Column(Boolean, default=True)
    timezone = Column(String(50), default='UTC')  # User's timezone

    # Collection execution tracking
    last_collection_at = Column(DateTime, nullable=True)
    next_collection_at = Column(DateTime, nullable=True, index=True)
    last_batch_id = Column(Integer, ForeignKey("collection_batches.id"), nullable=True)

    # Analysis execution tracking (analyses run after first collection of each period)
    last_monthly_analysis_at = Column(DateTime, nullable=True)
    last_quarterly_analysis_at = Column(DateTime, nullable=True)
    last_annual_analysis_at = Column(DateTime, nullable=True)

    # DEPRECATED: Legacy fields kept for migration (will be removed later)
    last_run_at = Column(DateTime, nullable=True)  # Use last_collection_at instead
    next_run_at = Column(DateTime, nullable=True)  # Use next_collection_at instead

    # Notification preferences
    send_email_notification = Column(Boolean, default=True)
    notification_email = Column(String(255), nullable=True)  # Optional override email

    # Metadata
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class ScheduledTaskHistory(Base):
    __tablename__ = "scheduled_task_history"
    id = Column(Integer, primary_key=True, index=True)
    scheduled_task_id = Column(Integer, ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    brand_id = Column(Integer, ForeignKey("brand_info.id"), nullable=False, index=True)

    # Execution details
    started_at = Column(DateTime, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'partial'

    # Results
    batch_id = Column(Integer, ForeignKey("collection_batches.id"), nullable=True)
    collection_responses = Column(Integer, default=0)
    analysis_responses = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# --- End of Models ---

# You can create the database file and tables by running this:
if __name__ == "__main__":
    from .database import engine # Import engine from database.py
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created (if they didn't exist).")