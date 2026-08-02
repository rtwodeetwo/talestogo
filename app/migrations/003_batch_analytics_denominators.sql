-- Migration: 003_batch_analytics_denominators.sql
-- Purpose: Let batch_analytics record the denominators its percentages imply
-- Created: 2026-08-01
--
-- Background
-- ----------
-- The August 2026 metric audit found that batch_analytics could not represent
-- the data it was summarising:
--
--   * 'Top 3' was never bucketed. compute_batch_analytics counted only Leader,
--     Featured and Listed, so a Top 3 response incremented mention_count but no
--     position bucket, and leader + featured + listed + not_mentioned did not
--     sum to total_responses. Every trend chart downstream inherited that.
--
--   * Unanalyzed responses were counted as "brand not mentioned". There was no
--     analyzed_at filter, so a failed analysis pass silently lowered the stored
--     mention rate with nothing to indicate it had happened.
--
--   * Sentiment percentages were computed as a Yes-only numerator over a
--     Yes+Indirect denominator, so the slices could not sum to 100.
--
-- The new columns let the table hold what it needs to be self-consistent:
-- top3_count closes the positioning sum, direct_mention_count gives sentiment
-- its correct denominator, and analyzed_count / unanalyzed_count / invalid_count
-- make the excluded rows visible rather than folding them into "not mentioned".
--
-- metrics_version tags rows written by the corrected implementation so a stale
-- row is distinguishable from a recomputed one.
--
-- All columns are nullable with no default beyond 0, so existing rows remain
-- readable after the migration.
--
-- No backfill is required. Existing rows keep metrics_version NULL, and
-- get_or_compute_batch_analytics treats any row whose metrics_version does not
-- match the current one as a miss, so stale rows are recomputed on next access
-- rather than served indefinitely. To force it for a whole brand up front, use
-- backfill_all_batch_analytics() or the admin recompute endpoint.
--
-- Safe to run on both SQLite and PostgreSQL: ALTER TABLE ... ADD COLUMN with a
-- constant default is supported by both.

ALTER TABLE batch_analytics ADD COLUMN top3_count INTEGER DEFAULT 0;

ALTER TABLE batch_analytics ADD COLUMN direct_mention_count INTEGER DEFAULT 0;

-- The sentiment counts divide by this, NOT by mention_count. It is a different
-- population from direct_mention_count: sentiment deliberately includes answers
-- to questions that named the brand (tone is meaningful there even though
-- visibility is not), and it excludes direct mentions carrying no sentiment
-- value. Storing it explicitly is what lets the sentiment slices sum to 100.
ALTER TABLE batch_analytics ADD COLUMN sentiment_base_count INTEGER DEFAULT 0;

ALTER TABLE batch_analytics ADD COLUMN analyzed_count INTEGER DEFAULT 0;

ALTER TABLE batch_analytics ADD COLUMN unanalyzed_count INTEGER DEFAULT 0;

ALTER TABLE batch_analytics ADD COLUMN invalid_count INTEGER DEFAULT 0;

ALTER TABLE batch_analytics ADD COLUMN metrics_version VARCHAR(16);
