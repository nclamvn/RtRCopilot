# Context/Memory and Action Contracts: local verification boundary

TIP-054.2/.3 introduce domain storage and authenticated contract APIs. They do **not** add an executor, queue dispatch, a provider/connector invocation, or a successful external business effect. A healthy schema and an admitted plan cannot certify any of those later runtime capabilities.

## Reproduce the current local gates

From the repository root, run `bash v2/scripts/verify-tip054-local.sh`. The default QA image is the existing local `rtr-tip054-local-qa:20261006`, which includes pytest/mypy/Ruff and the cached document/media tools. No package installation is attempted by default. Source/templates/test fixtures are explicitly selected read-only mounts; private `.env`, kernel corpus, serving volumes, `eval/runtime`, and the Docker socket are not mounted.

For independent focused overlap, run `TIP054_SCOPE=focused TIP054_QA_IMAGE=rtr-tip054-local-qa:20261006 bash v2/scripts/verify-tip054-local.sh`. It uses the same populated migration/privilege cycle, then the three new unit modules and one fresh database per Context, Action and mounted-HTTP integration module. Its counts overlap the full gate and must not be added to full totals.

Each run creates ownership-labeled disposable PostgreSQL, Redis and MinIO on an internal Docker network without serving ports. Provider keys are absent during tests, embeddings are offline, and every integration module gets its own prefixed database/pytest process. The owned synthetic Redis cache is reset between modules because older governance tests intentionally alter global ontology/maintenance state. Exact label checks restrict cleanup to that run's own resources. `TIP054_KEEP=1` retains those labeled fixtures only for an explicitly needed independent rerun.

The runner now exercises `0016 → 0017 → 0018 → 0017 → 0016 → 0017 → 0018`, checks the exact expected tables at each boundary, and checks individual runtime SELECT/INSERT/UPDATE/DELETE/TRUNCATE privileges. Mutable admission/approval revocation and run-budget fields remain constrained by the action migration's triggers; a SQL UPDATE grant is not a permission to rewrite their immutable contract fields.

Representative legacy survivors are created through real local contracts: a signed synthetic SOT package is validated/published/indexed and a synthetic DOCX is rendered through the real Files pipeline into MinIO with a deterministic malware fixture. Fingerprints of every original selected row must survive; additional Context/Action audit records are allowed, but the hash chain must remain valid and prior rows cannot change or disappear.

## Downgrade warning

These downgrade tests are disposable only. Downgrading from 0018 drops Action-domain tables and their rows. Downgrading from 0017 drops ContextPacket/Memory tables and their rows. Re-upgrade recreates those structures; it does not restore their lost contents. Legacy SOT/render/audit preservation is **not** proof of new-domain workflow backup/restore. Do not use this test cycle as an operational rollback procedure for a serving system containing new-domain work.

TIP-054.1 reports remain historical evidence of their actual schema-0016 execution. The shared runner's current schema cycle is explicitly the later .2/.3 gate, not a retroactive rewriting of .1's results.

## Auth and rate-class decisions

New routes reuse the existing HttpOnly/SameSite=Lax/secure-effective session-cookie pattern and current subject/resource checks. The backend scan did not find an explicit Origin/Referer or double-submit CSRF guard; synthetic HTTP cookie flows do not certify browser CSRF protection. No broader authentication policy was changed by this integration work.

Context resolve/packet POSTs are bounded read-compute with no provider and use the finite read class. Context memory mutations use the existing upload class; Action-domain mutations use render; distinct capability admission/revocation mutations use admin. Read-only GETs retain the read class. Exact path boundaries and mutation methods are regression tested. Rate classification grants no policy authority, publication permission, or effect capability.

The real mounted HTTP gate checks safe error/request-id envelopes, actual Redis-cookie private memory flows, unknown authority-field rejection, and maintenance denial. Schema checks report storage availability only; future durable execution and live-source readiness remain separate requirements.
