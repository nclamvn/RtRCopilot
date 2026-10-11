# Document render recovery: schema 0016 boundary

This local recovery change adds bounded attempts, an ownership token, and lease expiry to persisted render jobs. Redis is only a best-effort wakeup hint; the new worker also polls durable pending jobs. An expired rendering/validating attempt terminates honestly as `render_lease_expired`. The user may explicitly retry within the configured attempt bound. Recovery does not automatically regenerate a potentially partially staged artifact.

## Operational compatibility warning

Do not claim rolling compatibility with workers from schema 0015 or earlier. Those workers do not fence completion, failure, or staged-object cleanup by lease token. Before any separately authorized deployment of this patch, pause new render admission, stop or drain **all** old workers, apply migration 0016, and restart only workers running the new ownership-aware source. Do not let an old worker resume after upgrade. Changing the expected-schema string alone is not proof that a running worker has the new code.

A downgrade is not an operational recovery procedure: it drops ownership/attempt fields and the recovery index. It was exercised only in a disposable synthetic database. If an operator chooses a rollback, first stop all rendering workers and arrange an explicitly approved recovery/data plan; do not downgrade while attempts are active. Existing serving services and databases were not changed by the local verification work.

## Local reproduction

`bash scripts/verify-tip054-local.sh` creates a new labeled internal Docker network, PostgreSQL, Redis, and MinIO, using only synthetic credentials and a disposable `rtr_tip054_` database. It does not read private `.env`, mount a serving volume, or invoke an LLM/embedding provider. Source mounts are read-only and explicitly selected; generated artifacts stay in synthetic storage.

The default run requires cached images and the local QA image `rtr-tip054-local-qa:20261006`. To authorize only installation of the pinned public pytest/ruff/mypy packages into a disposable runner based on the cached full worker image, use `TIP054_QA_IMAGE=rtr-copilot-v2-worker:latest TIP054_INSTALL_QA=1 bash scripts/verify-tip054-local.sh`; after installation the runner is detached from the egress-capable bridge and attached only to the internal fixture network. This is dependency installation, not provider invocation. `TIP054_KEEP=1` retains only the labeled fixtures for independent local inspection; otherwise exit cleanup checks exact ownership labels before deleting its own containers and volumes.

The runner validates upgrade/downgrade/upgrade and lease columns before tests. Integration tests run as `rtr_app` (SELECT/INSERT/UPDATE allowed; DELETE and schema CREATE denied), while migrations use a separate synthetic owner role. Unit and integration phases use separate pytest processes to preserve their respective event-loop lifetimes. Each integration module gets its own fresh database because existing governance tests intentionally activate global ontology/maintenance state; the owned synthetic Redis cache is reset between modules. Partial/optional runtime-tool skips remain explicit in pytest output and are not counted as executed business scenarios.
