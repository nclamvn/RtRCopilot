import hashlib
import json
from typing import Any

import boto3  # type: ignore[import-untyped]

from rtr_copilot.config import get_settings


def inventory() -> list[dict[str, Any]]:
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint),
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
    results: list[dict[str, Any]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket):
        for item in page.get("Contents", []):
            key = str(item["Key"])
            if key.startswith(".rtr-restore/"):
                continue
            head = client.head_object(Bucket=settings.s3_bucket, Key=key)
            metadata = {
                str(name).lower(): str(value)
                for name, value in head.get("Metadata", {}).items()
            }
            response = client.get_object(Bucket=settings.s3_bucket, Key=key)
            body = response["Body"]
            digest = hashlib.sha256()
            byte_size = 0
            try:
                while chunk := body.read(1024 * 1024):
                    digest.update(chunk)
                    byte_size += len(chunk)
            finally:
                body.close()
            sha256 = digest.hexdigest()
            if (
                byte_size != int(head["ContentLength"])
                or metadata.get("sha256") != sha256
                or metadata.get("byte-size") != str(byte_size)
            ):
                raise RuntimeError(f"object_inventory_integrity_failed:{key}")
            results.append({
                "bucket": settings.s3_bucket,
                "key": key,
                "byte_size": byte_size,
                "sha256": sha256,
                "checksum_source": "verified-content-and-sha256-metadata",
            })
    return sorted(results, key=lambda item: str(item["key"]))


def main() -> None:
    print(json.dumps(inventory(), sort_keys=True))


if __name__ == "__main__":
    main()
