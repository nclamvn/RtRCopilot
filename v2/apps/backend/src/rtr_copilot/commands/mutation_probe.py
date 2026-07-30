import asyncio

from sqlalchemy import text

from rtr_copilot.db.uow import MaintenanceActive, UnitOfWork


async def probe() -> int:
    try:
        async with UnitOfWork().transaction() as session:
            await session.execute(text("SELECT 1"))
    except MaintenanceActive:
        print("mutation_probe=denied maintenance_active=true")
        return 0
    print("mutation_probe=unexpectedly_allowed maintenance_active=false")
    return 1


def main() -> None:
    raise SystemExit(asyncio.run(probe()))


if __name__ == "__main__":
    main()
