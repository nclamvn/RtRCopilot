SHELL := /bin/bash
RTR_BUILD_SHA ?= $(shell ./scripts/build-identity.sh)
export RTR_BUILD_SHA

.PHONY: dev verify e2e-enterprise tip032-recertify tip033-recertify tip034-pilot-capture tip03512-ai-surrogate tip035-preflight production-config-init production-config-check answer-runtime-check answer-runtime-refresh pilot-up pilot-check pilot-scorecard pilot-campaign-check pilot-campaign-evaluate pilot-down enterprise-release inventory-snapshot inventory-check document-lifecycle-proof connector-readiness crm-canary migrate migration-check db-verify backup restore-drill down clean reset ps logs hardened-up hardened-down hardened-probe ci-local migration-gate image-policy deploy rollback load-up load load-probe slo onboard-batch parity eval

# TIP-012 Task 1 — hardened profile (TLS ingress fronts everything, AC-01).
# Requires the ingress hostname to resolve to 127.0.0.1 for probes/browsers:
#   echo "127.0.0.1 rtr.local" | sudo tee -a /etc/hosts
# See docs/ingress-hardening.md. Dev profile (`make dev`) is unchanged.
HARDENED_COMPOSE := docker compose -f compose.yaml -f compose.hardened.yaml
INGRESS_HOST ?= rtr.local
HARDENED_PUBLIC_BASE_URL ?= https://$(INGRESS_HOST)

dev:
	docker compose up --build -d postgres redis minio minio-init clamav
	$(MAKE) migrate
	docker compose up --build -d api worker web
	./scripts/wait-ready.sh

verify:
	./scripts/verify-scaffold.sh

e2e-enterprise:
	./scripts/run-enterprise-e2e.sh

tip032-recertify:
	./scripts/run-tip032-recertification.sh

tip033-recertify:
	./scripts/run-tip033-recertification.sh

tip034-pilot-capture:
	./scripts/run-tip034-pilot-capture.sh

tip03512-ai-surrogate:
	./scripts/run-tip03512-ai-surrogate.sh

tip035-preflight:
	./scripts/verify-tip035-release.sh

PRODUCTION_ENV_FILE ?= .env.production

production-config-init:
	@test ! -e "$(PRODUCTION_ENV_FILE)" || { echo "Refusing to overwrite $(PRODUCTION_ENV_FILE)" >&2; exit 1; }
	install -m 600 .env.production.example "$(PRODUCTION_ENV_FILE)"
	@echo "Created $(PRODUCTION_ENV_FILE) with mode 600. Replace every __SET_*__ value, then run make production-config-check."

production-config-check:
	PRODUCTION_ENV_FILE="$(PRODUCTION_ENV_FILE)" ./scripts/verify-production-configuration.sh

# The local quality profile lives in .env.demo. `docker compose restart` does
# not reload changed environment variables, and plain `docker compose up` reads
# .env instead. Rebuild is intentional: a recreate from a stale image can pass
# the environment check while still running old query/grounding code.
# These targets make both code and configuration explicit without ever printing
# a credential value.
ANSWER_ENV_FILE ?= .env.demo

answer-runtime-check:
	ANSWER_ENV_FILE="$(ANSWER_ENV_FILE)" ./scripts/verify-answer-runtime.sh

answer-runtime-refresh:
	docker compose --env-file "$(ANSWER_ENV_FILE)" up -d --build --force-recreate api worker web
	$(MAKE) answer-runtime-check ANSWER_ENV_FILE="$(ANSWER_ENV_FILE)"

PILOT_KERNEL_ROOT ?= $(abspath ../../_Architecture)

pilot-up:
	./scripts/local-demo.sh --kernel-root "$(PILOT_KERNEL_ROOT)"
	$(MAKE) pilot-check

pilot-check:
	./scripts/verify-pilot-database.sh

PILOT_SCORECARD_INPUT ?= /app/eval/pilot/tip032_scorecard.json
PILOT_SCORECARD_OUTPUT ?= /app/eval/pilot/tip032_scorecard_result.json

pilot-scorecard:
	docker compose --env-file "$(ANSWER_ENV_FILE)" run --rm \
		-v "$(CURDIR)/eval:/app/eval" api \
		python -m rtr_copilot.commands.evaluate_pilot_scorecard \
		--input "$(PILOT_SCORECARD_INPUT)" --output "$(PILOT_SCORECARD_OUTPUT)"

PILOT_CAMPAIGN ?= /app/eval/pilot/tip034_campaign.json
PILOT_CAMPAIGN_DEFINITION_LEDGER ?= /app/eval/pilot/tip034_observations.json
PILOT_CAMPAIGN_LEDGER ?= /app/eval/runtime/tip034_observations.json
PILOT_CAMPAIGN_SOURCE ?= /app/eval/real_world/cases.json
PILOT_CAMPAIGN_DEFINITION_OUTPUT ?= /app/eval/runtime/tip034_definition_result.json
PILOT_CAMPAIGN_OUTPUT ?= /app/eval/runtime/tip034_campaign_result.json
PILOT_ACCEPTANCE_REPORT ?= /app/eval/runtime/tip034_pilot_capture.json

pilot-campaign-check:
	docker compose --env-file "$(ANSWER_ENV_FILE)" run --rm \
		-v "$(CURDIR)/eval:/app/eval" api \
		python -m rtr_copilot.commands.evaluate_pilot_campaign \
		--campaign "$(PILOT_CAMPAIGN)" --ledger "$(PILOT_CAMPAIGN_DEFINITION_LEDGER)" \
		--source-suite "$(PILOT_CAMPAIGN_SOURCE)" \
		--output "$(PILOT_CAMPAIGN_DEFINITION_OUTPUT)" --definition-only

pilot-campaign-evaluate:
	docker compose --env-file "$(ANSWER_ENV_FILE)" run --rm \
		-v "$(CURDIR)/eval:/app/eval" api \
		python -m rtr_copilot.commands.evaluate_pilot_campaign \
		--campaign "$(PILOT_CAMPAIGN)" --ledger "$(PILOT_CAMPAIGN_LEDGER)" \
		--source-suite "$(PILOT_CAMPAIGN_SOURCE)" \
		--acceptance-report "$(PILOT_ACCEPTANCE_REPORT)" \
		--output "$(PILOT_CAMPAIGN_OUTPUT)"

pilot-down:
	./scripts/local-demo.sh --down

enterprise-release:
	docker compose --env-file "$(ANSWER_ENV_FILE)" exec -T api \
		python -m rtr_copilot.commands.bootstrap_enterprise_release --approve

INVENTORY_OUTPUT ?= /app/eval/enterprise_corpus/runtime_snapshot.json

inventory-snapshot:
	docker compose --env-file "$(ANSWER_ENV_FILE)" run --rm \
		-v "$(CURDIR)/eval:/app/eval" api \
		python -m rtr_copilot.commands.snapshot_enterprise_inventory \
		--output "$(INVENTORY_OUTPUT)"

inventory-check:
	docker compose --env-file "$(ANSWER_ENV_FILE)" run --rm \
		-v "$(CURDIR)/eval:/app/eval:ro" api \
		python -m rtr_copilot.commands.snapshot_enterprise_inventory \
		--output "$(INVENTORY_OUTPUT)" --check

document-lifecycle-proof:
	docker compose --env-file "$(ANSWER_ENV_FILE)" run --rm \
		-v "$(CURDIR)/eval:/app/eval" api \
		python -m rtr_copilot.commands.prove_document_lifecycle --approve \
		--report /app/eval/document_os/runtime_lifecycle_proof.json

RTR_ECOSYSTEM_ROOT ?= $(abspath ../../..)

connector-readiness:
	docker compose --env-file "$(ANSWER_ENV_FILE)" run --rm \
		-v "$(RTR_ECOSYSTEM_ROOT):/ecosystem:ro" \
		-v "$(CURDIR)/eval:/app/eval" api \
		python -m rtr_copilot.commands.snapshot_connector_readiness \
		--rtr-root /ecosystem \
		--output /app/eval/enterprise_corpus/connector_readiness.json

crm-canary:
	docker compose --env-file "$(ANSWER_ENV_FILE)" run --rm \
		-v "$(RTR_ECOSYSTEM_ROOT):/ecosystem:ro" \
		-v "$(CURDIR)/eval:/app/eval" api \
		python -m rtr_copilot.commands.probe_crm_canary \
		--rtr-root /ecosystem \
		--output /app/eval/enterprise_corpus/crm_canary.json

migrate:
	docker compose --profile tools run --rm migrate

migration-check:
	docker compose --profile tools run --rm migrate alembic current
	docker compose --profile tools run --rm migrate alembic heads

db-verify:
	./scripts/verify-database.sh

backup:
	./scripts/backup-data.sh "$(BACKUP_DESTINATION)"

restore-drill:
	./scripts/restore-data.sh "$(BACKUP_ARCHIVE)" "$(RESTORE_TARGET)" "$(CONFIRM_TARGET)"

hardened-up:
	$(HARDENED_COMPOSE) up -d postgres redis minio minio-init clamav
	$(HARDENED_COMPOSE) --profile tools run --rm migrate
	PUBLIC_BASE_URL=$(HARDENED_PUBLIC_BASE_URL) INGRESS_HOST=$(INGRESS_HOST) \
		$(HARDENED_COMPOSE) --profile hardened up -d api worker web ingress
	INGRESS_HOST=$(INGRESS_HOST) ./scripts/wait-ready-hardened.sh

hardened-down:
	$(HARDENED_COMPOSE) --profile hardened down

hardened-probe:
	cd apps/backend && \
		INGRESS_PROBE_ORIGIN=https://$(INGRESS_HOST) \
		uv run pytest tests/test_ingress_probe.py -v

down:
	docker compose down

clean:
	docker compose down --remove-orphans
	rm -rf apps/web/.next apps/backend/.pytest_cache apps/backend/.mypy_cache apps/backend/.ruff_cache

reset:
	@read -r -p "Xóa toàn bộ named volumes V2? Gõ RESET-V2 để xác nhận: " answer; \
	test "$$answer" = "RESET-V2" || { echo "Đã hủy."; exit 1; }; \
	docker compose down --volumes --remove-orphans

ps:
	docker compose ps

logs:
	docker compose logs --tail=200

# TIP-012 Task 4 — CI/CD, migration gate, versioned deploy/rollback, image
# policy. Additive targets; `verify` and every other recipe above are untouched.
# ci-local mirrors .github/workflows/verify.yml stage-by-stage in this
# environment. Layer the sandbox compose-build workaround with RTR_SANDBOX_BUILD=1
# (see scripts/ci-common.sh). deploy/rollback take an optional VERSION:
#   make deploy VERSION=<sha>     make rollback VERSION=<sha>
ci-local:
	./scripts/ci-local.sh

migration-gate:
	./scripts/migration-gate.sh

image-policy:
	./scripts/verify-image-policy.sh

deploy:
	./scripts/deploy.sh $(VERSION)

rollback:
	./scripts/rollback.sh $(VERSION)

# TIP-012 Task 5 — load testing + SLO (Builder 5). Additive targets; `verify`
# and every recipe above are untouched. `load-up` brings up the hardened stack
# WITH the load-measurement override (compose.load.yaml raises rate-limit quotas
# so a single-IP k6 generator measures server latency). `load` runs the k6 SLO
# scenarios through the ingress and evaluates them. `slo` re-evaluates existing
# results. `load-probe` runs the R1 rate-limit probe at default limits. In this
# sandbox export MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600 (ClamAV freshness).
LOAD_COMPOSE := docker compose -f compose.yaml -f compose.hardened.yaml -f compose.load.yaml

load-up:
	$(LOAD_COMPOSE) up -d postgres redis minio minio-init clamav
	$(LOAD_COMPOSE) --profile tools run --rm migrate
	PUBLIC_BASE_URL=$(HARDENED_PUBLIC_BASE_URL) INGRESS_HOST=$(INGRESS_HOST) \
		$(LOAD_COMPOSE) --profile hardened up -d api worker web ingress
	INGRESS_HOST=$(INGRESS_HOST) ./scripts/wait-ready-hardened.sh

load:
	./scripts/run-load.sh
	./scripts/evaluate-slo.sh

load-probe:
	./scripts/run-load-probe.sh

slo:
	./scripts/evaluate-slo.sh

# TIP-013 Phase A tooling — additive; `verify` and every recipe above are
# untouched. `onboard-batch` is a curator-gated batch onboarding driver (dry-run by
# default; pass ARGS='--manifest … --apply --approve'). `parity` and `eval` run the
# V1-parity and answer-quality harnesses and (re)write the committed report
# artefacts under eval/. Both harnesses require a migrated SYNTHETIC database via
# INTEGRATION_DATABASE_DSN — never a real corpus.
onboard-batch:
	./scripts/onboard-batch.sh $(ARGS)

parity:
	cd apps/backend && uv run python ../../eval/run_parity.py

eval:
	cd apps/backend && uv run python ../../eval/run_eval.py
