<!--
This file is the source for the Docker Hub overview page at
https://hub.docker.com/r/rtwodeetwo/tales

It is NOT synced automatically. Docker Hub requires a repo:admin token to edit
a repository description, and the publish workflow deliberately holds only a
repo:write token. When this file changes, paste it into the Docker Hub
repository settings by hand.

Short description (the one-line summary field):
  AI reputation monitoring: track how AI assistants represent your organization
-->

# Tales

Tales tracks how your organization is represented by AI assistants. It asks the
major AI platforms the questions people actually ask about your brand, records
the answers on a schedule, and analyzes them for mentions, sentiment,
positioning, competitors, and descriptive language.

**Source:** https://github.com/rtwodeetwo/talestogo
**License:** MIT

## Platform

This image is built for **`linux/amd64` only**.

On an ARM host (AWS Graviton, Ampere, Apple Silicon) `docker compose up` will
fail with a manifest error rather than starting. ARM deployments are still
supported: clone the repository and build from source with
`docker compose up -d --build`, which produces an image for whatever
architecture you build on. If you need a published ARM image, open an issue on
GitHub and one can be added.

## Tags

| Tag | What it is |
|---|---|
| `latest` | The most recent tagged release. What you want unless you know otherwise. |
| `2.0.1`, `2.0` | Specific releases. Pin one of these if you need to know exactly what you deployed. |
| `edge` | The tip of `main`. Not a release. |
| `main` | Same as `edge`. |

## Quick start

Do not run this image on its own. It needs PostgreSQL and a set of environment
variables, which the deployment kit wires up for you:

https://github.com/rtwodeetwo/talestogo/tree/main/deployment-kit

```
cp .env.template .env      # then fill in the keys it asks for
docker compose up -d
docker compose exec app python scripts/admin/setup_initial_admin.py
```

Full instructions, including OIDC and LLM provider setup, are in
`IT_DEPLOYMENT_GUIDE.md` in that directory.

## Which build am I running?

Every image records the commit it was built from, both as OCI labels and at
runtime:

```
docker buildx imagetools inspect rtwodeetwo/tales:latest
curl http://localhost:8080/health
```

`/health` reports the version, the commit, and the build date, so a running
deployment can always be matched back to source.

## Security

Static analysis and dependency audit results, accepted findings, and CycloneDX
SBOMs are published in the repository at `SECURITY.md`. The scan suite is
committed, so you can reproduce it yourself rather than take our word for it.
