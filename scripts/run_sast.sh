#!/usr/bin/env bash
#
# Static analysis and dependency audit for TalesToGo.
#
#   ./scripts/run_sast.sh
#
# Exits non-zero if anything needs attention, so it can gate CI.
#
# The suppressions this relies on are deliberately narrow and documented at
# each site: bandit exclusions and skips live in pyproject.toml, and semgrep
# suppressions are inline "# nosemgrep: <rule-id>" comments with a reason.
# A clean run should mean "nothing to look at", not "we stopped looking".

set -uo pipefail
cd "$(dirname "$0")/.."

status=0
note() { printf '\n=== %s ===\n' "$1"; }
fail() { printf '  FAIL: %s\n' "$1"; status=1; }
pass() { printf '  ok: %s\n' "$1"; }

# Semgrep downloads its rulesets over HTTPS. On the PPPL network the Zscaler
# proxy intercepts TLS with a certificate Python does not trust, so the fetch
# dies with SSLCertVerificationError. Going direct works.
semgrep_direct() {
  env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy semgrep "$@"
}

SEMGREP_PACKS=(--config=p/python --config=p/javascript --config=p/secrets)
SQL_TEXT_RULE='python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text'

note "bandit (Python SAST)"
if bandit -c pyproject.toml -r app scripts -q; then
  pass "no findings"
else
  fail "bandit reported findings (see above)"
fi

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
if semgrep_direct scan "${SEMGREP_PACKS[@]}" --error --quiet --metrics=off app; then
  pass "no findings"
else
  fail "semgrep reported findings in app/"
fi

# Offline migration and maintenance scripts. These must issue raw DDL, which
# the SQLAlchemy ORM cannot express, so that one rule is dropped here. Every
# other rule (including secret detection) still applies.
note "semgrep (migrations/, scripts/, tests/ minus raw-SQL rule)"
if semgrep_direct scan "${SEMGREP_PACKS[@]}" --error --quiet --metrics=off \
     --exclude-rule "$SQL_TEXT_RULE" migrations scripts tests; then
  pass "no findings"
else
  fail "semgrep reported findings in offline scripts"
fi

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
if pip-audit -r requirements.txt "${pip_ignore[@]}"; then
  pass "no unaccepted vulnerabilities (accepted: ${PIP_ACCEPTED[*]})"
else
  fail "vulnerable Python dependencies"
fi

note "npm audit (frontend dependencies)"
# `npm audit` exits non-zero whenever any advisory exists, which under pipefail
# would fail the pipeline before the allowlist below is consulted. Swallow its
# status and let the filter decide.
if (cd frontend && { npm audit --json 2>/dev/null || true; } | python3 -c '
import json, sys
accepted = set(sys.argv[1:])
report = json.load(sys.stdin)
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
' "${NPM_ACCEPTED[@]}"); then
  pass "no unaccepted advisories"
else
  fail "unaccepted npm advisories (see docs/SECURITY_NOTES.md)"
fi

note "result"
if [ "$status" -eq 0 ]; then
  echo "  All scans clean."
else
  echo "  One or more scans need attention."
fi
exit "$status"
