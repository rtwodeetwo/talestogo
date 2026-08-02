#!/usr/bin/env python3
"""
Generate docs/METRIC_DEFINITIONS.md from the metrics_core docstrings.

The published methodology and the code have drifted apart before: app/routers/reports.py
documents a 1-5 positioning scale while POSITION_SCORES ran 1-4, and
frontend/src/pages/HowTalesWorks.tsx documents 1-4, all describing the same
function. Generating the doc from the source removes the opportunity.

    python scripts/admin/generate_metric_definitions.py [--check]

--check exits non-zero if the committed doc is stale, for CI.
"""
import argparse
import inspect
import os
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services import metrics_core as mc  # noqa: E402

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "docs", "METRIC_DEFINITIONS.md",
)

#: Order matters: this is the reading order for someone learning the system.
METRICS = [
    mc.mention_rate,
    mc.direct_mention_rate,
    mc.positive_sentiment_rate,
    mc.sentiment_distribution,
    mc.leadership_visibility,
    mc.positioning_distribution,
    mc.positioning_average,
    mc.share_of_voice,
    mc.descriptor_match_rate,
    mc.descriptor_frequency,
    mc.platform_mention_rates,
    mc.grounding_composition,
    mc.data_quality,
]


def _render() -> str:
    lines = [
        "# Tales Metric Definitions",
        "",
        "**Generated from `app/services/metrics_core.py`. Do not edit by hand.**",
        "Run `python scripts/admin/generate_metric_definitions.py` to refresh.",
        "",
        "Every number Tales reports is defined exactly once, here. If a dashboard",
        "tile, a CSV export, a generated report and a highlights email disagree about",
        "the same metric for the same period, one of them is not using these",
        "definitions and that is a bug.",
        "",
        "## Conventions",
        "",
        "- Percentages are reported to one decimal place. Values are computed in full",
        "  float and rounded once, at the presentation boundary.",
        "- An empty denominator yields no value at all, rendered as a dash. It is never",
        "  reported as `0.0`, because \"no data\" and \"genuinely zero\" are different facts.",
        "- Every metric reports its numerator and denominator alongside the rate, so any",
        "  figure can be checked against the underlying rows.",
        "",
        "## Vocabularies",
        "",
        f"- **Mention values**: {', '.join(f'`{v}`' for v in mc.MENTION_VALUES)}",
        f"- **Counted as mentioned**: {', '.join(f'`{v}`' for v in mc.MENTIONED_VALUES)}",
        f"- **Sentiment values**: {', '.join(f'`{v}`' for v in mc.SENTIMENT_VALUES)}",
        f"- **Positive sentiment**: {', '.join(f'`{v}`' for v in mc.POSITIVE_SENTIMENTS)}",
        f"- **Position values**: {', '.join(f'`{v}`' for v in mc.POSITION_VALUES)}",
        f"- **Counted as leadership**: {', '.join(f'`{v}`' for v in mc.LEADERSHIP_POSITIONS)}",
        "",
        "### Positioning scores",
        "",
        "| Position | Score |",
        "|---|---|",
    ]
    for position in mc.POSITION_VALUES:
        lines.append(f"| {position} | {mc.POSITION_SCORES[position]} |")
    lines += [
        "",
        "## Population selection",
        "",
        "Rows are loaded by `app/services/metrics_query.py` and tagged, not filtered.",
        "Each metric applies its own documented selection, so what a metric excludes is",
        "always visible rather than baked into the query.",
        "",
        "| Selection | Meaning |",
        "|---|---|",
        "| analyzed rows | the classifier returned a valid verdict and the query resolves |",
        "| organic rows | analyzed rows whose query does not contain the brand name |",
        "",
        "Excluded rows are counted and reported by `data_quality`, never silently folded",
        "into a negative result.",
        "",
        "## Metrics",
        "",
    ]

    for fn in METRICS:
        doc = inspect.getdoc(fn) or "(undocumented)"
        summary, _, body = doc.partition("\n\n")
        lines.append(f"### `{fn.__name__}`")
        lines.append("")
        lines.append(summary.strip())
        lines.append("")
        if body.strip():
            lines.append(textwrap.dedent(body).strip())
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the committed doc is stale")
    args = parser.parse_args()

    rendered = _render()

    if args.check:
        if not os.path.exists(OUTPUT_PATH):
            print(f"MISSING: {OUTPUT_PATH}", file=sys.stderr)
            return 1
        with open(OUTPUT_PATH, encoding="utf-8") as handle:
            if handle.read() != rendered:
                print(f"STALE: {OUTPUT_PATH} does not match metrics_core docstrings",
                      file=sys.stderr)
                return 1
        print(f"OK: {OUTPUT_PATH} is current")
        return 0

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
