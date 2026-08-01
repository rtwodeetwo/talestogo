"""
Hand-derived expected values for the golden dataset. This file is the contract.

Every constant below was computed by hand from the composition documented in
tests/fixtures/golden_dataset.py, NOT by running the code under test. That is the
whole point: if the implementation and this file agree, the implementation is
right, because this file was never allowed to learn from it.

To re-check any number, read the arithmetic in the comment above it against the
bucket counts in the fixture docstring. No tooling required.

If a value here ever needs to change, the fixture changed. Update the fixture
docstring, redo the arithmetic by hand, and only then edit this file.
"""

# =============================================================================
# BATCH 1 (January 2026) -- canonical population is 40 rows
#
#   57 rows in the batch, minus:
#      9  branded (analyzed)          -- the question named the brand
#      6  unanalyzed                  -- 5 organic + 1 branded, no classifier verdict
#      1  off-enum ("Probably")       -- not a usable classification
#      1  orphan (Q999, no Query row) -- branded-ness undeterminable
#   = 40 analyzed, valid-enum, non-branded answers
# =============================================================================

B1_POPULATION = 40
B1_TOTAL_ROWS = 57
B1_BRANDED_EXCLUDED = 9
B1_UNANALYZED_EXCLUDED = 6
B1_INVALID_ENUM_EXCLUDED = 1
B1_ORPHAN_EXCLUDED = 1

# Mentions: 12 "Yes" + 10 "Indirect" = 22 of 40
# 22 / 40 = 0.55
B1_MENTION_RATE = 55.0
B1_MENTION_NUMERATOR = 22

# Direct only: 12 "Yes" of 40
# 12 / 40 = 0.30
B1_DIRECT_MENTION_RATE = 30.0

# Positive sentiment. Denominator is every "Yes" carrying a valid sentiment,
# branded queries INCLUDED: 12 organic + 8 branded = 20.
# Numerator: organic (3 Very Positive + 5 Positive) + branded (2 + 3) = 13.
# 13 / 20 = 0.65
B1_POSITIVE_SENTIMENT_RATE = 65.0
B1_SENTIMENT_POPULATION = 20

# Full sentiment breakdown over those same 20. Sums to 100.0 by construction.
#   Very Positive 3 + 2 = 5   -> 25.0
#   Positive      5 + 3 = 8   -> 40.0
#   Neutral       2 + 2 = 4   -> 20.0
#   Negative      1 + 1 = 2   -> 10.0
#   Mixed         1 + 0 = 1   ->  5.0
#   Very Negative 0 + 0 = 0   ->  0.0   (unreachable from the analysis prompt)
B1_SENTIMENT_DISTRIBUTION = {
    "Very Positive": 25.0,
    "Positive": 40.0,
    "Neutral": 20.0,
    "Mixed": 5.0,
    "Negative": 10.0,
    "Very Negative": 0.0,
}

# Positions across the 40: Leader 3, Top 3 2, Featured 4, Listed 7, Not Mentioned 24
B1_POSITION_COUNTS = {
    "Leader": 3, "Top 3": 2, "Featured": 4, "Listed": 7, "Not Mentioned": 24,
}
#   3/40 = 7.5 | 2/40 = 5.0 | 4/40 = 10.0 | 7/40 = 17.5 | 24/40 = 60.0
B1_POSITION_DISTRIBUTION = {
    "Leader": 7.5, "Top 3": 5.0, "Featured": 10.0, "Listed": 17.5,
    "Not Mentioned": 60.0,
}

# Leadership visibility: Leader 3 + Top 3 2 + Featured 4 = 9 of 40
# 9 / 40 = 0.225
B1_LEADERSHIP_VISIBILITY = 22.5

# Positioning average on the 1-5 scale, over all 40:
#   Leader        3 x 5 = 15
#   Top 3         2 x 4 =  8
#   Featured      4 x 3 = 12
#   Listed        7 x 2 = 14
#   Not Mentioned 24 x 1 = 24
#   total = 73;  73 / 40 = 1.825 -> 1.8
B1_POSITIONING_AVERAGE = 1.8
B1_POSITIONING_SCORE_TOTAL = 73

# Share of voice. Competitor mentions across ALL 40 organic answers:
#   MIT 10, UKAEA 6, Stepwise Analytics 2  = 18
# Denominator = 22 brand mentions + 18 competitor mentions = 40
#   brand   22 / 40 = 55.0
#   MIT     10 / 40 = 25.0
#   UKAEA    6 / 40 = 15.0
#   Stepwise 2 / 40 =  5.0
B1_SHARE_OF_VOICE = 55.0
B1_COMPETITOR_SHARE_OF_VOICE = {
    "MIT": 25.0, "UKAEA": 15.0, "Stepwise Analytics": 5.0,
}
B1_COMPETITOR_MENTION_COUNTS = {"MIT": 10, "UKAEA": 6, "Stepwise Analytics": 2}

# Descriptor match. 3 target descriptors (is_target=True); "legacy" is excluded
# because it is is_target=False.
#   "high-temperature plasma" -> found (also matches "High-Temperature Plasma"
#                                       case-insensitively)
#   "innovative"              -> found
#   "AI-driven"               -> never used
#   2 / 3 = 0.6666... -> 66.7
B1_DESCRIPTOR_MATCH_RATE = 66.7
B1_DESCRIPTOR_MATCHED = ["high-temperature plasma", "innovative"]

# Descriptor frequency, case-folded, over mentioned answers (Yes and Indirect):
#   "innovative"              4 on Yes + 3 on Indirect                = 6
#   "high-temperature plasma" 3 lowercase + 2 "High-Temperature ..."  = 5
#   "legacy"                                                          = 2
#   "High Temperature Plasma" (space variant, a DIFFERENT descriptor) = 2
# The space variant staying separate is intentional: case folding is a bug fix,
# punctuation folding would be a product decision. See METRIC_DEFINITIONS.md.
B1_DESCRIPTOR_FREQUENCY = {
    "innovative": 6,
    "high-temperature plasma": 5,
    "legacy": 2,
    "High Temperature Plasma": 2,
}

# Per-platform mention rates. Responses rotate ChatGPT/Claude/Gemini/Perplexity
# in insertion order, giving 10 organic answers each.
B1_PLATFORM_MENTION_RATES = {
    "ChatGPT": 60.0, "Claude": 60.0, "Gemini": 50.0, "Perplexity": 50.0,
}


# =============================================================================
# BATCH 2 (February 2026) -- 20 rows, all organic and analyzed
#
# This batch exists to show that "February 2026" is not one number. The same 20
# rows produce three different mention rates depending only on how the window is
# drawn, because two rows straddle a month boundary:
#   TZ_A 2026-02-01T02:30Z ("Yes") -- February in UTC, January 31 in Eastern
#   TZ_B 2026-03-01T04:00Z ("No")  -- March in UTC,    February 28 in Eastern
# =============================================================================

# All 20 rows: 10 "Yes" + 2 "Indirect" = 12 of 20
# 12 / 20 = 0.60      <- what a batch-scoped report measures
B2_MENTION_RATE_BY_BATCH = 60.0

# Eastern February = [2026-02-01 05:00Z, 2026-03-01 05:00Z)
# Drops TZ_A (January in Eastern), keeps TZ_B (February 28 in Eastern).
# 18 mid-February rows (9 Yes, 2 Indirect, 7 No) + TZ_B ("No") = 19 rows
# mentions = 9 + 2 = 11;  11 / 19 = 0.5789... -> 57.9
# This is what the user saw on screen, because the UI renders Eastern.
B2_MENTION_RATE_EASTERN_FEB = 57.9

# UTC February = [2026-02-01 00:00Z, 2026-03-01 00:00Z)
# Keeps TZ_A, drops TZ_B.
# 18 mid-February rows + TZ_A ("Yes") = 19 rows
# mentions = 9 + 1 + 2 = 12;  12 / 19 = 0.6315... -> 63.2
# This is what every current period boundary in the app computes.
B2_MENTION_RATE_UTC_FEB = 63.2

B2_POPULATION_BY_BATCH = 20
B2_POPULATION_EASTERN_FEB = 19
B2_POPULATION_UTC_FEB = 19


# =============================================================================
# BATCH 3 -- isolation canary, user 2 / brand 2
#
# Six all-"Yes" rows. Every brand-1 number above must be unchanged by them. A
# tenancy leak shows up as brand 1's mention rate rising toward these.
# =============================================================================

B3_POPULATION = 6
B3_MENTION_RATE = 100.0


# =============================================================================
# Export integrity
# =============================================================================

# openpyxl 3.1.5 slices cell values at the Excel limit (openpyxl/cell/cell.py:163)
# with no error and no marker. The fixture carries a 40,000-character body.
EXCEL_CELL_LIMIT = 32767
LONG_RESPONSE_LENGTH = 40000

# A vertical tab is in openpyxl's ILLEGAL_CHARACTERS_RE. One such row currently
# raises IllegalCharacterError inside wb.save(), which 500s the whole export
# rather than the single row.
CONTROL_CHAR_RESPONSE_COUNT = 1
