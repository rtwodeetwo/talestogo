"""
The one tool that looks outside Tales' own database.

Everything else an investigation can call is deterministic and computed from
metrics_core. This is the exception: it asks a grounded provider what was
happening in the world during the window, so a drop can be attributed to a
competitor's announcement rather than left as "the number went down".

Two rules shape the whole module.

**A failed search is not an absence of news.** If every provider errors, the
agent must be told the check did not run, never handed an empty result that
reads like "nothing happened". `search_failed()` returns a payload the loop
marks as an error, and the run records a limitation.

**A missing key degrades the run, it does not fail it.** A deployment with no
grounded provider still gets a full internal investigation, plus an explicit
note saying external causes were not checked. That is why `limitations` is a
separate column from `error_message`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SEARCH_TOOL_NAME = "web_search"

SEARCH_SCOPES = ("brand", "industry", "competitor")

#: Ordered by how cheap and how recency-reliable each dialect is. Anthropic is
#: last on purpose: the agent loop itself is usually spending that key, and a
#: search should not compete with the reasoning budget.
_PROVIDER_PRIORITY = ("google", "openai_compatible", "bing_v7",
                      "azure_foundry_agents", "bing_grounded", "openai",
                      "azure", "anthropic")

SEARCH_UNAVAILABLE = {
    "limitation": ("External news search unavailable (no grounded provider "
                   "configured)"),
    "impact": ("External causes could not be checked. Conclusions rest on "
               "internal data only."),
}

SEARCH_FAILED = {
    "limitation": "External news search failed on every configured provider",
    "impact": ("External causes could not be checked. The absence of reported "
               "news in this investigation is not evidence that none occurred."),
}

#: Grounded answers are prose. Long enough to be useful, short enough that a
#: handful of searches does not crowd out the evidence.
SEARCH_MAX_TOKENS = 1500


def _ordered_providers(providers: List[Any]) -> List[Any]:
    priority = {api_type: i for i, api_type in enumerate(_PROVIDER_PRIORITY)}
    return sorted(providers, key=lambda p: (priority.get(p.api_type, 99),
                                            p.sort_order or 0))


def _build_prompt(scope: str, query: str, brand_name: str, industry: Optional[str],
                  window_label: str) -> str:
    """Turn the agent's question into a grounded-search prompt.

    The instruction to say so plainly when nothing turns up matters: without it
    a grounded model will pad an empty result into plausible-sounding
    background, and that padding would end up cited as a cause.
    """
    subject = {
        "brand": f"{brand_name}",
        "industry": f"the {industry or 'industry'} sector, in which {brand_name} operates",
        "competitor": f"organizations competing with {brand_name}",
    }.get(scope, brand_name)

    return (
        f"Search the web and answer this question about {subject}: {query}\n\n"
        f"The period of interest is {window_label}.\n\n"
        "Rules for your answer:\n"
        "- Report only what you actually found, with dates and source names.\n"
        "- If you find nothing relevant to the question and period, reply "
        "exactly: No relevant results found.\n"
        "- Do not speculate, and do not fill the answer with general background.\n"
        "- Be brief. A few sentences per item is enough."
    )


class WebSearch:
    """The agent's single external-search tool, across whatever is configured.

    One tool with a scope argument rather than three near-identical tools: the
    model picks the scope, and there is one code path to get right.
    """

    def __init__(self, manager, brand_name: str, industry: Optional[str],
                 window_label: str):
        self.brand_name = brand_name
        self.industry = industry
        self.window_label = window_label
        self._providers = _ordered_providers(manager.get_web_search_providers())
        self._analysis_provider = manager.get_analysis_provider()
        #: Set once every provider has failed. Retrying costs budget and fails
        #: again for the same infrastructure reason.
        self._exhausted = False

    @property
    def configured(self) -> bool:
        return bool(self._providers)

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    def limitation(self) -> Optional[Dict[str, str]]:
        """What to record about this run's external checking, if anything."""
        if not self.configured:
            return dict(SEARCH_UNAVAILABLE)
        if self._exhausted:
            return dict(SEARCH_FAILED)
        return None

    def run(self, scope: str, query: str) -> str:
        """Returns grounded prose, or raises SearchError.

        Raising rather than returning a message is deliberate: service.py turns
        an exception into a tool result flagged `is_error`, and that flag is the
        difference between "the search found nothing" and "the search did not
        happen".
        """
        if scope not in SEARCH_SCOPES:
            scope = "brand"
        if not query or not query.strip():
            raise SearchError("A search needs a query.")

        if not self.configured:
            raise SearchError(
                "No web-search provider is configured for this deployment, so "
                "external events cannot be checked. Do not treat this as "
                "evidence that nothing happened externally.")
        if self._exhausted:
            raise SearchError(
                "Web search already failed on every configured provider in this "
                "run and was not retried. External events remain unchecked.")

        prompt = _build_prompt(scope, query, self.brand_name, self.industry,
                               self.window_label)

        errors = []
        for provider in self._providers:
            try:
                text = provider.call_with_web_search(
                    prompt,
                    analysis_provider=self._analysis_provider,
                    max_tokens=SEARCH_MAX_TOKENS,
                )
            except Exception as exc:
                errors.append(f"{provider.provider_key}: {exc}")
                logger.warning("Investigation web search failed on %s: %s",
                               provider.provider_key, exc)
                continue

            # Google grounding can return an empty string without raising, and
            # an empty string handed back as a result reads as "no news".
            if text and text.strip():
                return text.strip()
            errors.append(f"{provider.provider_key}: returned an empty response")

        self._exhausted = True
        raise SearchError(
            "Web search failed on every configured provider: "
            + "; ".join(errors)
            + ". The external check did not run; this is not evidence that "
              "there was no news.")


class SearchError(RuntimeError):
    """The search did not run. Distinct from a search that found nothing."""
