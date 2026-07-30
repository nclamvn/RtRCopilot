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
    report = await repository.reconcile()
    print(json.dumps(report, sort_keys=True))
    return 1 if report["database_missing"] else 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
