import argparse
import json
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from rtr_copilot.config import get_settings

MARKER_KEY = ".rtr-restore/reservation.json"


def _client() -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=str(settings.s3_endpoint),
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )


def _keys(client: Any, bucket: str) -> set[str]:
    paginator = client.get_paginator("list_objects_v2")
    return {
        str(item["Key"])
        for page in paginator.paginate(Bucket=bucket)
        for item in page.get("Contents", [])
    }


def _owns_marker(client: Any, bucket: str, operation_id: str) -> bool:
    try:
        head = client.head_object(Bucket=bucket, Key=MARKER_KEY)
    except ClientError:
        return False
    metadata = {str(key).lower(): str(value) for key, value in head["Metadata"].items()}
    return metadata.get("restore-operation-id") == operation_id


def claim(bucket: str, operation_id: str) -> None:
    body = json.dumps({
        "operation_id": operation_id,
        "state": "reserved",
    }).encode()
    try:
        _client().put_object(
            Bucket=bucket,
            Key=MARKER_KEY,
            Body=body,
            ContentType="application/json",
            Metadata={
                "restore-operation-id": operation_id,
                "restore-state": "reserved",
            },
            IfNoneMatch="*",
        )
    except ClientError as exc:
        raise SystemExit(f"bucket reservation claim failed: {exc}") from exc
    client = _client()
    extras = _keys(client, bucket) - {MARKER_KEY}
    if extras:
        if _owns_marker(client, bucket, operation_id):
            client.delete_object(Bucket=bucket, Key=MARKER_KEY)
        raise SystemExit("bucket changed after preflight; reservation released")
    print(f"bucket_reservation=claimed operation_id={operation_id}")


def complete(bucket: str, operation_id: str, expected_path: str) -> None:
    client = _client()
    if not _owns_marker(client, bucket, operation_id):
        raise SystemExit("bucket ownership is ambiguous; restore quarantined")
    with open(expected_path) as expected_file:
        expected: list[dict[str, Any]] = json.load(expected_file)
    expected_keys = {str(item["key"]) for item in expected}
    actual_keys = _keys(client, bucket)
    if actual_keys != expected_keys | {MARKER_KEY}:
        raise SystemExit("bucket contains mixed or missing objects; restore quarantined")
    for item in expected:
        head = client.head_object(Bucket=bucket, Key=str(item["key"]))
        metadata = {
            str(key).lower(): str(value)
            for key, value in head.get("Metadata", {}).items()
        }
        if (
            metadata.get("restore-operation-id") != operation_id
            or metadata.get("sha256") != str(item["sha256"])
            or metadata.get("byte-size") != str(item["byte_size"])
        ):
            raise SystemExit(f"object ownership/integrity marker mismatch: {item['key']}")
    client.put_object(
        Bucket=bucket,
        Key=MARKER_KEY,
        Body=json.dumps({
            "operation_id": operation_id,
            "state": "ready",
            "object_count": len(expected),
        }).encode(),
        ContentType="application/json",
        Metadata={
            "restore-operation-id": operation_id,
            "restore-state": "ready",
        },
    )
    print(f"bucket_reservation=ready operation_id={operation_id}")


def cleanup(bucket: str, operation_id: str, created_bucket: bool) -> None:
    client = _client()
    if not _owns_marker(client, bucket, operation_id):
        raise SystemExit("bucket cleanup refused: ownership marker is missing or foreign")
    for key in _keys(client, bucket) - {MARKER_KEY}:
        head = client.head_object(Bucket=bucket, Key=key)
        metadata = {
            str(name).lower(): str(value)
            for name, value in head.get("Metadata", {}).items()
        }
        if metadata.get("restore-operation-id") == operation_id:
            client.delete_object(Bucket=bucket, Key=key)
    client.delete_object(Bucket=bucket, Key=MARKER_KEY)
    remaining = _keys(client, bucket)
    if created_bucket and not remaining:
        client.delete_bucket(Bucket=bucket)
    print(
        f"bucket_cleanup=complete operation_id={operation_id} "
        f"third_party_objects_preserved={len(remaining)}",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("claim", "complete", "cleanup"))
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--expected-path")
    parser.add_argument("--created-bucket", action="store_true")
    args = parser.parse_args()
    if args.action == "claim":
        claim(args.bucket, args.operation_id)
    elif args.action == "complete":
        if not args.expected_path:
            parser.error("--expected-path is required for complete")
        complete(args.bucket, args.operation_id, args.expected_path)
    else:
        cleanup(args.bucket, args.operation_id, args.created_bucket)


if __name__ == "__main__":
    main()
