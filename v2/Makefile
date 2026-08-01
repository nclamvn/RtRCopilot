SHELL := /bin/bash

.PHONY: dev verify migrate migration-check db-verify backup restore-drill down clean reset ps logs hardened-up hardened-down hardened-probe ci-local migration-gate image-policy deploy rollback

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
