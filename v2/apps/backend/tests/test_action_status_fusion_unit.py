"""R14 fixed admission inventory; engine construction only, no DB connection."""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.policy import ActionPolicy
from rtr_copilot.actions.service import ActionService
from rtr_copilot.db.uow import UnitOfWork

CASES = (
    "custom_factory",
    "custom_session",
    "connection_bind",
    "unsupported_options",
    "policy_override",
    "mismatched_policy_factory_same_url",
    "default_unknown_isolation",
    "repeatable_read",
    "serializable",
)


@pytest.mark.parametrize("case", CASES, ids=CASES)
@pytest.mark.asyncio
async def test_origin_gate_rejects_unknown_custom_overridden_and_mismatched_before_db(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = create_async_engine("postgresql+asyncpg://synthetic:synthetic@invalid/domain")
    explicit = base.execution_options(isolation_level="READ COMMITTED")
    factory = async_sessionmaker(explicit, expire_on_commit=False)
    service = ExecutionService(UnitOfWork(factory))
    assert service._status_read_admitted()
    variants: list[ExecutionService] = []

    def add(changed: Any) -> ExecutionService:
        item = ExecutionService(UnitOfWork(changed))
        variants.append(item)
        return item

    if case == "custom_factory":

        class CustomFactory(async_sessionmaker[AsyncSession]):
            pass

        add(CustomFactory(explicit, expire_on_commit=False))
        add(lambda: (_ for _ in ()).throw(AssertionError("factory invoked")))
    elif case == "custom_session":

        class CustomSession(AsyncSession):
            pass

        add(async_sessionmaker(explicit, class_=CustomSession, expire_on_commit=False))
    elif case == "connection_bind":
        add(async_sessionmaker(explicit.connect(), expire_on_commit=False))
    elif case == "unsupported_options":
        add(async_sessionmaker(explicit, expire_on_commit=True))
        add(async_sessionmaker(explicit, expire_on_commit=False, autoflush=False))
        add(async_sessionmaker(explicit, expire_on_commit=False, binds={object: explicit}))
        add(async_sessionmaker(explicit, expire_on_commit=False, sync_session_class=object))
        add(
            async_sessionmaker(
                explicit.execution_options(logging_token="custom"), expire_on_commit=False
            )
        )
    elif case == "policy_override":

        class CustomPolicy(ActionPolicy):
            pass

        class CustomActions(ActionService):
            pass

        class CustomUow(UnitOfWork):
            pass

        class CustomExecution(ExecutionService):
            pass

        item = add(factory)
        item.actions.policy = CustomPolicy(item.uow)
        variants.append(
            ExecutionService(UnitOfWork(factory), actions=CustomActions(UnitOfWork(factory)))
        )
        variants.append(ExecutionService(CustomUow(factory)))
        variants.append(CustomExecution(UnitOfWork(factory)))
        item = add(factory)
        item.actions.policy.current = item.actions.policy.current  # type: ignore[method-assign]
        item = add(factory)
        item._row = item._row  # type: ignore[method-assign]
        item = add(factory)
        item._owner = item._owner  # type: ignore[method-assign]
        item = add(factory)
        item._view = item._view  # type: ignore[method-assign]
    elif case == "mismatched_policy_factory_same_url":
        other = async_sessionmaker(explicit, expire_on_commit=False)
        item = add(factory)
        item.actions.policy.uow = UnitOfWork(other)
        item = add(factory)
        item.actions.uow = UnitOfWork(other)
    elif case == "default_unknown_isolation":
        add(async_sessionmaker(base, expire_on_commit=False))
        # Cached default information is deliberately not an admission credential.
        base.sync_engine.dialect.default_isolation_level = "READ COMMITTED"
    else:
        level = "REPEATABLE READ" if case == "repeatable_read" else "SERIALIZABLE"
        add(
            async_sessionmaker(
                base.execution_options(isolation_level=level), expire_on_commit=False
            )
        )

    async def no_session(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("candidate performed DB work")

    monkeypatch.setattr(AsyncSession, "execute", no_session)
    for item in variants:
        assert not item._status_read_admitted()
        seen: list[str] = []
        sentinel = object()

        async def old_owner(*args: Any, trace: list[str] = seen) -> None:
            trace.append("owner")

        async def old_view(*args: Any, trace: list[str] = seen, result: Any = sentinel) -> Any:
            trace.append("view")
            return result

        monkeypatch.setattr(item, "_owner", old_owner)
        monkeypatch.setattr(item, "_view", old_view)
        assert await item.status(object(), uuid.uuid4()) is sentinel  # type: ignore[arg-type]
        assert seen == ["owner", "view"]
    await base.dispose()
