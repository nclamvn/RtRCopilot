# Agent Workspace frontend

Independent local Next entry for the Workspace Python API. It has its own layout,
metadata, small neutral reset and routes. It imports the shared neutral UI and
the scoped BFF, not the legacy application shell, global CSS stack, auth, proxy or
company services. The legacy web entry is retained unchanged.

Use the Python launcher from `v2/apps/workspace`:

```sh
.venv/bin/workspace launch --simulation
```

This starts loopback API8110/UI3110. For isolated synthetic E2E, use separate
ports and a separate data directory, for example `--api-port 8120 --web-port 3120
--data-dir .workspace-data/aw05-e2e`. Use fresh browser contexts; changing only a port does
not isolate browser cookies.

The package uses the already pinned dependencies in the workspace lock. Offline
installation only in AW-05; no package/model/font download is authorized.
`pnpm workspace:build` from `v2` creates the one fixed reusable `.next-build`.
The Python launcher's `--production` serves that local optimized build.
Development uses the ordinary `.next` directory. Neither mode is deployment.

`pnpm workspace:audit` checks transitive local source imports and, after a build,
the compiled route manifest. No legacy app routes, styles or auth should enter
the graph. This is not a license audit, complete dependency SBOM or proof of AI
quality. The shared neutral source remains in the monorepo; this package is not
an independently vendored binary distribution.
