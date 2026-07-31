import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, BinaryIO, cast

import boto3  # type: ignore[import-untyped]

from rtr_copilot.config import Settings


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    sha256: str
    byte_size: int
    etag: str | None


class HashingReader:
    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.digest = hashlib.sha256()
        self.byte_size = 0

    def read(self, size: int = -1) -> bytes:
        data = self.source.read(size)
        self.digest.update(data)
        self.byte_size += len(data)
        return data

    def tell(self) -> int:
        return self.source.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        position = self.source.seek(offset, whence)
        if position == 0:
            self.digest = hashlib.sha256()
            self.byte_size = 0
        return position


class S3ObjectStorage:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.bucket = settings.s3_bucket
        self.client = client or boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint),
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

    async def upload_stream(
        self,
        *,
        key: str,
        stream: BinaryIO,
        mime_type: str,
        declared_sha256: str | None = None,
        upload_state: str = "staged",
        extra_metadata: dict[str, str] | None = None,
    ) -> StoredObject:
        def upload() -> StoredObject:
            reader = HashingReader(stream)
            initial_metadata = {"upload-state": upload_state}
            initial_metadata.update(extra_metadata or {})
            response = self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=reader,
                ContentType=mime_type,
                Metadata=initial_metadata,
            )
            digest = reader.digest.hexdigest()
            if declared_sha256 and digest != declared_sha256.lower():
                self.client.delete_object(Bucket=self.bucket, Key=key)
                raise ValueError("checksum_mismatch")
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            if int(head["ContentLength"]) != reader.byte_size:
                raise ValueError("object_size_mismatch")
            trusted_metadata = {
                "upload-state": upload_state,
                "sha256": digest,
                "byte-size": str(reader.byte_size),
            }
            trusted_metadata.update(extra_metadata or {})
            self.client.copy_object(
                Bucket=self.bucket,
                Key=key,
                CopySource={"Bucket": self.bucket, "Key": key},
                ContentType=mime_type,
                MetadataDirective="REPLACE",
                Metadata=trusted_metadata,
            )
            trusted_head = self.client.head_object(Bucket=self.bucket, Key=key)
            metadata = {
                str(name).lower(): str(value)
                for name, value in trusted_head.get("Metadata", {}).items()
            }
            if (
                metadata.get("sha256") != digest
                or metadata.get("byte-size") != str(reader.byte_size)
            ):
                raise ValueError("object_checksum_metadata_mismatch")
            return StoredObject(
                bucket=self.bucket,
                key=key,
                sha256=digest,
                byte_size=reader.byte_size,
                etag=str(trusted_head.get("ETag", response.get("ETag", ""))).strip('"')
                or None,
            )

        return await asyncio.to_thread(upload)

    async def download_to(self, key: str, target: BinaryIO) -> None:
        def download() -> None:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"]
            try:
                while chunk := body.read(1024 * 1024):
                    target.write(chunk)
            finally:
                body.close()
            target.flush()
            target.seek(0)

        await asyncio.to_thread(download)

    async def get_body(
        self,
        key: str,
        *,
        byte_range: tuple[int, int] | None = None,
    ) -> Any:
        arguments: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if byte_range is not None:
            arguments["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
        response = await asyncio.to_thread(self.client.get_object, **arguments)
        return response["Body"]

    async def head(self, key: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.client.head_object,
            Bucket=self.bucket,
            Key=key,
        )

    async def verify(
        self,
        *,
        key: str,
        expected_sha256: str,
        expected_size: int,
        recompute: bool = True,
    ) -> dict[str, Any]:
        def verify_object() -> dict[str, Any]:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            metadata = {
                str(name).lower(): str(value)
                for name, value in head.get("Metadata", {}).items()
            }
            if (
                int(head["ContentLength"]) != expected_size
                or metadata.get("sha256") != expected_sha256
                or metadata.get("byte-size") != str(expected_size)
            ):
                raise ValueError("object_trusted_metadata_mismatch")
            if recompute:
                response = self.client.get_object(Bucket=self.bucket, Key=key)
                body = response["Body"]
                digest = hashlib.sha256()
                byte_size = 0
                try:
                    while chunk := body.read(1024 * 1024):
                        digest.update(chunk)
                        byte_size += len(chunk)
                finally:
                    body.close()
                if byte_size != expected_size or digest.hexdigest() != expected_sha256:
                    raise ValueError("object_content_integrity_mismatch")
            return cast(dict[str, Any], head)

        return await asyncio.to_thread(verify_object)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self.client.delete_object,
            Bucket=self.bucket,
            Key=key,
        )

    async def inventory(self) -> list[dict[str, Any]]:
        def list_all() -> list[dict[str, Any]]:
            paginator = self.client.get_paginator("list_objects_v2")
            return [
                {
                    "key": item["Key"],
                    "byte_size": int(item["Size"]),
                    "etag": str(item.get("ETag", "")).strip('"'),
                }
                for page in paginator.paginate(Bucket=self.bucket)
                for item in page.get("Contents", [])
            ]

        return await asyncio.to_thread(list_all)
