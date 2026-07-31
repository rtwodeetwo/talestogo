# Security Scanning

Tales ships with its static analysis suite in the repository so you can verify
the code yourself rather than take this document's word for it.

## Results for Tales 2.0

Scanned 2026-07-31 against the 2.0 release.

| Scan | Tool | Result |
|------|------|--------|
| Python static analysis | bandit 1.9.4 | 0 findings |
| Pattern static analysis, `app/` | semgrep 1.172.0 | 0 findings |
| Pattern static analysis, offline scripts | semgrep 1.172.0 | 0 findings |
| Shell-injection guard | grep | no `shell=True`, no `os.system()` |
| Committed credentials | pattern scan over tracked files | none found |
| Python dependencies | pip-audit 2.10.0 | 0 unaccepted (1 accepted, below) |
| Frontend dependencies | npm audit (npm 11.13.0) | 0 unaccepted (1 accepted, below) |

Run on Python 3.13.13.

Two numbers are worth stating plainly, because "0 findings" is only meaningful
alongside what the tools reported before anything was configured:

- **bandit** reports 67 findings with no configuration at all, and every one of
  them is severity LOW. There are **no MEDIUM or HIGH findings** in this
  codebase whether or not you apply the project's configuration.
- **semgrep** reports 30 findings with no scoping, and **none of them are in
  `app/`**. All 30 are the `avoid-sqlalchemy-text` rule firing on offline
  database migration scripts, which have to issue raw DDL because the ORM
  cannot express `ALTER TABLE`.

The suppressions that take those to zero are narrow and individually
justified. `app/`, the code that actually handles web requests, is scanned with
every rule and no exclusions at all.

## Running the scans yourself

From a clone of the repository:

```bash
pip install bandit semgrep pip-audit
./scripts/run_sast.sh
```

It exits non-zero if anything fails, so it can gate a pipeline. Full
methodology, and the reasoning behind every suppression, is in
`docs/SECURITY_NOTES.md` in the repository.

If your network runs a TLS-intercepting proxy, semgrep's rule download may fail
certificate verification. The script already works around this by bypassing the
proxy for that one call.

## Known findings we have accepted

Both are dependency advisories with no fixed release available. Both were
checked for reachability rather than waved through, and both were re-verified
on 2026-07-31 as still having no fix published.

### ecdsa 0.19.2 (PYSEC-2026-1325, Minerva timing attack)

**Not reachable.** `ecdsa` is pulled in indirectly by `python-jose`. The
advisory affects ECDSA signing, key generation and ECDH. Signature
verification is unaffected.

Tales signs and verifies its own sessions with HS256 (HMAC-SHA256) and
validates Microsoft/Entra ID tokens with RS256 through `pyjwt` backed by
`cryptography`. No code path in Tales performs an ECDSA operation, so the
vulnerable functions are never called.

Upstream has published no fix and considers the affected API inherently
timing-sensitive.

### react-router (GHSA-qwww-vcr4-c8h2, RSC mode CSRF bypass)

**Not reachable.** The advisory applies to React Router's RSC (React Server
Components) mode, where a server action can run before a 400 response is
returned.

The Tales frontend is a browser-only single-page application. It has no server
runtime, does not use RSC mode, and does not define server actions. The
vulnerable code path is not present in the shipped build.

The advisory covers versions 7.12.0 through 8.2.0. The only remediations npm
offers are a downgrade to 7.11.0, which loses functionality, or a major upgrade
to 8.x. Tales holds at the latest 7.x patch release and will resolve this when
it moves to React Router 8.

## Reporting a vulnerability

If you find something, please contact the administrator address configured for
your deployment, or open an issue at
<https://github.com/rtwodeetwo/talestogo>.
