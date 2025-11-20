from __future__ import annotations

from typing import Any, Optional

from app.core import db as dal


async def add_ati_lead(
    uid: int,
    *,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    payload: str,
    source: str,
    status: str = "new",
    extra: Optional[dict[str, Any]] = None,
) -> None:
    await dal.add_b2b_ati_lead(
        uid,
        username=username,
        first_name=first_name,
        last_name=last_name,
        payload=payload,
        source=source,
        status=status,
        extra=extra,
    )
