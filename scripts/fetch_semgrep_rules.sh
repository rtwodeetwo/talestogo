#!/usr/bin/env bash
#
# Download semgrep's rule packs to a local directory, for networks where
# semgrep cannot fetch them itself.
#
#   ./scripts/fetch_semgrep_rules.sh [directory]     # default: .semgrep-rules
#   SEMGREP_RULES_DIR=.semgrep-rules ./scripts/run_sast.sh
#
# Why this exists: on a network with a TLS-intercepting proxy, semgrep's own
# fetch dies with SSLCertVerificationError while curl succeeds, because curl
# trusts the interception certificate through the OS trust store and Python's
# bundled certifi does not.
#
# There is a second remedy, documented in docs/SECURITY_NOTES.md: append the
# chain taken off the wire to certifi's bundle and point REQUESTS_CA_BUNDLE at
# it. That keeps the registry as the source of rules. This script is the option
# that needs no per-machine trust setup, and it is the only one that works on a
# deployment which cannot reach semgrep.dev at all.
#
# The downloaded files are not committed: the point is to take semgrep's
# current rules, not to freeze a copy that quietly goes stale.

set -euo pipefail
cd "$(dirname "$0")/.."

DEST="${1:-.semgrep-rules}"
PACKS=(python javascript secrets)

mkdir -p "$DEST"

for pack in "${PACKS[@]}"; do
  url="https://semgrep.dev/c/p/${pack}"
  printf 'fetching %s ... ' "$url"
  # --noproxy is deliberate: on the PPPL network the configured proxy stalls
  # some hosts outright, and the interception happens transparently anyway.
  if curl -sSfL --noproxy '*' -H 'Accept: application/json' \
       "$url" -o "$DEST/${pack}.yaml"; then
    printf '%s bytes\n' "$(wc -c < "$DEST/${pack}.yaml" | tr -d ' ')"
  else
    printf 'FAILED\n' >&2
    exit 1
  fi
done

cat <<EOF

Rules written to $DEST/

Run the scans against them with:

  SEMGREP_RULES_DIR=$DEST ./scripts/run_sast.sh
EOF
