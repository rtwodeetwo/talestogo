from pydantic import BaseModel, ConfigDict, EmailStr, Field
from typing import Optional, List
import datetime

# --- Tenant Schemas ---
class TenantBase(BaseModel):
    tenant_name: str
    subdomain: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = "#75C9C8"
    secondary_color: Optional[str] = "#665775"
    custom_domain: Optional[str] = None

class TenantCreate(TenantBase):
    pass

class TenantUpdate(BaseModel):
    tenant_name: Optional[str] = None
    subdomain: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    custom_domain: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class Tenant(TenantBase):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)


# --- LLM Provider Schemas ---
class LLMProviderBase(BaseModel):
    """Base schema for LLM provider configuration."""
    provider_key: str  # Unique identifier: "chatgpt", "claude", "gemini", "perplexity", "azure_openai"
    display_name: str  # Shown in UI: "ChatGPT", "Claude 3.5"
    api_type: str  # "openai", "anthropic", "google", "openai_compatible", "azure"
    model_name: str  # e.g., "gpt-4o", "claude-3-haiku-20240307"; for Azure, the deployment name
    api_endpoint: Optional[str] = None  # Custom endpoint for OpenAI-compatible / Azure resource URL
    env_var_name: Optional[str] = None  # Custom env var for non-default providers (e.g., "MISTRAL_API_KEY")
    api_version: Optional[str] = None  # Azure OpenAI api_version (e.g., "2024-10-21"); unused for other api_types
    bing_connection_name: Optional[str] = None  # Foundry project connection name for Bing Grounding
    color: str = "#666666"  # Hex color for charts
    sort_order: int = 0  # Display order in UI
    is_enabled: bool = True  # Whether to collect from this LLM
    use_for_analysis: bool = False  # Designate one LLM for response analysis
    supports_web_search: bool = False  # For State of the LLMs feature (Gemini/Perplexity)


class LLMProviderCreate(LLMProviderBase):
    """Schema for creating a new LLM provider."""
    tenant_id: Optional[int] = None  # Optional: assign to specific tenant


class LLMProviderUpdate(BaseModel):
    """Schema for updating an LLM provider."""
    provider_key: Optional[str] = None
    display_name: Optional[str] = None
    api_type: Optional[str] = None
    api_endpoint: Optional[str] = None
    model_name: Optional[str] = None
    env_var_name: Optional[str] = None  # Custom env var for non-default providers
    api_version: Optional[str] = None  # Azure OpenAI api_version
    bing_connection_name: Optional[str] = None  # Foundry project connection name for Bing Grounding
    color: Optional[str] = None
    sort_order: Optional[int] = None
    is_enabled: Optional[bool] = None
    use_for_analysis: Optional[bool] = None
    supports_web_search: Optional[bool] = None
    model_config = ConfigDict(extra='forbid')


class LLMProvider(LLMProviderBase):
    """Response schema for LLM provider."""
    id: int
    tenant_id: Optional[int] = None
    api_key_source: str = "environment"  # Always "environment" - keys come from env vars
    api_key_present: bool = False  # True if the provider's API key env var is actually set on the server
    resolved_env_var: Optional[str] = None  # Name of the env var the key is read from
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)


class LLMProviderTestRequest(BaseModel):
    """Schema for testing LLM provider connection."""
    test_prompt: str = "Hello, please respond with a brief greeting."


class LLMProviderTestResponse(BaseModel):
    """Response from testing LLM provider connection."""
    success: bool
    message: str
    response_preview: Optional[str] = None  # First 200 chars of response


class PlatformConfig(BaseModel):
    """Platform configuration for frontend charts."""
    key: str
    name: str
    color: str
    enabled: bool = True


class PlatformConfigResponse(BaseModel):
    """Response containing all configured platforms."""
    platforms: List[PlatformConfig]


# --- Query Schemas ---
class QueryBase(BaseModel):
    query_text: str
    category: Optional[str] = None
    priority: Optional[str] = None
    target_outcome: Optional[str] = None
    brand_in_query: bool = False
    active: bool = True
    notes: Optional[str] = None

class QueryCreate(QueryBase):
    query_id: Optional[str] = None  # Optional - will be auto-generated if not provided

class QueryUpdate(BaseModel):
    query_text: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    target_outcome: Optional[str] = None
    brand_in_query: Optional[bool] = None
    active: Optional[bool] = None
    notes: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class Query(QueryBase):
    query_id: str  # Required in the response
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- Response Schemas ---
class ResponseBase(BaseModel):
    query_id: str
    platform: str
    response_text: str
    query_text: Optional[str] = None

class ResponseCreate(ResponseBase):
    pass

class ResponseAnalysisInput(BaseModel):
    brand_mentioned: Optional[str] = None
    brand_position: Optional[str] = None
    sentiment: Optional[str] = None
    descriptors: Optional[str] = None
    competitors: Optional[str] = None
    sources: Optional[str] = None
    notes: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class Response(ResponseBase):
    id: int
    timestamp: datetime.datetime
    brand_mentioned: Optional[str] = None
    brand_position: Optional[str] = None
    sentiment: Optional[str] = None
    descriptors: Optional[str] = None
    competitors: Optional[str] = None
    sources: Optional[str] = None
    campaign_period: Optional[str] = None
    notes: Optional[str] = None
    analyzed_at: Optional[datetime.datetime] = None
    model_config = ConfigDict(from_attributes=True)

# --- Competitor Schemas ---
class CompetitorBase(BaseModel):
    organization: str
    type: Optional[str] = None
    focus_area: Optional[str] = None
    track: bool = True
    key_descriptors: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None

class CompetitorCreate(CompetitorBase):
    pass

class CompetitorUpdate(BaseModel):
    organization: Optional[str] = None
    type: Optional[str] = None
    focus_area: Optional[str] = None
    track: Optional[bool] = None
    key_descriptors: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class Competitor(CompetitorBase):
    id: int
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- TargetDescriptor Schemas ---
class TargetDescriptorBase(BaseModel):
    descriptor: str
    is_target: bool = True
    current_ownership: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None

class TargetDescriptorCreate(TargetDescriptorBase):
    pass

class TargetDescriptorUpdate(BaseModel):
    descriptor: Optional[str] = None
    is_target: Optional[bool] = None
    current_ownership: Optional[str] = None
    priority: Optional[str] = None
    notes: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class TargetDescriptor(TargetDescriptorBase):
    id: int
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- Campaign Schemas ---
class CampaignBase(BaseModel):
    campaign_name: str
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    status: Optional[str] = None
    target_narrative: Optional[str] = None
    key_messages: Optional[str] = None
    success_metrics: Optional[str] = None

class CampaignCreate(CampaignBase):
    pass

class CampaignUpdate(BaseModel):
    campaign_name: Optional[str] = None
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    status: Optional[str] = None
    target_narrative: Optional[str] = None
    key_messages: Optional[str] = None
    success_metrics: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class Campaign(CampaignBase):
    id: int
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)
    
# --- CitedSource Schemas ---
class CitedSourceBase(BaseModel):
    source_name: str
    source_type: Optional[str] = None
    authority_level: Optional[str] = None
    brand_coverage: Optional[str] = None
    last_cited: Optional[datetime.date] = None
    notes: Optional[str] = None

class CitedSourceCreate(CitedSourceBase):
    pass

class CitedSourceUpdate(BaseModel):
    source_name: Optional[str] = None
    source_type: Optional[str] = None
    authority_level: Optional[str] = None
    brand_coverage: Optional[str] = None
    last_cited: Optional[datetime.date] = None
    notes: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class CitedSource(CitedSourceBase):
    id: int
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- BatchAnalytics Schemas ---
class BatchAnalyticsBase(BaseModel):
    batch_id: int
    collection_date: datetime.datetime
    total_responses: int = 0
    mention_count: int = 0
    mention_rate: float = 0.0
    leader_count: int = 0
    featured_count: int = 0
    listed_count: int = 0
    not_mentioned_count: int = 0
    very_positive_count: int = 0
    positive_count: int = 0
    neutral_count: int = 0
    negative_count: int = 0
    very_negative_count: int = 0
    mixed_count: int = 0
    sov_data: Optional[str] = None
    descriptor_data: Optional[str] = None

class BatchAnalyticsCreate(BatchAnalyticsBase):
    pass

class BatchAnalytics(BatchAnalyticsBase):
    id: int
    user_id: int
    brand_id: int
    computed_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- Report Schemas ---
class ReportBase(BaseModel):
    title: str
    report_content: str
    report_type: str = 'monthly'  # 'monthly' or 'all_data'
    start_date: Optional[datetime.datetime] = None
    end_date: Optional[datetime.datetime] = None
    total_responses: int = 0
    mention_rate: Optional[float] = None
    google_doc_url: Optional[str] = None

class ReportCreate(ReportBase):
    pass

class ReportUpdate(BaseModel):
    title: Optional[str] = None
    google_doc_url: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class Report(ReportBase):
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- AnalysisHistory Schemas ---
class AnalysisHistoryBase(BaseModel):
    analysis_type: str
    executive_summary: Optional[str] = None
    recommendations: Optional[str] = None
    full_analysis_text: Optional[str] = None
    report_url: Optional[str] = None

class AnalysisHistoryCreate(AnalysisHistoryBase):
    pass

class AnalysisHistory(AnalysisHistoryBase):
    id: int
    timestamp: datetime.datetime
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- BrandInfo Schemas ---
class BrandInfoBase(BaseModel):
    brand_name: str
    website_url: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    strategic_messages: Optional[str] = None

class BrandInfoCreate(BrandInfoBase):
    pass

class BrandInfoUpdate(BaseModel):
    brand_name: Optional[str] = None
    website_url: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    strategic_messages: Optional[str] = None
    is_active: Optional[bool] = None
    model_config = ConfigDict(extra='forbid')

class BrandInfo(BrandInfoBase):
    id: int
    user_id: int
    is_active: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# Simple schema for listing brands
class BrandInfoList(BaseModel):
    id: int
    brand_name: str
    is_active: bool
    industry: Optional[str] = None
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- BrandShare Schemas ---
class BrandShareCreate(BaseModel):
    email: EmailStr  # Email of user to share with

class BrandShare(BaseModel):
    id: int
    brand_id: int
    user_id: int
    shared_by_user_id: int
    permission_level: str
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

class BrandShareWithUser(BaseModel):
    """BrandShare with user details for display"""
    id: int
    brand_id: int
    user_id: int
    user_email: str
    user_full_name: Optional[str] = None
    shared_by_user_id: int
    shared_by_email: str
    permission_level: str
    created_at: datetime.datetime

class BrandTransferRequest(BaseModel):
    """Request to transfer brand to another user"""
    email: EmailStr  # Email of user to transfer to

class BrandTransferResponse(BaseModel):
    """Response after transferring brand"""
    message: str
    brand_id: int
    brand_name: str
    new_owner_email: str
    new_owner_full_name: Optional[str] = None

# --- User/Auth Schemas ---
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    organization: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)

class GoogleLogin(BaseModel):
    token: str  # Google OAuth ID token

class MicrosoftLogin(BaseModel):
    token: str  # Microsoft OAuth ID token

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    organization: Optional[str] = None
    model_config = ConfigDict(extra='forbid')

class User(UserBase):
    id: int
    is_admin: bool
    is_active: bool
    is_invited: bool
    google_id: Optional[str] = None
    oauth_provider: Optional[str] = None
    picture_url: Optional[str] = None
    invitation_expires_at: Optional[datetime.datetime] = None
    tenant_id: Optional[int] = None
    last_login: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    user_id: Optional[int] = None


# --- Auth Configuration Schemas ---
class AuthConfig(BaseModel):
    """
    Public authentication configuration for the frontend.
    Tells the UI which auth methods are available and their client IDs.
    """
    local_auth_enabled: bool = True
    microsoft_auth_enabled: bool = False
    google_auth_enabled: bool = False
    microsoft_client_id: Optional[str] = None
    microsoft_authority: Optional[str] = None
    google_client_id: Optional[str] = None


class BrandingConfig(BaseModel):
    """
    Public branding configuration for lab-specific customization.
    """
    site_name: str = "Tales"
    site_logo_url: Optional[str] = None
    primary_color: str = "#003e60"
    secondary_color: str = "#75c9c8"
    admin_email: Optional[str] = None  # Public contact email shown in user-facing UI

class UserInvite(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    organization: Optional[str] = None

class UserAdminUpdate(BaseModel):
    """Schema for admin to update user status"""
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    model_config = ConfigDict(extra='forbid')

# --- Invitation Schemas ---
class InvitationCreate(BaseModel):
    """Schema for creating an invitation"""
    email: EmailStr
    full_name: str
    organization: Optional[str] = None
    tenant_id: Optional[int] = None  # Optional: assign to specific tenant, defaults to admin's tenant

class InvitationResponse(BaseModel):
    """Schema for invitation response with token"""
    email: EmailStr
    full_name: str
    invitation_token: str
    expires_at: Optional[datetime.datetime] = None
    invitation_url: str

class InvitationValidate(BaseModel):
    """Schema for validating invitation token"""
    email: EmailStr
    full_name: str
    expires_at: datetime.datetime

class InvitationAccept(BaseModel):
    """Schema for accepting invitation and setting password"""
    token: str
    password: str

# --- Task Status Schemas ---
class TaskStatus(BaseModel):
    id: int
    user_id: int
    brand_id: Optional[int] = None
    task_type: str
    status: str
    progress: int
    total_items: int
    processed_items: int
    message: Optional[str] = None
    error_message: Optional[str] = None
    process_id: Optional[int] = None
    started_at: datetime.datetime
    completed_at: Optional[datetime.datetime] = None
    updated_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# SITE CONFIGURATION SCHEMAS
# ============================================================================

class SiteConfigBase(BaseModel):
    """Base schema for site configuration settings."""
    site_url: Optional[str] = None  # Base URL for email links
    admin_email: Optional[str] = None  # Contact email shown in emails
    site_name: Optional[str] = None  # Application name (defaults to "TALES")


class SiteConfigUpdate(BaseModel):
    """Schema for updating site configuration."""
    site_url: Optional[str] = None
    admin_email: Optional[str] = None
    site_name: Optional[str] = None
    model_config = ConfigDict(extra='forbid')


class SiteConfig(SiteConfigBase):
    """Response schema for site configuration."""
    pass

