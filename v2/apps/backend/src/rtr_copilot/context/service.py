"""Local, source-current company projection and explicit non-authoritative memory."""

import hashlib
import json
import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.context.models import (
    ContextError,
    ContextGap,
    ContextPacket,
    EntityProjection,
    ExplicitRelation,
    MemoryCorrection,
    MemoryCreate,
    MemoryScope,
    MemoryTombstone,
    MemoryView,
    PacketRequest,
    RelationAssertion,
    SOTReference,
    utc_now,
)
from rtr_copilot.context.sources import current_context_subject, revalidate_sot_references
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.rag.ontology import EnterpriseOntology, load_runtime_ontology
from rtr_copilot.rag.use_class import USE_CLASSES, UseClass
from rtr_copilot.repositories.audit import AuditRepository

MAX_MEMORY = 100
MAX_TTL = timedelta(days=30)  # Local contract ceiling, not a production retention policy.


def _refs(raw: Any) -> tuple[SOTReference, ...]:
    return tuple(SOTReference.model_validate(item) for item in raw)


def _scope(row: Any) -> MemoryScope:
    return MemoryScope.model_validate({"kind": row["scope_kind"], "key": row["scope_key"]})


def _gaps(*items: tuple[ContextGap, ...]) -> tuple[ContextGap, ...]:
    return tuple(sorted({gap for group in items for gap in group}, key=lambda gap: gap.code))


def _scope_allowed(subject: Subject, scope: MemoryScope, *, team_write: bool = False) -> bool:
    if scope.kind == "private":
        return True
    memberships = subject.projects if scope.kind == "project" else subject.departments
    return str(scope.key) in memberships and (
        not team_write or bool(subject.roles & {Role.LEADER, Role.CURATOR})
    )


def _size(packet: ContextPacket) -> int:
    return len(
        json.dumps(
            packet.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    )


def bound_packet(packet: ContextPacket) -> ContextPacket:
    """Bound the entire serialized result, not only excerpts or English chars."""
    ceiling = min(packet.max_bytes, packet.max_estimated_tokens * 4)
    result = packet
    while True:
        result = result.model_copy(update={"estimated_tokens": math.ceil(_size(result) / 4)})
        if _size(result) <= ceiling:
            return result
        result = result.model_copy(
            update={
                "truncated": True,
                "coverage": "partial",
                "gaps": _gaps(result.gaps, (ContextGap(code="budget_limited"),)),
            }
        )
        if result.sources and any(source.text for source in result.sources):
            # Reduce the longest excerpt deterministically without splitting UTF-8.
            longest = max(
                range(len(result.sources)),
                key=lambda index: (
                    len((result.sources[index].text or "").encode("utf-8")),
                    -index,
                ),
            )
            clipped_sources = list(result.sources)
            content = clipped_sources[longest].text or ""
            clipped_sources[longest] = clipped_sources[longest].model_copy(
                update={"text": content[: len(content) // 2]},
            )
            result = result.model_copy(update={"sources": tuple(clipped_sources)})
        elif result.notes:
            result = result.model_copy(update={"notes": result.notes[:-1]})
        elif result.relations:
            result = result.model_copy(update={"relations": result.relations[:-1]})
        elif result.sources:
            sources = result.sources[:-1]
            keep = {source.reference for source in sources}
            entities = tuple(
                entity.model_copy(
                    update={
                        "references": tuple(ref for ref in entity.references if ref in keep),
                    }
                )
                for entity in result.entities
                if any(ref in keep for ref in entity.references)
            )
            ids = {entity.entity_id for entity in entities}
            result = result.model_copy(
                update={
                    "sources": sources,
                    "entities": entities,
                    "relations": tuple(
                        rel
                        for rel in result.relations
                        if rel.source in keep
                        and rel.subject_entity_id in ids
                        and rel.object_entity_id in ids
                    ),
                }
            )
        elif result.entities:
            result = result.model_copy(update={"entities": ()})
        else:
            raise ContextError("context_budget_too_small", 400)


class ContextService:
    def __init__(
        self,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.uow = UnitOfWork(factory)
        self.clock = clock

    async def _subject(self, subject: Subject, scope: MemoryScope) -> Subject:
        current = await current_context_subject(subject, self.uow.factory)
        if not _scope_allowed(current, scope):
            raise ContextError("context_scope_unavailable", 403)
        return current

    async def _audit(
        self,
        session: AsyncSession,
        subject: Subject,
        action: str,
        identity: UUID,
        request_id: str,
        **metadata: Any,
    ) -> None:
        await AuditRepository().append(
            session,
            actor_kind="user",
            actor_user_id=UUID(subject.user_id),
            action=action,
            result="success",
            reason_code="context_lifecycle",
            request_id=request_id,
            resource_id=None,
            resource_type=None,
            details={"context_id": str(identity), **metadata},
        )

    async def _select(
        self,
        request: PacketRequest,
        ontology: EnterpriseOntology,
    ) -> tuple[tuple[SOTReference, ...], tuple[str, ...], tuple[ContextGap, ...]]:
        matches = [
            match
            for match in ontology.candidate_matches(request.query, limit=10)
            if match.match_kind != "candidate"
        ]
        ids = tuple(sorted({match.entity_id for match in matches}))
        all_keys = sorted(
            {
                key
                for identity in ids
                for key in (
                    *ontology.by_id[identity].definition_record_keys,
                    *(
                        key
                        for facet in ontology.by_id[identity].profile_facets
                        for key in facet.record_keys
                    ),
                )
            }
        )
        keys = all_keys[:200]
        if not keys:
            return (), (), (ContextGap(code="unavailable"),)
        async with self.uow.factory() as session:
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT r.source_key,r.record_key,rv.version_id,rv.content_sha256
                FROM records r JOIN record_versions rv ON rv.version_id=r.current_version_id
                WHERE r.record_key=ANY(CAST(:keys AS text[]))
                  AND (cardinality(CAST(:sources AS text[]))=0
                    OR r.source_key=ANY(CAST(:sources AS text[])))
                ORDER BY r.source_key,r.record_key LIMIT 21
            """),
                        {"keys": keys, "sources": list(request.source_keys)},
                    )
                )
                .mappings()
                .all()
            )
        refs = tuple(
            SOTReference(
                source_key=row["source_key"],
                record_key=row["record_key"],
                record_version_id=row["version_id"],
                content_sha256=str(row["content_sha256"]),
            )
            for row in rows[:20]
        )
        # This generic gap never discloses denied identifiers/counts.
        gaps: tuple[ContextGap, ...] = (
            (ContextGap(code="unavailable"),) if len(rows) < len(keys) else ()
        )
        if len(all_keys) > 200 or len(rows) > 20:
            gaps += (ContextGap(code="budget_limited"),)
        if any(match.match_kind in {"weak", "partial"} for match in matches):
            gaps += (ContextGap(code="ambiguous"),)
        surfaces: dict[str, set[str]] = {}
        for match in matches:
            surfaces.setdefault(match.matched_surface, set()).add(match.entity_id)
        if any(len(identities) > 1 for identities in surfaces.values()):
            gaps += (ContextGap(code="ambiguous"),)
        source_keys: dict[str, set[str]] = {}
        for row in rows:
            source_keys.setdefault(row["record_key"], set()).add(row["source_key"])
        if not request.source_keys and any(len(sources) > 1 for sources in source_keys.values()):
            gaps += (ContextGap(code="ambiguous"),)
        return refs, ids, gaps

    async def _entities(
        self,
        ontology: EnterpriseOntology,
        ids: tuple[str, ...],
        refs: tuple[SOTReference, ...],
    ) -> tuple[EntityProjection, ...]:
        output: list[EntityProjection] = []
        for identity in ids[:10]:
            entity = ontology.by_id.get(identity)
            if entity is None:
                continue
            keys = {
                *entity.definition_record_keys,
                *(key for facet in entity.profile_facets for key in facet.record_keys),
            }
            backing = tuple(ref for ref in refs if ref.record_key in keys)
            if backing:
                output.append(
                    EntityProjection(
                        entity_id=identity,
                        canonical_name=entity.canonical_name,
                        entity_type=entity.entity_type,
                        domain=entity.domain,
                        references=backing,
                    )
                )
        return tuple(output)

    async def _relations(
        self,
        subject: Subject,
        refs: tuple[SOTReference, ...],
        ids: set[str],
        use_class: UseClass,
        request_id: str,
    ) -> tuple[RelationAssertion, ...]:
        # Purpose and ACL precede the dedicated relation projection query.
        allowed = await revalidate_sot_references(
            subject,
            refs,
            factory=self.uow.factory,
            use_class=use_class,
            request_id=request_id,
            now=self.clock(),
        )
        result: list[RelationAssertion] = []
        async with self.uow.factory() as session:
            for source in allowed.sources:
                ref = source.reference
                raw = await session.scalar(
                    text("""
                    SELECT value_payload->'context_relations' FROM record_versions
                    WHERE version_id=:version
                """),
                    {"version": ref.record_version_id},
                )
                keys = set(
                    (
                        await session.execute(
                            text("""
                    SELECT evidence_key FROM evidence_spans
                    WHERE record_version_id=:version AND lifecycle='active' LIMIT 1000
                """),
                            {"version": ref.record_version_id},
                        )
                    ).scalars()
                )
                for value in raw[:20] if isinstance(raw, list) else []:
                    try:
                        rel = ExplicitRelation.model_validate(value)
                    except ValidationError:
                        continue
                    if (
                        rel.subject_entity_id in ids
                        and rel.object_entity_id in ids
                        and rel.evidence_key in keys
                    ):
                        result.append(RelationAssertion(**rel.model_dump(), source=ref))
                        if len(result) == 20:
                            return tuple(result)
        return tuple(result)

    async def resolve(
        self,
        subject: Subject,
        request: PacketRequest,
        *,
        request_id: str,
        persist: bool = False,
    ) -> ContextPacket:
        current = await self._subject(subject, request.scope)
        ontology = await load_runtime_ontology(self.uow.factory)
        refs, ids, gaps = await self._select(request, ontology)
        packet = await self._assemble(
            current,
            uuid4(),
            request.scope,
            request.use_class,
            ontology.digest,
            refs,
            ids,
            request.max_bytes,
            request.max_estimated_tokens,
            request_id=request_id,
            initial_gaps=gaps,
            include_memory=request.include_memory,
        )
        if persist:
            async with self.uow.transaction() as session:
                await session.execute(
                    text("""
                    INSERT INTO context_packets(packet_id,owner_subject_id,scope_kind,scope_key,
                      use_class,ontology_digest,query_digest,source_refs,entity_ids,memory_refs,
                      max_bytes,max_estimated_tokens,gap_codes,selection_truncated)
                    VALUES (:id,:owner,:kind,:key,:purpose,:ontology,:query,
                      CAST(:refs AS jsonb),:entities,CAST(:memories AS jsonb),:bytes,:tokens,
                      :gaps,:truncated)
                """),
                    {
                        "id": packet.packet_id,
                        "owner": UUID(current.user_id),
                        "kind": request.scope.kind,
                        "key": request.scope.key,
                        "purpose": request.use_class,
                        "ontology": packet.ontology_digest,
                        "query": hashlib.sha256(request.query.encode()).hexdigest(),
                        "refs": json.dumps(
                            [source.reference.model_dump(mode="json") for source in packet.sources]
                        ),
                        "entities": [entity.entity_id for entity in packet.entities],
                        "memories": json.dumps(
                            [
                                {"memory_id": str(note.memory_id), "revision": note.revision}
                                for note in packet.notes
                            ]
                        ),
                        "bytes": request.max_bytes,
                        "tokens": request.max_estimated_tokens,
                        "gaps": [gap.code for gap in packet.gaps],
                        "truncated": packet.truncated,
                    },
                )
                await self._audit(
                    session,
                    current,
                    "context.packet.create",
                    packet.packet_id,
                    request_id,
                    use_class=request.use_class,
                )
            # Persistence is not authorization for the subsequent disclosure.
            return await self.read_packet(subject, packet.packet_id, request_id=request_id)
        return packet

    async def _assemble(
        self,
        subject: Subject,
        packet_id: UUID,
        scope: MemoryScope,
        use_class: UseClass,
        ontology_digest: str,
        refs: tuple[SOTReference, ...],
        ids: tuple[str, ...],
        max_bytes: int,
        max_tokens: int,
        *,
        request_id: str,
        initial_gaps: tuple[ContextGap, ...] = (),
        include_memory: bool = False,
        memory_refs: tuple[dict[str, Any], ...] = (),
        initial_truncated: bool = False,
    ) -> ContextPacket:
        current = await self._subject(subject, scope)
        resolution = await revalidate_sot_references(
            current,
            refs,
            factory=self.uow.factory,
            use_class=use_class,
            request_id=request_id,
            now=self.clock(),
            include_text=True,
        )
        ontology = await load_runtime_ontology(self.uow.factory)
        gaps = _gaps(initial_gaps, resolution.gaps)
        if ontology.digest != ontology_digest:
            ids = ()
            gaps = _gaps(gaps, (ContextGap(code="ontology_changed"),))
        entities = await self._entities(
            ontology, ids, tuple(s.reference for s in resolution.sources)
        )
        relations = await self._relations(
            current,
            tuple(s.reference for s in resolution.sources),
            {entity.entity_id for entity in entities},
            use_class,
            request_id,
        )
        notes: list[MemoryView] = []
        if include_memory:
            try:
                notes.extend(
                    await self.list_memory(
                        current, scope, use_class=use_class, request_id=request_id, limit=20
                    )
                )
            except ContextError:
                gaps = _gaps(gaps, (ContextGap(code="memory_unavailable"),))
        for memory_ref in memory_refs[:20]:
            try:
                note = await self.read_memory(
                    current,
                    UUID(memory_ref["memory_id"]),
                    use_class=use_class,
                    request_id=request_id,
                )
                if note.revision == memory_ref["revision"] and note.text is not None:
                    notes.append(note)
                else:
                    gaps = _gaps(gaps, (ContextGap(code="memory_unavailable"),))
            except ContextError:
                gaps = _gaps(gaps, (ContextGap(code="memory_unavailable"),))
        # Mandatory final recheck, after relations/memory loads; no nested checkout.
        final = await revalidate_sot_references(
            current,
            tuple(s.reference for s in resolution.sources),
            factory=self.uow.factory,
            use_class=use_class,
            request_id=request_id,
            now=self.clock(),
        )
        await self._subject(final.subject, scope)
        keep = {source.reference for source in final.sources}
        sources = tuple(source for source in resolution.sources if source.reference in keep)
        entities = await self._entities(
            ontology, ids, tuple(source.reference for source in sources)
        )
        visible_ids = {entity.entity_id for entity in entities}
        relations = tuple(
            rel
            for rel in relations
            if rel.source in keep
            and rel.subject_entity_id in visible_ids
            and rel.object_entity_id in visible_ids
        )
        # Re-read every selected note at the final boundary, including its refs.
        final_notes: list[MemoryView] = []
        for note in notes[:20]:
            try:
                fresh = await self.read_memory(
                    final.subject, note.memory_id, use_class=use_class, request_id=request_id
                )
            except ContextError:
                gaps = _gaps(gaps, (ContextGap(code="memory_unavailable"),))
                continue
            if fresh.text is not None and fresh.revision == note.revision:
                final_notes.append(fresh)
            else:
                gaps = _gaps(gaps, (ContextGap(code="memory_unavailable"),))
        gaps = _gaps(gaps, final.gaps)
        # Notes are also live reads. Recheck sources after their final read boundary.
        final = await revalidate_sot_references(
            final.subject,
            tuple(source.reference for source in sources),
            factory=self.uow.factory,
            use_class=use_class,
            request_id=request_id,
            now=self.clock(),
        )
        await self._subject(final.subject, scope)
        keep = {source.reference for source in final.sources}
        sources = tuple(source for source in sources if source.reference in keep)
        entities = await self._entities(
            ontology, ids, tuple(source.reference for source in sources)
        )
        visible_ids = {entity.entity_id for entity in entities}
        relations = tuple(
            rel
            for rel in relations
            if rel.source in keep
            and rel.subject_entity_id in visible_ids
            and rel.object_entity_id in visible_ids
        )
        gaps = _gaps(gaps, final.gaps)
        if not sources and not final_notes:
            # Do not reveal candidate names/counts/owners when no backing fact is permitted.
            entities, relations = (), ()
            gaps = (ContextGap(code="unavailable"),)
        return bound_packet(
            ContextPacket(
                packet_id=packet_id,
                caller_id=UUID(final.subject.user_id),
                scope=scope,
                use_class=use_class,
                ontology_digest=ontology_digest,
                retrieved_at=self.clock(),
                sources=sources,
                entities=entities,
                relations=relations,
                notes=tuple(final_notes),
                gaps=gaps,
                coverage="partial" if gaps else "supported",
                max_bytes=max_bytes,
                max_estimated_tokens=max_tokens,
                truncated=initial_truncated or any(gap.code == "budget_limited" for gap in gaps),
            ).model_copy(
                update={
                    "coverage": "unavailable"
                    if not sources and not final_notes
                    else "partial"
                    if gaps
                    else "supported"
                }
            )
        )

    async def read_packet(
        self,
        subject: Subject,
        packet_id: UUID,
        *,
        request_id: str,
    ) -> ContextPacket:
        current = await current_context_subject(subject, self.uow.factory)
        async with self.uow.factory() as session:
            row = (
                (
                    await session.execute(
                        text("""
                SELECT * FROM context_packets WHERE packet_id=:id AND owner_subject_id=:owner
            """),
                        {"id": packet_id, "owner": UUID(current.user_id)},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ContextError("context_packet_unavailable", 404)
        return await self._assemble(
            current,
            packet_id,
            _scope(row),
            row["use_class"],
            row["ontology_digest"],
            _refs(row["source_refs"]),
            tuple(row["entity_ids"]),
            row["max_bytes"],
            row["max_estimated_tokens"],
            request_id=request_id,
            memory_refs=tuple(row["memory_refs"]),
            initial_gaps=tuple(
                ContextGap.model_validate({"code": code}) for code in row["gap_codes"]
            ),
            initial_truncated=row["selection_truncated"],
        )

    def _expiry(self, expiry: datetime, created_at: datetime) -> None:
        instant = self.clock()
        if expiry.tzinfo is None or not instant < expiry <= created_at + MAX_TTL:
            raise ContextError("memory_ttl_invalid", 422)

    async def _memory_admission(
        self,
        subject: Subject,
        request: MemoryCreate,
        request_id: str,
    ) -> Subject:
        current = await self._subject(subject, request.scope)
        if not _scope_allowed(current, request.scope, team_write=True):
            raise ContextError("memory_scope_write_denied", 403)
        if not request.text.strip():
            raise ContextError("memory_text_invalid", 422)
        result = await revalidate_sot_references(
            current,
            request.references,
            factory=self.uow.factory,
            use_class=request.use_class,
            request_id=request_id,
            now=self.clock(),
        )
        if len(result.sources) != len(request.references):
            raise ContextError("memory_sources_unavailable", 409)
        if not _scope_allowed(result.subject, request.scope, team_write=True):
            raise ContextError("memory_scope_write_denied", 403)
        return result.subject

    async def create_memory(
        self,
        subject: Subject,
        request: MemoryCreate,
        *,
        request_id: str,
    ) -> MemoryView:
        instant = self.clock()
        self._expiry(request.expires_at, instant)
        current = await self._memory_admission(subject, request, request_id)
        identity = uuid4()
        async with self.uow.transaction() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:owner))"), {"owner": current.user_id}
            )
            count = await session.scalar(
                text("""
                SELECT count(*) FROM memory_entries WHERE owner_subject_id=:owner
                  AND lifecycle='active' AND expires_at>:now
            """),
                {"owner": UUID(current.user_id), "now": instant},
            )
            if int(count or 0) >= MAX_MEMORY:
                raise ContextError("memory_count_budget", 409)
            await session.execute(
                text("""
                INSERT INTO memory_entries(memory_id,owner_subject_id,scope_kind,scope_key,kind,
                  note_text,source_refs,use_class,expires_at,created_at,updated_at)
                VALUES (:id,:owner,:scope,:key,:kind,:content,CAST(:refs AS jsonb),
                  :purpose,:expiry,:now,:now)
            """),
                {
                    "id": identity,
                    "owner": UUID(current.user_id),
                    "scope": request.scope.kind,
                    "key": request.scope.key,
                    "kind": request.kind,
                    "content": request.text,
                    "refs": json.dumps([ref.model_dump(mode="json") for ref in request.references]),
                    "purpose": request.use_class,
                    "expiry": request.expires_at,
                    "now": instant,
                },
            )
            await self._audit(
                session,
                current,
                "memory.create",
                identity,
                request_id,
                revision=1,
                kind=request.kind,
            )
        return await self.read_memory(current, identity, request_id=request_id)

    async def read_memory(
        self,
        subject: Subject,
        memory_id: UUID,
        *,
        request_id: str,
        use_class: UseClass | None = None,
    ) -> MemoryView:
        current = await current_context_subject(subject, self.uow.factory)
        async with self.uow.factory() as session:
            row = (
                (
                    await session.execute(
                        text("""
                SELECT memory_id,owner_subject_id,scope_kind,scope_key,kind,source_refs,use_class,
                  revision,lifecycle,expires_at,created_at,updated_at FROM memory_entries
                WHERE memory_id=:id
            """),
                        {"id": memory_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if (
            row is None
            or (row["scope_kind"] == "private" and row["owner_subject_id"] != UUID(current.user_id))
            or not _scope_allowed(current, _scope(row))
        ):
            raise ContextError("memory_unavailable", 404)
        refs = _refs(row["source_refs"])
        purpose: UseClass = use_class or row["use_class"]
        state = row["lifecycle"]
        note_text: str | None = None
        if state == "active" and row["expires_at"] <= self.clock():
            state = "expired"
        if state == "active":
            result = await revalidate_sot_references(
                current,
                refs,
                factory=self.uow.factory,
                use_class=purpose,
                request_id=request_id,
                now=self.clock(),
            )
            if not _scope_allowed(result.subject, _scope(row)):
                raise ContextError("memory_unavailable", 404)
            if len(result.sources) != len(refs) or USE_CLASSES.index(purpose) > USE_CLASSES.index(
                row["use_class"]
            ):
                state = "withheld"
            else:
                async with self.uow.factory() as session:
                    note_text = await session.scalar(
                        text("""
                        SELECT note_text FROM memory_entries WHERE memory_id=:id
                          AND revision=:revision AND lifecycle='active' AND expires_at>:now
                    """),
                        {"id": memory_id, "revision": row["revision"], "now": self.clock()},
                    )
                final = await revalidate_sot_references(
                    current,
                    refs,
                    factory=self.uow.factory,
                    use_class=purpose,
                    request_id=request_id,
                    now=self.clock(),
                )
                if not _scope_allowed(final.subject, _scope(row)):
                    raise ContextError("memory_unavailable", 404)
                if len(final.sources) != len(refs):
                    state, note_text = "withheld", None
                # A delete/correction may happen while source permissions are rechecked.
                # Only the same still-live revision may disclose the text loaded above.
                async with self.uow.factory() as session:
                    unchanged = await session.scalar(
                        text("""
                        SELECT 1 FROM memory_entries WHERE memory_id=:id AND revision=:revision
                          AND lifecycle='active' AND expires_at>:now
                    """),
                        {"id": memory_id, "revision": row["revision"], "now": self.clock()},
                    )
                if not unchanged:
                    state, note_text = "withheld", None
        return MemoryView.model_validate(
            {
                "memory_id": memory_id,
                "owner_subject_id": row["owner_subject_id"],
                "scope": _scope(row),
                "kind": row["kind"],
                "text": note_text,
                "references": refs if note_text is not None else (),
                "use_class": row["use_class"],
                "revision": row["revision"],
                "lifecycle": state,
                "expires_at": row["expires_at"],
                "updated_at": row["updated_at"],
            }
        )

    async def list_memory(
        self,
        subject: Subject,
        scope: MemoryScope,
        *,
        request_id: str,
        use_class: UseClass = "proposal",
        limit: int = 20,
    ) -> tuple[MemoryView, ...]:
        current = await self._subject(subject, scope)
        async with self.uow.factory() as session:
            ids = (
                (
                    await session.execute(
                        text("""
                SELECT memory_id FROM memory_entries WHERE scope_kind=:kind
                  AND scope_key IS NOT DISTINCT FROM :key
                  AND (:kind<>'private' OR owner_subject_id=:owner)
                  AND lifecycle='active' AND expires_at>:now
                ORDER BY updated_at DESC,memory_id LIMIT :limit
            """),
                        {
                            "kind": scope.kind,
                            "key": scope.key,
                            "owner": UUID(current.user_id),
                            "now": self.clock(),
                            "limit": min(max(limit, 1), 20),
                        },
                    )
                )
                .scalars()
                .all()
            )
        result: list[MemoryView] = []
        for identity in ids:
            try:
                view = await self.read_memory(
                    current, identity, use_class=use_class, request_id=request_id
                )
            except ContextError:
                continue
            if view.text is not None:
                result.append(view)
        return tuple(result)

    async def correct_memory(
        self,
        subject: Subject,
        memory_id: UUID,
        request: MemoryCorrection,
        *,
        request_id: str,
    ) -> MemoryView:
        current = await current_context_subject(subject, self.uow.factory)
        async with self.uow.factory() as session:
            row = (
                (
                    await session.execute(
                        text("""
                SELECT owner_subject_id,scope_kind,scope_key,created_at FROM memory_entries
                WHERE memory_id=:id AND lifecycle='active'
            """),
                        {"id": memory_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or row["owner_subject_id"] != UUID(current.user_id):
            raise ContextError("memory_unavailable", 404)
        if request.scope != _scope(row):
            raise ContextError("memory_scope_change_forbidden", 409)
        self._expiry(request.expires_at, row["created_at"])
        current = await self._memory_admission(current, request, request_id)
        async with self.uow.transaction() as session:
            changed = await session.scalar(
                text("""
                UPDATE memory_entries SET kind=:kind,note_text=:content,
                  source_refs=CAST(:refs AS jsonb),use_class=:purpose,expires_at=:expiry,
                  revision=revision+1,updated_at=:now
                WHERE memory_id=:id AND owner_subject_id=:owner
                  AND revision=:revision AND lifecycle='active' RETURNING revision
            """),
                {
                    "id": memory_id,
                    "owner": UUID(current.user_id),
                    "kind": request.kind,
                    "content": request.text,
                    "refs": json.dumps([ref.model_dump(mode="json") for ref in request.references]),
                    "purpose": request.use_class,
                    "expiry": request.expires_at,
                    "now": self.clock(),
                    "revision": request.expected_revision,
                },
            )
            if changed is None:
                raise ContextError("memory_revision_conflict", 409)
            await self._audit(
                session, current, "memory.correct", memory_id, request_id, revision=int(changed)
            )
        return await self.read_memory(current, memory_id, request_id=request_id)

    async def delete_memory(
        self,
        subject: Subject,
        memory_id: UUID,
        expected_revision: int,
        *,
        request_id: str,
    ) -> MemoryTombstone:
        current = await current_context_subject(subject, self.uow.factory)
        # An active original owner may redact their own note after scope revocation;
        # this operation reveals no note, scope, source refs or prior content.
        async with self.uow.transaction() as session:
            row = (
                await session.execute(
                    text("""
                SELECT revision,lifecycle FROM memory_entries WHERE memory_id=:id
                  AND owner_subject_id=:owner FOR UPDATE
            """),
                    {"id": memory_id, "owner": UUID(current.user_id)},
                )
            ).one_or_none()
            if row is None:
                raise ContextError("memory_unavailable", 404)
            if row[0] != expected_revision:
                raise ContextError("memory_revision_conflict", 409)
            if row[1] == "deleted":
                return MemoryTombstone(memory_id=memory_id, revision=row[0])
            revision = await session.scalar(
                text("""
                UPDATE memory_entries SET note_text=NULL,source_refs='[]',lifecycle='deleted',
                  revision=revision+1,deleted_at=:now,updated_at=:now
                WHERE memory_id=:id RETURNING revision
            """),
                {"id": memory_id, "now": self.clock()},
            )
            await self._audit(
                session, current, "memory.delete", memory_id, request_id, revision=int(revision)
            )
        return MemoryTombstone(memory_id=memory_id, revision=int(revision))
