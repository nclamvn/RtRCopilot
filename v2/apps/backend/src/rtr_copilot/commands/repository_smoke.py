import asyncio

from sqlalchemy import text

from rtr_copilot.config import get_settings
from rtr_copilot.db.engine import session_factory
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
from rtr_copilot.storage.s3 import S3ObjectStorage


async def smoke() -> int:
    factory = session_factory()
    async with factory() as session:
        identity = (await session.execute(text("""
            SELECT issuer, provider_sub FROM subjects ORDER BY created_at LIMIT 1
        """))).one_or_none()
        objects = (await session.execute(text("""
            SELECT object_key, sha256, byte_size FROM object_blobs
            WHERE storage_state='available' ORDER BY created_at
        """))).all()
        valid, audit_count, _ = await AuditRepository().verify(session)
    if identity is not None:
        subject = await PostgresSubjectRepository(factory).get_by_identity(
            str(identity[0]),
            str(identity[1]),
        )
        if subject is None:
            raise RuntimeError("identity_repository_smoke_failed")
    storage = S3ObjectStorage(get_settings())
    for key, sha256, byte_size in objects:
        await storage.verify(
            key=str(key),
            expected_sha256=str(sha256),
            expected_size=int(byte_size),
            recompute=True,
        )
    if not valid:
        raise RuntimeError("audit_repository_smoke_failed")
    print(
        f"repository_smoke=pass identities={int(identity is not None)} "
        f"objects={len(objects)} audit_events={audit_count}",
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(smoke()))


if __name__ == "__main__":
    main()
