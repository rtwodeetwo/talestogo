#!/usr/bin/env python3
"""
Run every competing metric implementation side by side and report the spread.

This is the "before" column of the restatement table. It exists because the only
way to rebuild trust in the numbers is to show, concretely, how far apart the
current implementations are and which direction each one moves once they are
unified.

    python scripts/admin/metric_baseline.py                      # golden fixture
    python scripts/admin/metric_baseline.py --db sqlite:///x.db  # real data
    python scripts/admin/metric_baseline.py --json out.json

By default it runs against the deterministic fixture in
tests/fixtures/golden_dataset.py, where every canonical value is hand-derived in
tests/golden_expected.py, so the spread reported here can be checked by hand.

Point it at a real database with --db to produce the per-batch restatement table
for actual history. Nothing is written to the database in either mode.
"""
import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import models  # noqa: E402
from app.database import Base  # noqa: E402
from app.services import metrics_core as mc  # noqa: E402
from app.services import metrics_query as mq  # noqa: E402

UNAVAILABLE = "n/a"


def _safe(fn: Callable[[], Any]) -> Any:
    """Run a legacy implementation, recording failures instead of aborting.

    A legacy implementation that raises is itself a finding, so failures are
    recorded rather than aborting the comparison.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - reporting the failure is the point
        return f"ERROR: {type(exc).__name__}: {exc}"


def _pct(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value


# ============================================================ implementations

def collect_mention_rates(db, user_id: int, brand_id: int,
                          batch_id: Optional[int]) -> Dict[str, Any]:
    """Every mention-rate implementation, over the same rows."""
    from app import analytics as legacy_analytics
    from app.services import metrics as legacy_metrics
    from app.services.analytics_cache import AnalyticsCache
    from app.routers import highlights

    responses = _responses(db, user_id, brand_id, batch_id)
    queries = db.query(models.Query).filter(
        models.Query.user_id == user_id, models.Query.brand_id == brand_id
    ).all()
    non_branded = {q.query_id for q in queries if not q.brand_in_query}

    results: Dict[str, Any] = {}

    # app/analytics.py:78 -- Yes+Indirect over branded-excluded, rounded to int,
    # but with NO analyzed_at filter, so unanalyzed rows sit in the denominator.
    results["app/analytics.py:78"] = _safe(lambda: _pct(
        legacy_analytics.get_dashboard_metrics(
            db, user_id=user_id, brand_id=brand_id, batch_id=batch_id
        ).get("mention_rate")))

    # app/services/metrics.py:161 -- 'Yes' only, and the caller is expected to
    # pre-filter branded queries, which several callers did not.
    results["metrics.py:161 (Yes-only, unfiltered)"] = _safe(
        lambda: _pct(legacy_metrics.calculate_mention_metrics(responses).get("yes_pct")))
    results["metrics.py:161 (correctly pre-filtered)"] = _safe(lambda: _pct(
        legacy_metrics.calculate_mention_metrics(
            legacy_metrics.filter_exclude_branded_queries(responses, queries)
        ).get("yes_pct")))

    # app/services/batch_analytics.py:139 -- organic only, Yes+Indirect, int,
    # counts unanalyzed rows as not-mentioned.
    if batch_id is not None:
        results["batch_analytics.py:139 (stored)"] = _safe(lambda: _pct(
            _batch_analytics_rate(db, batch_id)))

    # app/services/analytics_cache.py:179 -- defaults to a 180-day window.
    results["analytics_cache.py:179"] = _safe(lambda: _pct(
        AnalyticsCache(db, user_id=user_id, brand_id=brand_id,
                       batch_id=batch_id).get_dashboard_data().get("mention_rate")))

    # app/routers/highlights.py -- migrated to metrics_core.
    results["highlights.py (migrated)"] = _safe(lambda: _pct(
        highlights._compute_mention_rate(
            _population(db, user_id, brand_id, batch_id))[2]))

    # app/routers/analytics.py:739 -- per-LLM chart, 'Yes' only.
    results["routers/analytics.py:739 (per-LLM, Yes only)"] = _safe(lambda: _pct(
        _yes_only_rate(responses, non_branded)))

    # The canonical definition.
    pop = _population(db, user_id, brand_id, batch_id)
    results["CANONICAL metrics_core.mention_rate"] = _pct(mc.mention_rate(pop).value)
    return results


def collect_sentiment_rates(db, user_id: int, brand_id: int,
                            batch_id: Optional[int]) -> Dict[str, Any]:
    from app import analytics as legacy_analytics
    from app.services import metrics as legacy_metrics
    from app.services.analytics_cache import AnalyticsCache

    responses = _responses(db, user_id, brand_id, batch_id)
    results: Dict[str, Any] = {}

    results["app/analytics.py:98"] = _safe(lambda: _pct(
        legacy_analytics.get_dashboard_metrics(
            db, user_id=user_id, brand_id=brand_id, batch_id=batch_id
        ).get("positive_sentiment")))

    results["metrics.py:317"] = _safe(lambda: _pct(
        legacy_metrics.calculate_positive_sentiment_rate(responses)))

    # The Yes-numerator over (Yes+Indirect)-denominator mismatch.
    results["analytics_cache.py:208"] = _safe(lambda: _pct(
        AnalyticsCache(db, user_id=user_id, brand_id=brand_id,
                       batch_id=batch_id).get_dashboard_data().get("positive_sentiment")))

    pop = _population(db, user_id, brand_id, batch_id)
    results["CANONICAL metrics_core.positive_sentiment_rate"] = _pct(
        mc.positive_sentiment_rate(pop).value)
    return results


def collect_share_of_voice(db, user_id: int, brand_id: int,
                           batch_id: Optional[int]) -> Dict[str, Any]:
    from app import analytics as legacy_analytics
    from app.services import metrics as legacy_metrics
    from app.services.analytics_cache import AnalyticsCache

    responses = _responses(db, user_id, brand_id, batch_id)
    queries = db.query(models.Query).filter(
        models.Query.user_id == user_id, models.Query.brand_id == brand_id).all()
    competitors = db.query(models.Competitor).filter(
        models.Competitor.user_id == user_id,
        models.Competitor.brand_id == brand_id).all()
    brand = db.query(models.BrandInfo).filter(models.BrandInfo.id == brand_id).first()
    brand_name = brand.brand_name if brand else ""

    results: Dict[str, Any] = {}

    # metrics.py:559 -- positioning-based, top-5 competitors only.
    results["metrics.py:559 (positioning-based)"] = _safe(lambda: _pct(
        legacy_metrics.calculate_share_of_voice(
            responses, queries, competitors, brand_name).get("brand_sov")))

    # app/analytics.py:566
    def _legacy_sov():
        rows = legacy_analytics.get_share_of_voice(db, user_id=user_id, brand_id=brand_id)
        for row in rows:
            if row.get("organization") == brand_name or row.get("is_brand"):
                return row.get("share_of_voice")
        return UNAVAILABLE
    results["app/analytics.py:566"] = _safe(lambda: _pct(_legacy_sov()))

    # analytics_cache.py:391 -- mention-based, competitors counted ONLY within
    # brand-mentioned responses, and no name normalization.
    results["analytics_cache.py:391 (mentioned-only denominator)"] = _safe(lambda: _pct(
        AnalyticsCache(db, user_id=user_id, brand_id=brand_id,
                       batch_id=batch_id).get_dashboard_data().get("share_of_voice")))

    pop = _population(db, user_id, brand_id, batch_id)
    results["CANONICAL metrics_core.share_of_voice"] = _pct(
        mc.share_of_voice(pop)[0].value)
    return results


def collect_positioning(db, user_id: int, brand_id: int,
                        batch_id: Optional[int]) -> Dict[str, Any]:
    from app.services import metrics as legacy_metrics
    from app.services.analytics_cache import AnalyticsCache

    responses = _responses(db, user_id, brand_id, batch_id)
    queries = db.query(models.Query).filter(
        models.Query.user_id == user_id, models.Query.brand_id == brand_id).all()

    results: Dict[str, Any] = {}

    # metrics.py:257 -- 1-4 scale, no 'Top 3' key, mentions-only denominator,
    results["metrics.py:257 (avg, 1-4 scale, int)"] = _safe(lambda:
        legacy_metrics.calculate_positioning_average(responses, queries))

    # metrics.py:489 -- Leader + Top 3 + Featured over all organic.
    results["metrics.py:489 (leadership visibility)"] = _safe(lambda: _pct(
        legacy_metrics.calculate_leadership_visibility(responses, queries)))

    # routers/analytics.py:268 -- what the Dashboard's trend ARROW uses.
    if batch_id is not None:
        results["routers/analytics.py:268 (leader only, the trend arrow)"] = _safe(
            lambda: _pct(_leader_only_pct(db, batch_id)))

    results["analytics_cache positioning"] = _safe(lambda:
        AnalyticsCache(db, user_id=user_id, brand_id=brand_id,
                       batch_id=batch_id).get_positioning_data().get("leading_position"))

    pop = _population(db, user_id, brand_id, batch_id)
    results["CANONICAL metrics_core.positioning_average (1-5)"] = mc.positioning_average(pop).value
    results["CANONICAL metrics_core.leadership_visibility"] = _pct(
        mc.leadership_visibility(pop).value)
    return results


def collect_descriptors(db, user_id: int, brand_id: int,
                        batch_id: Optional[int]) -> Dict[str, Any]:
    from app.services import metrics as legacy_metrics
    from app.services.analytics_cache import AnalyticsCache

    responses = _responses(db, user_id, brand_id, batch_id)
    all_descriptors = db.query(models.TargetDescriptor).filter(
        models.TargetDescriptor.user_id == user_id,
        models.TargetDescriptor.brand_id == brand_id).all()

    results: Dict[str, Any] = {}

    # metrics.py:419 -- exact match over 'Yes' only, is_target filtered.
    results["metrics.py:419 (exact, Yes only)"] = _safe(lambda: _pct(
        legacy_metrics.calculate_descriptor_match_rate(responses, all_descriptors)))

    # analytics_cache.py:283 -- bidirectional substring over Yes and Indirect.
    results["analytics_cache.py:283 (bidirectional substring)"] = _safe(lambda: _pct(
        AnalyticsCache(db, user_id=user_id, brand_id=brand_id,
                       batch_id=batch_id).get_dashboard_data().get("descriptor_match")))

    # metrics.py:389 -- case-SENSITIVE frequency counting.
    results["metrics.py:389 (case-sensitive frequency)"] = _safe(lambda:
        dict(sorted(legacy_metrics.analyze_descriptors(responses).items(),
                    key=lambda kv: -kv[1])))

    pop = _population(db, user_id, brand_id, batch_id)
    results["CANONICAL metrics_core.descriptor_match_rate"] = _pct(
        mc.descriptor_match_rate(pop).value)
    results["CANONICAL metrics_core.descriptor_frequency (case-folded)"] = \
        mc.descriptor_frequency(pop)
    return results


# ==================================================================== helpers

def _responses(db, user_id: int, brand_id: int, batch_id: Optional[int]):
    query = db.query(models.Response).filter(
        models.Response.user_id == user_id, models.Response.brand_id == brand_id)
    if batch_id is not None:
        query = query.filter(models.Response.batch_id == batch_id)
    return query.order_by(models.Response.id).all()


def _population(db, user_id: int, brand_id: int, batch_id: Optional[int]):
    if batch_id is not None:
        scope = mq.MetricScope.for_batch(user_id, brand_id, batch_id)
    else:
        scope = mq.MetricScope(user_id, brand_id)
    return mq.resolve(db, scope)


def _batch_analytics_rate(db, batch_id: int) -> Any:
    """Read the STORED row, never recompute.

    compute_batch_analytics commits (batch_analytics.py:166, :194), and a
    baseline tool pointed at production must not write. Reading what is stored is
    also the more honest measurement: BatchAnalytics is only written at batch
    completion (routers/batches.py:205-209) and is never refreshed when a query's
    brand_in_query flag changes or a response is re-analyzed, so the stored value
    is what the dashboard actually serves, staleness included.
    """
    row = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.batch_id == batch_id).first()
    if row is None:
        return "no stored row"
    return row.mention_rate


def _leader_only_pct(db, batch_id: int) -> Any:
    """Reproduces routers/analytics.py:266-268 without going through the route."""
    row = db.query(models.BatchAnalytics).filter(
        models.BatchAnalytics.batch_id == batch_id).first()
    if not row or not row.total_responses:
        return UNAVAILABLE
    return round((row.leader_count / row.total_responses) * 100)


def _yes_only_rate(responses, non_branded) -> Any:
    eligible = [r for r in responses if r.query_id in non_branded]
    if not eligible:
        return UNAVAILABLE
    return round(100.0 * sum(1 for r in eligible if r.brand_mentioned == "Yes")
                 / len(eligible), 1)


METRIC_GROUPS = {
    "mention_rate": collect_mention_rates,
    "positive_sentiment": collect_sentiment_rates,
    "share_of_voice": collect_share_of_voice,
    "positioning": collect_positioning,
    "descriptors": collect_descriptors,
}


def run_for_scope(db, user_id: int, brand_id: int, batch_id: Optional[int],
                  label: str) -> Dict[str, Any]:
    pop = _population(db, user_id, brand_id, batch_id)
    return {
        "label": label,
        "user_id": user_id,
        "brand_id": brand_id,
        "batch_id": batch_id,
        "data_quality": mc.data_quality(pop),
        "metrics": {name: fn(db, user_id, brand_id, batch_id)
                    for name, fn in METRIC_GROUPS.items()},
    }


# ===================================================================== output

def _spread(values: Dict[str, Any]) -> Optional[float]:
    numbers = [v for v in values.values() if isinstance(v, (int, float))]
    if len(numbers) < 2:
        return None
    return round(max(numbers) - min(numbers), 2)


def print_report(scopes: List[Dict[str, Any]]) -> None:
    for scope in scopes:
        print("=" * 78)
        print(f"  {scope['label']}   (user {scope['user_id']}, brand {scope['brand_id']}"
              f"{', batch ' + str(scope['batch_id']) if scope['batch_id'] else ''})")
        print("=" * 78)

        quality = scope["data_quality"]
        print(f"\n  Rows: {quality['total_rows']} total, {quality['counted']} counted")
        print(f"        excluded: {quality['branded_excluded']} branded, "
              f"{quality['unanalyzed_excluded']} unanalyzed, "
              f"{quality['invalid_enum_excluded']} off-enum, "
              f"{quality['orphan_query_excluded']} orphan")

        for metric_name, implementations in scope["metrics"].items():
            print(f"\n  {metric_name}")
            print("  " + "-" * 74)
            width = max(len(k) for k in implementations)
            for impl, value in implementations.items():
                marker = "->" if impl.startswith("CANONICAL") else "  "
                if isinstance(value, dict):
                    rendered = json.dumps(value)
                    if len(rendered) > 40:
                        rendered = rendered[:37] + "..."
                else:
                    rendered = str(value)
                print(f"  {marker} {impl.ljust(width)}  {rendered}")
            spread = _spread(implementations)
            if spread is not None and spread > 0:
                print(f"     {'SPREAD'.ljust(width)}  {spread} percentage points")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="SQLAlchemy URL. Omit to use the golden fixture.")
    parser.add_argument("--brand-id", type=int, help="limit to one brand")
    parser.add_argument("--json", help="also write the full result as JSON")
    args = parser.parse_args()

    if args.db:
        engine = create_engine(args.db)
        session_factory = sessionmaker(bind=engine)
        db = session_factory()
        source = args.db
    else:
        engine = create_engine(
            "sqlite:///file:metricbaseline?mode=memory&cache=shared&uri=true",
            connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        session_factory = sessionmaker(bind=engine)
        db = session_factory()
        from tests.fixtures.golden_dataset import (
            seed_batch_analytics, seed_golden_dataset,
        )
        seed_golden_dataset(db)
        db.commit()
        # Only on the in-memory fixture: gives the comparison a "what the app
        # stored" column. Never run against --db, which stays strictly read-only.
        seed_batch_analytics(db)
        source = "golden fixture (tests/fixtures/golden_dataset.py)"

    print(f"\nSource: {source}\n")

    try:
        brands = db.query(models.BrandInfo)
        if args.brand_id:
            brands = brands.filter(models.BrandInfo.id == args.brand_id)
        scopes: List[Dict[str, Any]] = []

        for brand in brands.order_by(models.BrandInfo.id).all():
            batches = db.query(models.CollectionBatch).filter(
                models.CollectionBatch.brand_id == brand.id
            ).order_by(models.CollectionBatch.started_at).all()
            for batch in batches:
                scopes.append(run_for_scope(
                    db, brand.user_id, brand.id, batch.id,
                    f"{brand.brand_name} / {batch.batch_name}"))
            scopes.append(run_for_scope(
                db, brand.user_id, brand.id, None, f"{brand.brand_name} / all data"))

        print_report(scopes)

        if args.json:
            with open(args.json, "w", encoding="utf-8") as handle:
                json.dump(scopes, handle, indent=2, default=str)
            print(f"Wrote {args.json}")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
