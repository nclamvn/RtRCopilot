import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.rag.adapters import OfflineHashEmbedding, normalize_query
from rtr_copilot.rag.answering import AnswerService
from rtr_copilot.rag.api import rag_subject
from rtr_copilot.rag.models import SearchFilters
from rtr_copilot.rag.retrieval import RetrievalService

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def caller(user_id: uuid.UUID) -> Subject:
    return Subject(
        user_id=str(user_id), issuer="tip018", sub=user_id.hex,
        email=f"{user_id.hex}@rtrobotics.com", canonical_domain="rtrobotics.com",
        roles={Role.STAFF},
    )


async def seed_file(
    factory: async_sessionmaker[Any],
    owner: uuid.UUID,
    *,
    token: str,
    classification: str = "internal",
    leading_fillers: int = 0,
) -> tuple[uuid.UUID, uuid.UUID]:
    document_id, version_id = uuid.uuid4(), uuid.uuid4()
    source_object_id, rendition_object_id, rendition_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    chunk_id = uuid.uuid4()
    sha = hashlib.sha256(token.encode()).hexdigest()
    normalized = normalize_query(token)
    vector = OfflineHashEmbedding(64).embed(normalized)
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
            VALUES (:owner,'tip018',:sub,:email,'rtrobotics.com')
            ON CONFLICT (user_id) DO NOTHING
        """), {"owner": owner, "sub": owner.hex, "email": f"{owner.hex}@rtrobotics.com"})
        for resource_id, resource_type in (
            (document_id, "document"), (version_id, "document_version"),
            (source_object_id, "object"), (rendition_object_id, "object"),
            (rendition_id, "rendition"),
        ):
            await session.execute(text("""
                INSERT INTO resources(resource_id,resource_type,owner_subject_id,
                  classification,source_zone,lifecycle_state)
                VALUES (:id,:kind,:owner,:classification,'private_context','active')
            """), {
                "id": resource_id, "kind": resource_type, "owner": owner,
                "classification": classification,
            })
        for object_id, suffix in (
            (source_object_id, "source"), (rendition_object_id, "rendition"),
        ):
            await session.execute(text("""
                INSERT INTO object_blobs(object_id,bucket,object_key,sha256,
                  byte_size,mime_type,storage_state,created_by,verified_at)
                VALUES (:id,'test',:key,:sha,:size,'application/json',
                  'available',:owner,now())
            """), {
                "id": object_id, "key": f"tip018/{version_id}/{suffix}",
                "sha": sha, "size": len(token.encode()), "owner": owner,
            })
        await session.execute(text("""
            INSERT INTO documents(document_id,logical_name)
            VALUES (:document_id,:logical_name)
        """), {"document_id": document_id, "logical_name": f"file-{version_id}"})
        await session.execute(text("""
            INSERT INTO document_versions(version_id,document_id,version_no,
              object_id,original_filename,mime_type,sha256,byte_size,created_by,
              detected_mime,viewer_state)
            VALUES (:version_id,:document_id,1,:object_id,:filename,
              'application/pdf',:sha,:size,:owner,'application/pdf','ready')
        """), {
            "version_id": version_id, "document_id": document_id,
            "object_id": source_object_id, "filename": f"{token}.pdf",
            "sha": sha, "size": len(token.encode()), "owner": owner,
        })
        await session.execute(text("""
            UPDATE documents SET current_version_id=:version_id
            WHERE document_id=:document_id
        """), {"version_id": version_id, "document_id": document_id})
        await session.execute(text("""
            INSERT INTO renditions(rendition_id,version_id,kind,object_id,mime_type,
              status,generator,generator_version,source_sha256,quality_state)
            VALUES (:rendition_id,:version_id,'page_text_json',:object_id,
              'application/json','ready','test','1',:sha,'complete')
        """), {
            "rendition_id": rendition_id, "version_id": version_id,
            "object_id": rendition_object_id, "sha": sha,
        })
        await session.execute(text("""
            INSERT INTO file_chunks(file_chunk_id,document_version_id,rendition_id,
              chunk_key,display_text,normalized_text,text_sha256,source_sha256,
              rendition_sha256,rendition_kind,locator,ordinal,embedding)
            SELECT gen_random_uuid(),CAST(:version_id AS uuid),
              CAST(:rendition_id AS uuid),
              'file:' || CAST(:version_id AS text) || ':'
                || CAST(:rendition_id AS text) || ':' || lpad(gs::text,8,'0'),
              'generic filler', 'generic filler', :filler_sha, :sha, :sha,
              'page_text_json',CAST(:filler_locator AS jsonb),gs,
              CAST(:filler_embedding AS vector)
            FROM generate_series(1,:leading_fillers) gs
        """), {
            "version_id": version_id, "rendition_id": rendition_id,
            "leading_fillers": leading_fillers,
            "filler_sha": hashlib.sha256(b"generic filler").hexdigest(),
            "filler_locator": json.dumps({"page": 1}),
            "sha": sha,
            "filler_embedding": json.dumps(
                OfflineHashEmbedding(64).embed("generic filler"),
            ),
        })
        target_ordinal = leading_fillers + 1
        await session.execute(text("""
            INSERT INTO file_chunks(file_chunk_id,document_version_id,rendition_id,
              chunk_key,display_text,normalized_text,text_sha256,source_sha256,
              rendition_sha256,rendition_kind,locator,ordinal,embedding)
            VALUES (:chunk_id,:version_id,:rendition_id,:chunk_key,:content,
              :normalized,:sha,:sha,:sha,'page_text_json',
              CAST(:locator AS jsonb),:ordinal,CAST(:embedding AS vector))
        """), {
            "chunk_id": chunk_id, "version_id": version_id,
            "rendition_id": rendition_id,
            "chunk_key": (
                f"file:{version_id}:{rendition_id}:{target_ordinal:08d}"
            ),
            "content": token, "normalized": normalized, "sha": sha,
            "locator": json.dumps({"page": 1}),
            "embedding": json.dumps(vector),
            "ordinal": target_ordinal,
        })
    return version_id, chunk_id


@pytest.mark.asyncio
async def test_per_file_isolation_acl_and_grounded_persistence(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    del tmp_path
    owner = uuid.uuid4()
    token_a = f"ALPHA-{uuid.uuid4().hex} approved flight envelope"
    token_b = f"BRAVO-{uuid.uuid4().hex} confidential vendor margin"
    version_a, chunk_a = await seed_file(
        factory, owner, token=token_a, leading_fillers=205,
    )
    version_b, _ = await seed_file(factory, owner, token=token_b)
    service = RetrievalService(get_settings(), factory=factory)

    hits_a = await service.search(
        caller(owner), token_a,
        filters=SearchFilters(version_id=version_a), request_id="tip018-a",
    )
    assert hits_a and {hit.chunk_id for hit in hits_a} == {chunk_a}
    assert all(hit.citation.zone_label == "private" for hit in hits_a)
    assert all(hit.citation.document_version_id == version_a for hit in hits_a)
    assert token_b.encode() not in "\n".join(hit.snippet for hit in hits_a).encode()
    assert await service.search(
        caller(owner), token_a,
        filters=SearchFilters(
            version_id=version_a, classification_ceiling="public_internal",
        ),
        request_id="tip018-ceiling",
    ) == []

    cross = await service.search(
        caller(owner), token_b,
        filters=SearchFilters(version_id=version_a), request_id="tip018-cross",
    )
    assert all(hit.citation.document_version_id == version_a for hit in cross)
    assert token_b.encode() not in "\n".join(hit.snippet for hit in cross).encode()

    answer = await AnswerService(
        get_settings(), factory=factory,
        retrieval=RetrievalService(get_settings(), factory=factory),
    ).ask(
        caller(owner), token_a, filters=SearchFilters(version_id=version_a),
        require_verified=True, conversation_id=None, request_id="tip018-answer",
    )
    assert answer.state == "grounded"
    assert answer.citations[0].zone_label == "private"
    async with factory() as session:
        persisted = (await session.execute(text("""
            SELECT chunk_id,file_chunk_id,document_version_id,zone_label
            FROM answer_citations WHERE answer_run_id=:run_id
        """), {"run_id": answer.answer_run_id})).mappings().one()
    assert persisted["chunk_id"] is None
    assert persisted["file_chunk_id"] == chunk_a
    assert persisted["document_version_id"] == version_a
    assert persisted["zone_label"] == "private"

    async def authenticated() -> Subject:
        return caller(owner)

    app.dependency_overrides[rag_subject] = authenticated
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            history = await client.get(
                f"/api/v1/conversations/{answer.conversation_id}",
            )
            assert history.status_code == 200
            replayed = history.json()["messages"][-1]
            assert replayed["citations"][0]["zone_label"] == "private"
            assert replayed["citations"][0]["document_version_id"] == str(version_a)

            async with factory() as session, session.begin():
                await session.execute(text("""
                    INSERT INTO acl_entries(acl_id,resource_id,principal_type,
                      principal_id,action,effect,granted_by)
                    VALUES (:acl,:version_id,'user',:owner,'view','deny',:owner)
                """), {
                    "acl": uuid.uuid4(), "version_id": version_a, "owner": owner,
                })
            revoked = await client.get(
                f"/api/v1/conversations/{answer.conversation_id}",
            )
            assert revoked.status_code == 200
            replayed = revoked.json()["messages"][-1]
            assert replayed["citations"] == []
            assert replayed["content"] == "Evidence is no longer available."
    finally:
        app.dependency_overrides.pop(rag_subject, None)
    denied = await service.search(
        caller(owner), token_a,
        filters=SearchFilters(version_id=version_a), request_id="tip018-denied",
    )
    missing = await service.search(
        caller(owner), token_a,
        filters=SearchFilters(version_id=uuid.uuid4()), request_id="tip018-missing",
    )
    assert denied == missing == []
    assert await service.search(
        caller(owner), token_b,
        filters=SearchFilters(version_id=version_b), request_id="tip018-b",
    )


def test_file_scope_is_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="mutually_exclusive"):
        SearchFilters(source_key="rtr.specs", version_id=uuid.uuid4())
