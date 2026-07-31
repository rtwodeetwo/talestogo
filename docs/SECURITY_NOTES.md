# Security Notes

How to run the scanners, and the short list of findings we have looked at and
decided not to act on.

The per-release results, including the raw pre-configuration counts, ship to
deployers in `deployment-kit/SECURITY.md`. That file is the record of what a
given release scanned clean against; this file is the methodology behind it.
When you change a suppression here, update that file too.

## Running the scans

```bash
./scripts/run_sast.sh
```

It runs bandit, semgrep, pip-audit and npm audit, and exits non-zero if any of
them reports something not on the accepted list below. Tools needed:

```bash
pip install bandit semgrep pip-audit
```

A clean run should mean "nothing to look at", not "we stopped looking". The
suppressions behind it are deliberately narrow:

- **bandit** exclusions and skips live in `pyproject.toml`, each with a comment.
  Note bandit only reads that file when passed `-c pyproject.toml`, which the
  script does. Running bare `bandit -r app scripts` ignores the config and
  produces about 70 findings that are all already accounted for.
- **semgrep** suppressions are inline `# nosemgrep: <rule-id>` comments next to
  the code, each with a reason. The marker has to sit on the line immediately
  above the finding; an explanatory comment in between silently breaks it.
- `app/` is scanned with every rule and no exclusions, because that is the
  deployed request-handling surface. `migrations/`, `scripts/` and `tests/` are
  scanned with the same rules minus `avoid-sqlalchemy-text`, since offline
  schema migrations have to issue raw DDL that the ORM cannot express.
- Secrets are caught by a separate pattern grep over git-tracked files, not by
  semgrep. The free `p/secrets` pack was tested against planted samples and
  missed a plain `AKIA...` assignment and a PEM private key, so it should not
  be trusted as the secret scanner. Semgrep also limits itself to files git
  knows about, which is why the grep uses `git ls-files` too.
- The bandit config skips B404 and B603, which flag importing `subprocess` and
  calling it *without* a shell (the safe form). The checks for the dangerous
  variants (B602 `shell=True`, B605 `os.system`, B607 partial paths) stay on,
  and the script separately greps for `shell=True` and `os.system(` so a
  regression cannot hide behind those two skips.

If you add a suppression, write down why next to it. If the reason is "it is
probably fine", that is not a suppression, that is an unfinished investigation.

Worth re-testing the suppressions occasionally by planting a vulnerability and
confirming the scanners still fail. Last checked: a raw-SQL injection in
`app/`, `shell=True`, `os.system()`, an AWS key and a PEM private key were all
still caught with the current configuration.

## Accepted findings

### ecdsa 0.19.2 — PYSEC-2026-1325 (Minerva timing attack)

**Not reachable.** `ecdsa` arrives transitively through
`python-jose[cryptography]`. The advisory affects ECDSA signing, key generation
and ECDH; signature *verification* is unaffected.

Tales signs and verifies its own JWTs with **HS256** (HMAC-SHA256, see
`app/auth.py`), and validates Microsoft/Entra ID tokens with **RS256** through
`pyjwt` backed by `cryptography`. No code path performs an ECDSA operation, so
the vulnerable functions are never called.

There is no fixed release. Upstream considers the affected API inherently
timing-sensitive. Re-check if Tales ever adopts an ES\* JWT algorithm, which
would make this immediately relevant.

### react-router — GHSA-qwww-vcr4-c8h2 (RSC mode CSRF bypass)

**Not reachable.** The advisory applies to React Router's **RSC (React Server
Components) mode**, where server actions can execute before a 400 response is
returned.

The Tales frontend is a client-only Vite SPA. It uses `BrowserRouter` with
declarative `Routes`/`Route` and the navigation hooks, has no server runtime,
no `react-router.config`, and does not use `createBrowserRouter`, RSC mode, or
server actions. The vulnerable code path does not exist in this build.

The advisory range is `7.12.0 - 8.2.0`. npm's only offered remediations are a
downgrade to 7.11.0 (a functional regression) or a jump to 8.x (a major
upgrade). We hold at the latest 7.x patch instead. Revisit when moving to
React Router 8, which resolves it directly.

## Fixed rather than suppressed

For the record, the following came out of the same review and were fixed in
code, not annotated away:

- `POST /migration/rollback-pending-shares` deleted. It ran `DELETE`, `ALTER
  TABLE` and `DROP COLUMN` against `brand_shares` behind nothing but
  `get_current_user`, so any authenticated user could break brand sharing. It
  was leftover migration scaffolding; the rollback still exists as
  `migrations/rollback_pending_shares.py` for operators with database access.
- The highlights cron secret is now compared with `hmac.compare_digest` instead
  of `!=`, so response latency does not leak it.
- CORS no longer allows `http://localhost:*` when `ENVIRONMENT=production`. The
  policy is credentialed, so a deployment should not accept credentialed
  requests from an origin it does not serve.
- Four `except: pass` blocks that swallowed every exception including
  `KeyboardInterrupt` now catch `Exception` and log, or were restructured away.
