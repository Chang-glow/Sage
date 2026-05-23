"""Data integrity utilities — write-read verification for critical DB operations.

Each verifier writes a WARNING log (not an exception) on mismatch — the write
already succeeded; this is a diagnostic signal for investigation, not a rollback.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select

logger = structlog.get_logger()


async def verify_insert(db, model: type, pk_value: Any, pk_column: str = "id") -> bool:
    """Write-read verification: confirm a just-inserted row is retrievable."""
    col = getattr(model, pk_column)
    result = await db.execute(select(func.count()).select_from(model).where(col == pk_value))
    count = result.scalar_one()
    if count != 1:
        logger.warning(
            "write_read_mismatch",
            model=model.__tablename__,
            pk_column=pk_column,
            pk_value=str(pk_value),
            found_count=count,
        )
        return False
    return True


async def verify_count(
    db, model: type, expected: int, *, where_col: str | None = None, where_val: Any = None
) -> bool:
    """Confirm row count matches expected after a bulk operation."""
    stmt = select(func.count()).select_from(model)
    if where_col is not None:
        stmt = stmt.where(getattr(model, where_col) == where_val)
    result = await db.execute(stmt)
    actual = result.scalar_one()
    if actual != expected:
        logger.warning(
            "write_read_count_mismatch",
            model=model.__tablename__,
            expected=expected,
            actual=actual,
        )
        return False
    return True
