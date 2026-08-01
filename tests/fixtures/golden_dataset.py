"""
The golden dataset: a deterministic, hand-computable corpus for metric reconciliation.

Every value here is a literal. There is no randomness, no utcnow(), and no
dependence on the machine's timezone. That is what allows tests/golden_expected.py
to state each expected number as a constant with the arithmetic written out, and
for a human to check it with a calculator.

The composition is deliberate: each bucket below exists to expose one specific
divergence the August 2026 audit found. Do not "tidy" the counts. The odd numbers
are load-bearing.

================================================================================
BATCH 1 (January 2026), user 1, brand 1 -- 57 responses total
================================================================================

  Non-branded, analyzed, valid enum ...................... 40   <- the canonical denominator
      brand_mentioned = "Yes" .......................... 12
      brand_mentioned = "Indirect" ..................... 10
      brand_mentioned = "No" ........................... 18

  Non-branded, UNANALYZED (analyzed_at IS NULL) ..........  5   <- counted as "No" today
  Non-branded, analyzed, OFF-ENUM ("Probably") ...........  1   <- silently becomes "No" today
  ORPHAN (query_id Q999, no Query row) ...................  1   <- dropped by INNER JOIN today
  Branded (brand_in_query = True) ........................ 10
      analyzed, "Yes", valid sentiment ..................  8
      analyzed, "Yes", sentiment = None .................  1
      unanalyzed ........................................  1

  Positions across the 40 non-branded analyzed:
      Leader 3 | Top 3 2 | Featured 4 | Listed 7 | Not Mentioned 24   (= 40)
      ("Top 3" is present precisely because batch_analytics.py:98-103 drops it
       and POSITION_SCORES has no key for it.)

  Sentiment (only ever on brand_mentioned = "Yes"):
      organic Yes (12): Very Positive 3, Positive 5, Neutral 2, Negative 1, Mixed 1
      branded Yes  (8): Very Positive 2, Positive 3, Neutral 2, Negative 1
      Note: zero "Very Negative". That category is unreachable from the analysis
      prompt (analyze_responses.py:194-200) while six consumers count it, so the
      fixture reflects reality rather than papering over it.

  Competitor mentions across the 40 non-branded analyzed (18 total):
      MIT 10 | UKAEA 6 | Stepwise Analytics 2
      Placed 7 inside brand-mentioned responses and 11 inside "No" responses,
      so the analytics_cache.py:391 "competitors only from brand-mentioned rows"
      restriction produces a visibly different denominator.
      "Stepwise Analytics" exists to trip metrics.py:79, where the unanchored
      test `'step' in name_lower` rewrites it to "UKAEA".

  Descriptors (on Yes and Indirect rows):
      "high-temperature plasma" x3, "High-Temperature Plasma" x2  (case variants)
      "High Temperature Plasma" x2                                (space variant)
      "innovative" x4 on Yes, x3 on Indirect
      "legacy" x2                                                 (is_target = False)

================================================================================
BATCH 2 (February 2026), user 1, brand 1 -- 20 responses, all non-branded/analyzed
================================================================================

      brand_mentioned = "Yes" .......................... 10
      brand_mentioned = "Indirect" .....................  2
      brand_mentioned = "No" ...........................  8

  Two rows straddle a month boundary, which is the whole point of this batch:
      TZ_A  2026-02-01T02:30:00Z  ("Yes")  -> February in UTC, January 31 in Eastern
      TZ_B  2026-03-01T04:00:00Z  ("No")   -> March in UTC,    February 28 in Eastern
  The other 18 are stamped 2026-02-15T12:00:00Z, which is unambiguous in both.

================================================================================
BATCH 3, user 2, brand 2 -- 6 responses, all "Yes"
================================================================================

  Isolation canary. Every brand-1 metric must be unaffected by these rows. A
  tenancy leak (the brand_id-only filters at app/analytics.py:146-148,
  analytics_cache.py:379-381, highlights.py:139-142) shows up as brand 1's
  numbers moving.
"""
import datetime

from app import models

# ---------------------------------------------------------------- identifiers
USER_1_ID = 1
USER_2_ID = 2
BRAND_1_ID = 1
BRAND_2_ID = 2
BATCH_1_ID = 1
BATCH_2_ID = 2
BATCH_3_ID = 3

BRAND_1_NAME = "Golden Labs"
BRAND_2_NAME = "Other Labs"

NON_BRANDED_QUERY_IDS = ["Q001", "Q002", "Q003", "Q004", "Q005", "Q006", "Q007", "Q008"]
BRANDED_QUERY_IDS = ["QB01", "QB02"]
ORPHAN_QUERY_ID = "Q999"  # deliberately has no Query row

PLATFORMS = ["ChatGPT", "Claude", "Gemini", "Perplexity"]

# ------------------------------------------------------------------ timestamps
JAN_TS = datetime.datetime(2026, 1, 15, 12, 0, 0)
FEB_TS = datetime.datetime(2026, 2, 15, 12, 0, 0)
# Straddles the Jan/Feb boundary: February in UTC, January 31 21:30 in Eastern.
TZ_A_TS = datetime.datetime(2026, 2, 1, 2, 30, 0)
# Straddles the Feb/Mar boundary: March in UTC, February 28 23:00 in Eastern.
TZ_B_TS = datetime.datetime(2026, 3, 1, 4, 0, 0)
ANALYZED_TS = datetime.datetime(2026, 3, 5, 9, 0, 0)

# -------------------------------------------------------------- export stressors
# openpyxl silently slices cell values at 32767 characters (openpyxl/cell/cell.py:163).
LONG_RESPONSE_TEXT = "L" * 40000
# A vertical-tab is in openpyxl's ILLEGAL_CHARACTERS_RE and raises on save.
CONTROL_CHAR_RESPONSE_TEXT = "before\x0bafter"

# ------------------------------------------------------------------ descriptors
TARGET_DESCRIPTORS = ["high-temperature plasma", "innovative", "AI-driven"]
NON_TARGET_DESCRIPTORS = ["legacy"]

# ------------------------------------------------------------------ competitors
COMPETITOR_NAMES = ["MIT", "UKAEA", "Stepwise Analytics"]


def _rotate(seq, i):
    return seq[i % len(seq)]


class _ResponseBuilder:
    """Accumulates Response rows, assigning ids and rotating query/platform."""

    def __init__(self):
        self.rows = []
        self._next_id = 1
        self._q = 0
        self._p = 0

    def add(self, *, user_id, brand_id, batch_id, brand_mentioned,
            brand_position=None, sentiment=None, descriptors=None,
            competitors=None, timestamp=JAN_TS, analyzed=True,
            query_id=None, response_text=None, platform=None):
        if query_id is None:
            query_id = _rotate(NON_BRANDED_QUERY_IDS, self._q)
            self._q += 1
        if platform is None:
            platform = _rotate(PLATFORMS, self._p)
            self._p += 1

        row = models.Response(
            id=self._next_id,
            user_id=user_id,
            brand_id=brand_id,
            batch_id=batch_id,
            query_id=query_id,
            query_text=f"golden query {query_id}",
            platform=platform,
            response_text=response_text or f"golden response {self._next_id}",
            timestamp=timestamp,
            brand_mentioned=brand_mentioned,
            brand_position=brand_position,
            sentiment=sentiment,
            descriptors=descriptors,
            competitors=competitors,
            sources=None,
            campaign_period=None,
            notes=None,
            analyzed_at=ANALYZED_TS if analyzed else None,
        )
        self._next_id += 1
        self.rows.append(row)
        return row


def _build_batch_1(b):
    """The 57 rows of batch 1. See the module docstring for the composition."""

    # -- 12 non-branded "Yes" -------------------------------------------------
    # Positions: Leader 3, Top 3 2, Featured 3, Listed 4.
    # Sentiment: Very Positive 3, Positive 5, Neutral 2, Negative 1, Mixed 1.
    # Descriptors and competitors are attached here and on the Indirect rows.
    yes_spec = [
        # (position,        sentiment,        descriptors,                       competitors)
        ("Leader",          "Very Positive",  "high-temperature plasma, innovative", "MIT"),
        ("Leader",          "Very Positive",  "high-temperature plasma",         "MIT"),
        ("Leader",          "Very Positive",  "High-Temperature Plasma",         None),
        ("Top 3",           "Positive",       "high-temperature plasma, innovative", "UKAEA"),
        ("Top 3",           "Positive",       "High-Temperature Plasma, legacy", None),
        ("Featured",        "Positive",       "innovative",                      "MIT"),
        ("Featured",        "Positive",       "High Temperature Plasma",         None),
        ("Featured",        "Positive",       "High Temperature Plasma, legacy", "Stepwise Analytics"),
        ("Listed",          "Neutral",        None,                              "MIT"),
        ("Listed",          "Neutral",        None,                              "UKAEA"),
        ("Listed",          "Negative",       None,                              None),
        ("Listed",          "Mixed",          None,                              None),
    ]
    for position, sentiment, descriptors, competitors in yes_spec:
        b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
              brand_mentioned="Yes", brand_position=position, sentiment=sentiment,
              descriptors=descriptors, competitors=competitors)

    # -- 10 non-branded "Indirect" -------------------------------------------
    # Positions: Featured 1, Listed 3, Not Mentioned 6. No sentiment (per the
    # analysis prompt, sentiment is only assigned to direct mentions).
    indirect_spec = [
        ("Featured",      "innovative", None),
        ("Listed",        "innovative", None),
        ("Listed",        "innovative", None),
        ("Listed",        None,         None),
        ("Not Mentioned", None,         None),
        ("Not Mentioned", None,         None),
        ("Not Mentioned", None,         None),
        ("Not Mentioned", None,         None),
        ("Not Mentioned", None,         None),
        ("Not Mentioned", None,         None),
    ]
    for position, descriptors, competitors in indirect_spec:
        b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
              brand_mentioned="Indirect", brand_position=position,
              descriptors=descriptors, competitors=competitors)

    # -- 18 non-branded "No" --------------------------------------------------
    # All "Not Mentioned". 11 of the 18 competitor mentions live here, which is
    # what makes the analytics_cache.py:391 restriction visible.
    no_competitors = [
        "MIT", "MIT", "MIT", "MIT", "MIT", "MIT",
        "UKAEA", "UKAEA", "UKAEA", "UKAEA",
        "Stepwise Analytics",
        None, None, None, None, None, None, None,
    ]
    assert len(no_competitors) == 18
    for i, competitors in enumerate(no_competitors):
        # Two of these carry export-hostile bodies.
        if i == 16:
            text = LONG_RESPONSE_TEXT
        elif i == 17:
            text = CONTROL_CHAR_RESPONSE_TEXT
        else:
            text = None
        b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
              brand_mentioned="No", brand_position="Not Mentioned",
              competitors=competitors, response_text=text)

    # -- 5 non-branded UNANALYZED --------------------------------------------
    # brand_mentioned is NULL and analyzed_at is NULL. Today these land in
    # not_mentioned_count (batch_analytics.py:104-105) and in the denominator
    # (app/analytics.py:53-55), which silently depresses every mention rate.
    for _ in range(5):
        b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
              brand_mentioned=None, analyzed=False)

    # -- 1 non-branded OFF-ENUM ----------------------------------------------
    # There is no validation between the analysis LLM and the database
    # (analyze_responses.py:293-299), so a value like this can be written and
    # then silently fails every .in_(['Yes','Indirect']) filter downstream.
    b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
          brand_mentioned="Probably", brand_position="Listed")

    # -- 1 ORPHAN -------------------------------------------------------------
    # No Query row has query_id Q999, so the INNER JOIN at analytics_cache.py:91
    # drops it, the set-membership test at highlights.py:152 drops it, and
    # generate_report.py:394 keeps it. Three surfaces, three populations.
    b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
          brand_mentioned="No", brand_position="Not Mentioned",
          query_id=ORPHAN_QUERY_ID)

    # -- 10 BRANDED (brand_in_query = True) -----------------------------------
    # 8 analyzed with valid sentiment, 1 analyzed with no sentiment, 1 unanalyzed.
    branded_sentiments = [
        "Very Positive", "Very Positive",
        "Positive", "Positive", "Positive",
        "Neutral", "Neutral",
        "Negative",
    ]
    for i, sentiment in enumerate(branded_sentiments):
        b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
              brand_mentioned="Yes", brand_position="Featured", sentiment=sentiment,
              query_id=_rotate(BRANDED_QUERY_IDS, i))
    b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
          brand_mentioned="Yes", brand_position="Featured", sentiment=None,
          query_id=BRANDED_QUERY_IDS[0])
    b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_1_ID,
          brand_mentioned=None, analyzed=False, query_id=BRANDED_QUERY_IDS[1])


def _build_batch_2(b):
    """The 20 rows of batch 2, including the two month-boundary straddlers."""

    # TZ_A: February in UTC, January 31 in Eastern.
    b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_2_ID,
          brand_mentioned="Yes", brand_position="Leader", sentiment="Positive",
          timestamp=TZ_A_TS)
    # TZ_B: March in UTC, February 28 in Eastern.
    b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_2_ID,
          brand_mentioned="No", brand_position="Not Mentioned",
          timestamp=TZ_B_TS)

    # The unambiguous middle of February: 9 Yes, 2 Indirect, 7 No.
    for i in range(9):
        b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_2_ID,
              brand_mentioned="Yes",
              brand_position="Leader" if i < 2 else "Listed",
              sentiment="Positive" if i < 5 else "Neutral",
              timestamp=FEB_TS)
    for _ in range(2):
        b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_2_ID,
              brand_mentioned="Indirect", brand_position="Listed", timestamp=FEB_TS)
    for _ in range(7):
        b.add(user_id=USER_1_ID, brand_id=BRAND_1_ID, batch_id=BATCH_2_ID,
              brand_mentioned="No", brand_position="Not Mentioned", timestamp=FEB_TS)


def _build_batch_3(b):
    """Isolation canary: 6 all-"Yes" rows owned by a different user and brand."""
    for _ in range(6):
        b.add(user_id=USER_2_ID, brand_id=BRAND_2_ID, batch_id=BATCH_3_ID,
              brand_mentioned="Yes", brand_position="Leader",
              sentiment="Very Positive", descriptors="innovative",
              competitors="MIT", timestamp=JAN_TS)


def seed_golden_dataset(db):
    """Populate `db` with the golden dataset. Caller commits."""
    db.add_all([
        models.User(id=USER_1_ID, email="owner@golden.test", full_name="Golden Owner",
                    organization=BRAND_1_NAME, is_active=True, is_admin=False, is_invited=True),
        models.User(id=USER_2_ID, email="other@golden.test", full_name="Other Owner",
                    organization=BRAND_2_NAME, is_active=True, is_admin=False, is_invited=True),
    ])
    db.add_all([
        models.BrandInfo(id=BRAND_1_ID, user_id=USER_1_ID, brand_name=BRAND_1_NAME,
                         industry="fusion energy", description="Golden test brand",
                         is_active=True, fiscal_year_start_month=1),
        models.BrandInfo(id=BRAND_2_ID, user_id=USER_2_ID, brand_name=BRAND_2_NAME,
                         industry="fusion energy", description="Isolation canary brand",
                         is_active=True, fiscal_year_start_month=1),
    ])

    # Queries. Note there is deliberately NO row for ORPHAN_QUERY_ID.
    qid = 1
    for query_id in NON_BRANDED_QUERY_IDS:
        db.add(models.Query(id=qid, user_id=USER_1_ID, brand_id=BRAND_1_ID,
                            query_id=query_id, query_text=f"golden query {query_id}",
                            category="science", priority="High",
                            brand_in_query=False, active=True))
        qid += 1
    for query_id in BRANDED_QUERY_IDS:
        db.add(models.Query(id=qid, user_id=USER_1_ID, brand_id=BRAND_1_ID,
                            query_id=query_id,
                            query_text=f"what is {BRAND_1_NAME} known for",
                            category="science", priority="High",
                            brand_in_query=True, active=True))
        qid += 1
    # The canary brand needs the full set: _ResponseBuilder rotates query ids
    # across all batches, so batch 3 draws from anywhere in NON_BRANDED_QUERY_IDS.
    # Seeding only a couple would make its rows read as orphans.
    for query_id in NON_BRANDED_QUERY_IDS:
        db.add(models.Query(id=qid, user_id=USER_2_ID, brand_id=BRAND_2_ID,
                            query_id=query_id, query_text=f"canary query {query_id}",
                            category="science", priority="High",
                            brand_in_query=False, active=True))
        qid += 1

    # Target descriptors. "legacy" is is_target=False so the filter is testable.
    did = 1
    for descriptor in TARGET_DESCRIPTORS:
        db.add(models.TargetDescriptor(id=did, user_id=USER_1_ID, brand_id=BRAND_1_ID,
                                       descriptor=descriptor, is_target=True,
                                       priority="High"))
        did += 1
    for descriptor in NON_TARGET_DESCRIPTORS:
        db.add(models.TargetDescriptor(id=did, user_id=USER_1_ID, brand_id=BRAND_1_ID,
                                       descriptor=descriptor, is_target=False,
                                       priority="Low"))
        did += 1

    cid = 1
    for organization in COMPETITOR_NAMES:
        db.add(models.Competitor(id=cid, user_id=USER_1_ID, brand_id=BRAND_1_ID,
                                 organization=organization, type="National Lab",
                                 track=True))
        cid += 1

    db.add_all([
        models.CollectionBatch(id=BATCH_1_ID, user_id=USER_1_ID, brand_id=BRAND_1_ID,
                               batch_name="January 2026", started_at=JAN_TS,
                               completed_at=JAN_TS, status="completed",
                               total_queries=10, total_responses=57,
                               platforms=",".join(PLATFORMS)),
        models.CollectionBatch(id=BATCH_2_ID, user_id=USER_1_ID, brand_id=BRAND_1_ID,
                               batch_name="February 2026", started_at=FEB_TS,
                               completed_at=FEB_TS, status="completed",
                               total_queries=8, total_responses=20,
                               platforms=",".join(PLATFORMS)),
        models.CollectionBatch(id=BATCH_3_ID, user_id=USER_2_ID, brand_id=BRAND_2_ID,
                               batch_name="Canary batch", started_at=JAN_TS,
                               completed_at=JAN_TS, status="completed",
                               total_queries=2, total_responses=6,
                               platforms=",".join(PLATFORMS)),
    ])

    builder = _ResponseBuilder()
    _build_batch_1(builder)
    _build_batch_2(builder)
    _build_batch_3(builder)
    db.add_all(builder.rows)

    return builder.rows


def seed_batch_analytics(db):
    """Populate batch_analytics using the CURRENT implementation.

    This is deliberately not part of seed_golden_dataset. It represents "what the
    app stored", not ground truth, so it is opt-in and only the reconciliation
    surfaces ask for it. The canonical expectations in tests/golden_expected.py
    never depend on it.

    Note that compute_batch_analytics commits (app/services/batch_analytics.py:166,
    :194), which is safe here only because the golden database is in-memory.
    """
    from app.services.batch_analytics import compute_batch_analytics

    for batch_id, user_id, brand_id in (
        (BATCH_1_ID, USER_1_ID, BRAND_1_ID),
        (BATCH_2_ID, USER_1_ID, BRAND_1_ID),
        (BATCH_3_ID, USER_2_ID, BRAND_2_ID),
    ):
        compute_batch_analytics(db, batch_id, user_id, brand_id)
