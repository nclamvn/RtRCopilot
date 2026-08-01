"""Read an admin-editable integer limit from governance ``SETTING_REGISTRY``.

Cost budgets and job concurrency caps are versioned, bounded governance
settings (admin-editable via the existing settings surface). They are consulted
only at low-frequency decision points (per ask, per job submission), so a single
governed read with a registry-default fallback is appropriate. The import is
deferred to keep the ``limits`` package free of a top-level cycle with
``governance.service`` (which imports ``ingestion.api``).
"""

from sqlalchemy.ext.asyncio import AsyncSession


async def effective_int_setting(session: AsyncSession, key: str) -> int:
    from rtr_copilot.governance.service import SETTING_REGISTRY
    from rtr_copilot.repositories.governance import GovernanceRepository

    spec = SETTING_REGISTRY[key]
    stored = await GovernanceRepository().get_setting(session, key)
    value = stored.value if stored is not None else spec.default
    if isinstance(value, bool) or not isinstance(value, int | float):
        value = spec.default
    return int(value)
