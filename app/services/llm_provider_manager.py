"""
LLM Provider Manager for Tales Project

Manages LLM providers for tenant deployments. API keys are always read from
environment variables, never stored in the database. Provider configuration
(model names, colors, enabled status) is stored in the database.
"""

import os
from typing import List, Dict, Optional
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app import models
from app.services.generic_llm_client import GenericLLMClient, LLMAPIError, LLMConfigurationError


# Standard mapping of api_type to environment variable name
API_TYPE_TO_ENV_VAR = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "openai_compatible": "PERPLEXITY_API_KEY",
    # Bing-backed web search (additive, used only for the State of the LLMs
    # report section). bing_v7 pairs with the configured analysis provider;
    # azure_foundry_agents uses Azure AI Foundry Prompt Agents with Bing Grounding.
    "bing_v7": "BING_SEARCH_V7_API_KEY",
    "azure_foundry_agents": "AZURE_AI_PROJECT_ENDPOINT",
    "bing_grounded": "AZURE_AI_PROJECT_ENDPOINT",  # backward compat alias
}


@dataclass
class ProviderConfig:
    """
    Provider configuration for LLM calls.

    API keys are looked up from environment variables at call time, not stored
    in this config. For default providers (ChatGPT, Claude, Gemini, Perplexity),
    the env var is determined by api_type. Custom providers specify env_var_name.
    """
    provider_key: str
    display_name: str
    api_type: str
    model_name: str
    api_endpoint: Optional[str] = None
    env_var_name: Optional[str] = None  # Custom env var for non-default providers
    api_version: Optional[str] = None  # Azure OpenAI api_version (e.g., "2024-10-21")
    bing_connection_name: Optional[str] = None  # Foundry project connection name for Bing Grounding
    color: str = "#666666"
    sort_order: int = 0
    is_enabled: bool = True
    use_for_analysis: bool = False
    supports_web_search: bool = False

    def _get_api_key(self) -> str:
        """Get API key from environment variable.

        Uses env_var_name if set, otherwise falls back to standard mapping based on api_type.
        """
        if self.env_var_name:
            return os.getenv(self.env_var_name, "")

        # Standard mapping for known api_types
        env_var = API_TYPE_TO_ENV_VAR.get(self.api_type, "")
        return os.getenv(env_var, "") if env_var else ""

    def has_api_key(self) -> bool:
        """Check if the API key is configured in environment.

        For azure_foundry_agents/bing_grounded, auth is via DefaultAzureCredential
        so we check for a configured endpoint instead of an API key.
        """
        if self.api_type in ("azure_foundry_agents", "bing_grounded"):
            return bool(self.api_endpoint)
        return bool(self._get_api_key())

    def call(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.7) -> str:
        """Call this provider with a prompt."""
        api_key = self._get_api_key()
        if not api_key and self.api_type not in ("azure_foundry_agents", "bing_grounded"):
            env_var = self.env_var_name or API_TYPE_TO_ENV_VAR.get(self.api_type, "UNKNOWN")
            raise LLMConfigurationError(f"API key not found in environment variable: {env_var}")

        return GenericLLMClient.call(
            api_type=self.api_type,
            api_key=api_key,
            model_name=self.model_name,
            prompt=prompt,
            api_endpoint=self.api_endpoint,
            api_version=self.api_version,
            max_tokens=max_tokens,
            temperature=temperature,
            bing_connection_name=self.bing_connection_name,
        )

    def call_with_web_search(
        self,
        prompt: str,
        analysis_provider: Optional["ProviderConfig"] = None,
    ) -> str:
        """Call this provider with web search grounding.

        For api_type=="bing_v7", an `analysis_provider` is required — Bing v7
        retrieves search results but does NOT synthesize them; the analysis
        provider writes the prose from those results. Other web-search
        api_types ignore the parameter.
        """
        api_key = self._get_api_key()
        if not api_key and self.api_type not in ("azure_foundry_agents", "bing_grounded"):
            env_var = self.env_var_name or API_TYPE_TO_ENV_VAR.get(self.api_type, "UNKNOWN")
            raise LLMConfigurationError(f"API key not found in environment variable: {env_var}")

        return GenericLLMClient.call_with_web_search(
            api_type=self.api_type,
            api_key=api_key,
            model_name=self.model_name,
            prompt=prompt,
            api_endpoint=self.api_endpoint,
            api_version=self.api_version,
            analysis_provider=analysis_provider,
            bing_connection_name=self.bing_connection_name,
        )


# Default provider configurations
# Used when no LLMProvider records exist in the database
DEFAULT_PROVIDERS = [
    {
        "provider_key": "chatgpt",
        "display_name": "ChatGPT",
        "api_type": "openai",
        "model_name": "gpt-4o",
        "color": "#10A37F",
        "sort_order": 0,
        "supports_web_search": False,
    },
    {
        "provider_key": "claude",
        "display_name": "Claude",
        "api_type": "anthropic",
        "model_name": "claude-haiku-4-5-20251001",
        "color": "#CC785C",
        "sort_order": 1,
        "supports_web_search": False,
    },
    {
        "provider_key": "gemini",
        "display_name": "Gemini",
        "api_type": "google",
        "model_name": "gemini-2.5-flash",
        "color": "#4285F4",
        "sort_order": 2,
        "supports_web_search": True,
        "use_for_analysis": True,  # Default analysis provider
    },
    {
        "provider_key": "perplexity",
        "display_name": "Perplexity",
        "api_type": "openai_compatible",
        "api_endpoint": "https://api.perplexity.ai",
        "model_name": "sonar",
        "color": "#1FB8CD",
        "sort_order": 3,
        "supports_web_search": True,
    },
    # Azure OpenAI is NOT in defaults: it requires api_endpoint (resource URL),
    # api_version, and a deployment name that are all tenant-specific. Admins
    # configure it explicitly via Admin → LLM Providers.
]


class LLMProviderManager:
    """
    Manages LLM providers for a tenant.

    Provides methods to get enabled providers, analysis provider, web search
    providers, and provider colors for frontend. API keys are always read from
    environment variables, never from the database.
    """

    def __init__(self, db: Session, tenant_id: Optional[int] = None):
        """
        Initialize the provider manager.

        Args:
            db: SQLAlchemy database session
            tenant_id: Optional tenant ID. If None, uses global providers or defaults.
        """
        self.db = db
        self.tenant_id = tenant_id
        self._providers_cache: Optional[List[ProviderConfig]] = None

    def _load_providers(self) -> List[ProviderConfig]:
        """
        Load providers from database or fall back to defaults.

        Priority order:
        1. If tenant has tenant-specific providers, use ONLY those
        2. If tenant has no tenant-specific providers, use global providers (tenant_id=None)
        3. If no database providers at all, fall back to DEFAULT_PROVIDERS

        Only includes providers whose API key is present in the environment.
        """
        if self._providers_cache is not None:
            return self._providers_cache

        db_providers = []

        if self.tenant_id is not None:
            # First, check if tenant has their own providers
            tenant_providers = self.db.query(models.LLMProvider).filter(
                models.LLMProvider.tenant_id == self.tenant_id,
                models.LLMProvider.is_enabled == True
            ).order_by(models.LLMProvider.sort_order).all()

            if tenant_providers:
                # Tenant has their own providers, use ONLY those (no global mixing)
                db_providers = tenant_providers
            else:
                # Tenant has no providers, fall back to global providers
                db_providers = self.db.query(models.LLMProvider).filter(
                    models.LLMProvider.tenant_id == None,
                    models.LLMProvider.is_enabled == True
                ).order_by(models.LLMProvider.sort_order).all()
        else:
            # No tenant specified, only get global providers
            db_providers = self.db.query(models.LLMProvider).filter(
                models.LLMProvider.tenant_id == None,
                models.LLMProvider.is_enabled == True
            ).order_by(models.LLMProvider.sort_order).all()

        if db_providers:
            # Use database providers
            self._providers_cache = []
            for p in db_providers:
                config = ProviderConfig(
                    provider_key=p.provider_key,
                    display_name=p.display_name,
                    api_type=p.api_type,
                    model_name=p.model_name,
                    api_endpoint=p.api_endpoint,
                    env_var_name=p.env_var_name,
                    api_version=p.api_version,
                    bing_connection_name=getattr(p, "bing_connection_name", None),
                    color=p.color or "#666666",
                    sort_order=p.sort_order or 0,
                    is_enabled=p.is_enabled,
                    use_for_analysis=p.use_for_analysis,
                    supports_web_search=p.supports_web_search,
                )
                # Only include providers with valid API keys in environment
                if config.has_api_key():
                    self._providers_cache.append(config)
        else:
            # Fall back to default providers
            self._providers_cache = self._get_default_providers()

        return self._providers_cache

    def _get_default_providers(self) -> List[ProviderConfig]:
        """Get default providers (only those with API keys configured in environment)."""
        providers = []

        for config in DEFAULT_PROVIDERS:
            provider = ProviderConfig(
                provider_key=config["provider_key"],
                display_name=config["display_name"],
                api_type=config["api_type"],
                model_name=config["model_name"],
                api_endpoint=config.get("api_endpoint"),
                env_var_name=None,  # Default providers use standard mapping
                api_version=config.get("api_version"),
                color=config.get("color", "#666666"),
                sort_order=config.get("sort_order", 0),
                is_enabled=True,
                use_for_analysis=config.get("use_for_analysis", False),
                supports_web_search=config.get("supports_web_search", False),
            )
            # Only include if API key is present in environment
            if provider.has_api_key():
                providers.append(provider)

        return providers

    def get_enabled_providers(self) -> List[ProviderConfig]:
        """
        Get all enabled LLM providers for data collection.

        Only returns providers whose API key is present in the environment.
        """
        return [p for p in self._load_providers() if p.is_enabled]

    def get_analysis_provider(self) -> Optional[ProviderConfig]:
        """
        Get the LLM designated for response analysis.

        Returns the provider with use_for_analysis=True, or the first
        available provider if none is designated.
        """
        providers = self._load_providers()

        # First, look for explicitly designated analysis provider
        for p in providers:
            if p.use_for_analysis and p.is_enabled:
                return p

        # Fall back to first enabled provider
        for p in providers:
            if p.is_enabled:
                return p

        return None

    def get_web_search_providers(self) -> List[ProviderConfig]:
        """
        Get providers that support web search, ordered by priority.

        Used for the State of the LLMs feature which requires fresh web search.
        Returns providers with supports_web_search=True.
        """
        return [
            p for p in self._load_providers()
            if p.supports_web_search and p.is_enabled
        ]

    def get_provider_by_key(self, provider_key: str) -> Optional[ProviderConfig]:
        """Get a specific provider by its key."""
        for p in self._load_providers():
            if p.provider_key == provider_key:
                return p
        return None

    def get_provider_colors(self) -> Dict[str, str]:
        """
        Get {display_name: color} mapping for frontend charts.

        Returns a dictionary mapping provider display names to their
        configured hex colors.
        """
        return {p.display_name: p.color for p in self._load_providers() if p.is_enabled}

    def get_platform_config(self) -> List[Dict]:
        """
        Get platform configuration for frontend.

        Returns list of dicts with key, name, color, enabled for each provider.
        """
        return [
            {
                "key": p.provider_key,
                "name": p.display_name,
                "color": p.color,
                "enabled": p.is_enabled,
            }
            for p in self._load_providers()
        ]

    def is_using_database_providers(self) -> bool:
        """Check if using database providers (vs default providers)."""
        if self.tenant_id is not None:
            # Check tenant-specific first, then global
            tenant_count = self.db.query(models.LLMProvider).filter(
                models.LLMProvider.tenant_id == self.tenant_id,
                models.LLMProvider.is_enabled == True
            ).count()

            if tenant_count > 0:
                return True

            # Check global providers
            global_count = self.db.query(models.LLMProvider).filter(
                models.LLMProvider.tenant_id == None,
                models.LLMProvider.is_enabled == True
            ).count()

            return global_count > 0
        else:
            # Only check global
            return self.db.query(models.LLMProvider).filter(
                models.LLMProvider.tenant_id == None,
                models.LLMProvider.is_enabled == True
            ).count() > 0

    def clear_cache(self):
        """Clear the providers cache to force reload."""
        self._providers_cache = None


def get_llm_provider_manager(db: Session, user: Optional[models.User] = None) -> LLMProviderManager:
    """
    Factory function to get an LLMProviderManager for a user.

    Args:
        db: SQLAlchemy database session
        user: Optional user to get tenant_id from

    Returns:
        LLMProviderManager configured for the user's tenant
    """
    tenant_id = user.tenant_id if user else None
    return LLMProviderManager(db, tenant_id)
