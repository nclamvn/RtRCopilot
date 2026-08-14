import argparse
import asyncio
import json
import uuid

from rtr_copilot.config import get_settings
from rtr_copilot.repositories.objects import ObjectRepository
from rtr_copilot.storage.s3 import S3ObjectStorage


async def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete-key")
    parser.add_argument("--actor-id")
    parser.add_argument("--request-id", default="object-reconciliation")
    parser.add_argument("--confirm-delete", action="store_true")
    parser.add_argument("--mark-missing", action="store_true")
    parser.add_argument("--confirm-mark-missing", action="store_true")
    args = parser.parse_args()
    repository = ObjectRepository(S3ObjectStorage(get_settings()))
    if args.delete_key:
        if not args.actor_id:
            parser.error("--actor-id is required for repair/delete")
        await repository.reconcile_delete(
            args.delete_key,
            actor_id=uuid.UUID(args.actor_id),
            request_id=args.request_id,
            explicit=args.confirm_delete,
        )
    repair = None
    if args.mark_missing:
        repair = await repository.reconcile_mark_missing(
            request_id=args.request_id,
            explicit=args.confirm_mark_missing,
        )
    report = await repository.reconcile()
    if repair is None:
        # Preserve the existing read-only command contract for operators and
        # automation that consume the three reconciliation lists directly.
        output: object = report
    else:
        # Repair logs remain content-free: counts and the key-set digest prove
        # scope without exposing internal object paths.
        output = {
            "repair": repair,
            "report_counts": {
                key: len(value) for key, value in report.items()
            },
        }
    print(json.dumps(output, sort_keys=True))
    return 1 if report["database_missing"] else 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
