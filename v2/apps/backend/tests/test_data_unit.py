import hashlib
import io
import uuid
from typing import Any

import pytest
from botocore.exceptions import ClientError

from rtr_copilot.commands import restore_bucket_guard
from rtr_copilot.repositories.audit import redact
from rtr_copilot.repositories.objects import DownloadCapability, normalize_filename
from rtr_copilot.storage.s3 import S3ObjectStorage


class FakeS3:
    def __init__(self) -> None:
        self.body = b""
        self.deleted: list[str] = []
        self.metadata: dict[str, str] = {}

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self.body = b""
        self.metadata = dict(kwargs.get("Metadata", {}))
        reader = kwargs["Body"]
        while chunk := reader.read(3):
            self.body += chunk
        return {"ETag": '"etag-is-not-a-checksum"'}

    def copy_object(self, **kwargs: Any) -> dict[str, str]:
        self.metadata = dict(kwargs["Metadata"])
        return {"CopyObjectResult": {"ETag": '"copied-etag"'}}

    def head_object(self, **_: Any) -> dict[str, Any]:
        return {
            "ContentLength": len(self.body),
            "Metadata": self.metadata,
            "ETag": '"copied-etag"',
        }

    def get_object(self, **_: Any) -> dict[str, Any]:
        return {"Body": io.BytesIO(self.body)}

    def delete_object(self, **kwargs: Any) -> None:
        self.deleted.append(str(kwargs["Key"]))


class FakeRestoreGuardS3:
    def __init__(self, objects: dict[str, dict[str, str]]) -> None:
        self.objects = objects
        self.bucket_deleted = False

    def put_object(self, **kwargs: Any) -> None:
        key = str(kwargs["Key"])
        if kwargs.get("IfNoneMatch") == "*" and key in self.objects:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )
        self.objects[key] = dict(kwargs.get("Metadata", {}))

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        key = str(kwargs["Key"])
        if key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing"}},
                "HeadObject",
            )
        return {"Metadata": self.objects[key]}

    def delete_object(self, **kwargs: Any) -> None:
        self.objects.pop(str(kwargs["Key"]))

    def delete_bucket(self, **_: Any) -> None:
        self.bucket_deleted = True

    def get_paginator(self, _: str) -> Any:
        objects = self.objects

        class Paginator:
            def paginate(self, **__: Any) -> list[dict[str, Any]]:
                return [{"Contents": [{"Key": key} for key in objects]}]

        return Paginator()


def test_nested_audit_redaction_removes_forbidden_keys_and_values() -> None:
    cleaned = redact({
        "safe": {
            "password": "hidden",
            "nested": [{"access_token": "hidden"}, "contains cookie material"],
        },
        "result": "ok",
    })
    serialized = str(cleaned).lower()
    assert cleaned["result"] == "ok"
    for forbidden in ("password", "access_token", "cookie", "hidden"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_streaming_sha256_size_head_and_uuid_key() -> None:
    fake = FakeS3()
    settings = type("StorageSettings", (), {
        "s3_bucket": "bucket",
        "s3_endpoint": "http://invalid",
        "s3_access_key": "key",
        "s3_secret_key": "secret",
    })()
    storage = S3ObjectStorage(settings, fake)  # type: ignore[arg-type]
    payload = b"streamed-object-payload"
    object_id = uuid.uuid4()
    result = await storage.upload_stream(
        key=f"staging/{object_id}",
        stream=io.BytesIO(payload),
        mime_type="application/octet-stream",
    )
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.byte_size == len(payload)
    assert str(object_id) in result.key
    assert "payload" not in result.key
    assert result.etag != result.sha256
    await storage.verify(
        key=result.key,
        expected_sha256=result.sha256,
        expected_size=result.byte_size,
    )


@pytest.mark.asyncio
async def test_same_size_overwrite_fails_closed_on_streamed_recompute() -> None:
    fake = FakeS3()
    settings = type("StorageSettings", (), {
        "s3_bucket": "bucket",
        "s3_endpoint": "http://invalid",
        "s3_access_key": "key",
        "s3_secret_key": "secret",
    })()
    storage = S3ObjectStorage(settings, fake)  # type: ignore[arg-type]
    stored = await storage.upload_stream(
        key="staging/same-size",
        stream=io.BytesIO(b"original"),
        mime_type="application/octet-stream",
    )
    fake.body = b"tampered"
    with pytest.raises(ValueError, match="object_content_integrity_mismatch"):
        await storage.verify(
            key=stored.key,
            expected_sha256=stored.sha256,
            expected_size=stored.byte_size,
        )


@pytest.mark.asyncio
async def test_declared_checksum_mismatch_deletes_staged_object() -> None:
    fake = FakeS3()
    settings = type("StorageSettings", (), {
        "s3_bucket": "bucket",
        "s3_endpoint": "http://invalid",
        "s3_access_key": "key",
        "s3_secret_key": "secret",
    })()
    storage = S3ObjectStorage(settings, fake)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="checksum_mismatch"):
        await storage.upload_stream(
            key="staging/key",
            stream=io.BytesIO(b"bytes"),
            mime_type="application/octet-stream",
            declared_sha256="0" * 64,
        )
    assert fake.deleted == ["staging/key"]


def test_filename_normalization_never_controls_identity() -> None:
    assert normalize_filename("../../Company Plan.pdf") == "Company Plan.pdf"
    assert normalize_filename("C:\\secret\\voice.wav") == "voice.wav"


def test_download_capability_is_explicit() -> None:
    capability = DownloadCapability(
        resource_id=uuid.uuid4(),
        action="download",
        allow=False,
        decision_id="deny.classification",
    )
    assert capability.allow is False


def test_restore_claim_detects_post_preflight_race_and_preserves_third_party(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRestoreGuardS3({"third-party-marker": {}})
    monkeypatch.setattr(restore_bucket_guard, "_client", lambda: fake)
    with pytest.raises(SystemExit, match="changed after preflight"):
        restore_bucket_guard.claim("race-target", "operation-1")
    assert fake.objects == {"third-party-marker": {}}


def test_restore_cleanup_removes_only_current_operation_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation_id = "operation-2"
    fake = FakeRestoreGuardS3({
        restore_bucket_guard.MARKER_KEY: {"restore-operation-id": operation_id},
        "staging/owned": {"restore-operation-id": operation_id},
        "third-party-marker": {},
    })
    monkeypatch.setattr(restore_bucket_guard, "_client", lambda: fake)
    restore_bucket_guard.cleanup("race-target", operation_id, created_bucket=True)
    assert fake.objects == {"third-party-marker": {}}
    assert not fake.bucket_deleted
