#!/usr/bin/env bash
#
# Static analysis and dependency audit for TalesToGo.
#
#   ./scripts/run_sast.sh
#
# Exits non-zero if anything needs attention, so it can gate CI.
#
# A scan that COULD NOT RUN is reported separately from a scan that FOUND
# SOMETHING, and the two are never merged into one "FAIL". They mean opposite
# things: findings are work to do, an error is a gate that is not actually
# guarding anything. A security check that reports "problem" when it really
# means "I did not look" is worse than no check, because it trains everyone to
# ignore it. Both still fail the run; only the wording and the summary differ.
#
# The suppressions this relies on are deliberately narrow and documented at
# each site: bandit exclusions and skips live in pyproject.toml, and semgrep
# suppressions are inline "# nosemgrep: <rule-id>" comments with a reason.
# A clean run should mean "nothing to look at", not "we stopped looking".

set -uo pipefail
cd "$(dirname "$0")/.."

findings=0
errors=0
note() { printf '\n=== %s ===\n' "$1"; }
fail()  { printf '  FINDINGS: %s\n' "$1"; findings=1; }
error() { printf '  COULD NOT RUN: %s\n' "$1"; errors=1; }
pass()  { printf '  ok: %s\n' "$1"; }

# ---------------------------------------------------------------- semgrep
#
# By default the rule packs are fetched from semgrep's registry. On a network
# with a TLS-intercepting proxy that fetch fails, and no CA bundle fixes it (see
# scripts/fetch_semgrep_rules.sh for why). Set SEMGREP_RULES_DIR to a directory
# of downloaded packs to scan without touching the network.
SEMGREP_RULES_DIR="${SEMGREP_RULES_DIR:-}"

if [ -n "$SEMGREP_RULES_DIR" ]; then
  SEMGREP_PACKS=()
  for pack in python javascript secrets; do
    if [ -f "$SEMGREP_RULES_DIR/$pack.yaml" ]; then
      SEMGREP_PACKS+=(--config="$SEMGREP_RULES_DIR/$pack.yaml")
    fi
  done
  printf 'semgrep: using local rules from %s\n' "$SEMGREP_RULES_DIR"
else
  SEMGREP_PACKS=(--config=p/python --config=p/javascript --config=p/secrets)
fi

# Rule ids are prefixed with the config path when rules are loaded from files,
# so the same rule has two names depending on how it was loaded. Both are passed
# wherever the rule is named; an id that matches nothing is harmless.
SQL_TEXT_RULE='python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text'
SQL_TEXT_RULE_LOCAL="semgrep-rules.$SQL_TEXT_RULE"

# semgrep: 0 = clean, 1 = findings, >=2 = the scan itself failed.
run_semgrep() {
  local label="$1"; shift
  local output
  output=$(semgrep scan "$@" --metrics=off --error --quiet 2>&1)
  local code=$?
  case "$code" in
    0) pass "$label: no findings" ;;
    1) printf '%s\n' "$output"; fail "$label" ;;
    *) printf '%s\n' "$output" | tail -5
       error "$label: semgrep exited $code before scanning (rules could not be "\
"loaded, or the scan crashed). See scripts/fetch_semgrep_rules.sh." ;;
  esac
}

note "bandit (Python SAST)"
bandit_out=$(bandit -c pyproject.toml -r app scripts -q 2>&1)
bandit_code=$?
case "$bandit_code" in
  0) pass "no findings" ;;
  1) printf '%s\n' "$bandit_out"; fail "bandit reported findings" ;;
  *) printf '%s\n' "$bandit_out" | tail -10
     error "bandit exited $bandit_code without completing a scan" ;;
esac

# Belt and braces for the B404/B603 skips in pyproject.toml: those turn off the
# noisy "you imported subprocess" and "you called subprocess safely" checks, so
# confirm out-of-band that nobody introduced an actual shell invocation.
note "shell-injection guard"
if grep -rn --include='*.py' -E 'shell\s*=\s*True|os\.system\(' app scripts; then
  fail "shell invocation found in app/ or scripts/"
else
  pass "no shell=True or os.system() in app/ or scripts/"
fi

# app/ is the deployed request-handling surface: every rule, no exclusions.
note "semgrep (app/, all rules)"
run_semgrep "app/" "${SEMGREP_PACKS[@]}" app

# Offline migration and maintenance scripts. These must issue raw DDL, which
# the SQLAlchemy ORM cannot express, so that one rule is dropped here. Every
# other rule (including secret detection) still applies.
note "semgrep (migrations/, scripts/, tests/ minus raw-SQL rule)"
run_semgrep "offline scripts" "${SEMGREP_PACKS[@]}" \
  --exclude-rule "$SQL_TEXT_RULE" --exclude-rule "$SQL_TEXT_RULE_LOCAL" \
  migrations scripts tests

# Two advisories have no fixed release we can take. Both are documented, with
# the reachability argument, in docs/SECURITY_NOTES.md. They are listed here so
# that ANY OTHER advisory still fails the run. Re-check them when upgrading.
PIP_ACCEPTED=(PYSEC-2026-1325)          # ecdsa Minerva timing attack
NPM_ACCEPTED=(GHSA-qwww-vcr4-c8h2)      # react-router RSC-mode CSRF

# The free p/secrets pack turns out to miss plain assignments of AWS keys and
# PEM private keys (verified against planted samples), so don't rely on it.
# These patterns are high-signal enough to fail a build on.
note "committed-secret scan"
secret_re='AKIA[0-9A-Z]{16}'
secret_re+='|-----BEGIN [A-Z ]*PRIVATE KEY-----'
secret_re+='|gh[pousr]_[A-Za-z0-9]{20,}'
secret_re+='|xox[baprs]-[0-9A-Za-z-]{10,}'
secret_re+='|sk-[A-Za-z0-9_-]{20,}'
secret_re+='|AIza[0-9A-Za-z_-]{35}'
# Scan what would actually ship: files tracked by git, minus lockfiles.
if git ls-files -z -- . ':!*package-lock.json' ':!*.lock' \
     | xargs -0 grep -nIE "$secret_re" ; then
  fail "possible committed credential (see above)"
else
  pass "no credential patterns in tracked files"
fi

note "pip-audit (Python dependencies)"
pip_ignore=()
for v in "${PIP_ACCEPTED[@]}"; do pip_ignore+=(--ignore-vuln "$v"); done
pip_out=$(pip-audit -r requirements.txt "${pip_ignore[@]}" 2>&1)
pip_code=$?
printf '%s\n' "$pip_out"
if [ "$pip_code" -eq 0 ]; then
  pass "no unaccepted vulnerabilities (accepted: ${PIP_ACCEPTED[*]})"
elif printf '%s' "$pip_out" | grep -qiE 'connection|timed out|resolve|ssl|network'; then
  # An audit that could not reach its advisory database has not cleared
  # anything, and must not be read as "one vulnerable dependency".
  error "pip-audit could not reach the advisory database"
else
  fail "vulnerable Python dependencies"
fi

note "npm audit (frontend dependencies)"
# `npm audit` exits non-zero whenever any advisory exists, which under pipefail
# would fail the pipeline before the allowlist below is consulted. Swallow its
# status and let the filter decide.
npm_out=$(cd frontend && { npm audit --json 2>/dev/null || true; } | python3 -c '
import json, sys
accepted = set(sys.argv[1:])
try:
    report = json.load(sys.stdin)
except ValueError:
    # No parseable report means the audit did not run. Exit 2 so the caller can
    # tell that apart from "advisories were found".
    print("  npm audit produced no report")
    sys.exit(2)
found = set()
for vuln in report.get("vulnerabilities", {}).values():
    for src in vuln.get("via", []):
        if isinstance(src, dict) and src.get("url"):
            found.add(src["url"].rsplit("/", 1)[-1])
unexpected = sorted(found - accepted)
for advisory in unexpected:
    print("  unaccepted advisory: " + advisory)
still_accepted = sorted(found & accepted)
if still_accepted:
    print("  accepted, still present: " + ", ".join(still_accepted))
sys.exit(1 if unexpected else 0)
' "${NPM_ACCEPTED[@]}" 2>&1)
npm_code=$?
printf '%s\n' "$npm_out"
case "$npm_code" in
  0) pass "no unaccepted advisories" ;;
  1) fail "unaccepted npm advisories (see docs/SECURITY_NOTES.md)" ;;
  *) error "npm audit did not produce a report" ;;
esac

note "result"
if [ "$errors" -ne 0 ]; then
  echo "  One or more scans COULD NOT RUN. Nothing was cleared by them."
fi
if [ "$findings" -ne 0 ]; then
  echo "  One or more scans reported findings."
fi
if [ "$errors" -eq 0 ] && [ "$findings" -eq 0 ]; then
  echo "  All scans ran, all clean."
fi
[ "$errors" -eq 0 ] && [ "$findings" -eq 0 ]
