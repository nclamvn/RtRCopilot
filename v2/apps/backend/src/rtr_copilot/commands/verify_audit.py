import asyncio

from rtr_copilot.db.engine import session_factory
from rtr_copilot.repositories.audit import AuditRepository


async def verify() -> int:
    async with session_factory()() as session:
        valid, count, head = await AuditRepository().verify(session)
    print(f"audit_chain_valid={str(valid).lower()} count={count} head={head or 'none'}")
    return 0 if valid else 1


def main() -> None:
    raise SystemExit(asyncio.run(verify()))


if __name__ == "__main__":
    main()
