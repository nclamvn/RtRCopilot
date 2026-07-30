SHELL := /bin/bash

.PHONY: dev verify migrate migration-check db-verify backup restore-drill down clean reset ps logs

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
