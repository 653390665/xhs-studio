from __future__ import annotations

from typing import Any, Iterable


def paginated(
    items: Iterable[Any],
    page: int = 1,
    page_size: int = 20,
    extra: dict | None = None,
    *,
    max_size: int = 100,
    total: int | None = None,
) -> dict:
    """Page a materialized list, optionally attaching response metadata.

    ``extra`` exists because a filtered list needs to explain itself. When the
    follower-count filter drops notes whose author was never measured, the count
    that comes back is honest but incomplete; the caller needs to say how many
    were skipped, or the number reads as "this is all there is".

    ``max_size`` defaults to 100 and exists because a hard-coded 100 used to
    silently truncate callers that advertised more: ``/api/publish/jobs`` declares
    ``le=500`` and the queue asks for 500, but only 100 rows came back while
    ``total``/``counts`` described the whole table — the number and the list
    disagreed. Callers that legitimately need a bigger page pass their own cap
    here, so the contract is explicit instead of hidden in this module.

    ``total`` is for callers that已 在 SQL 层分页：它们传进来的 ``items``
    只是当页，真正的总数由 ``count()`` 单独算。不传时仍按「materialize 全部再切片」
    的老行为（大多数列表只有几十行，够用且不改调用方）。
    """
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), max(1, max_size))
    materialized = list(items)
    if total is not None:
        # 已经是当页数据，不再切片（再切一次会从第 1 条开始）。
        payload = {
            "total": int(total),
            "page": safe_page,
            "page_size": safe_page_size,
            "items": materialized,
        }
    else:
        start = (safe_page - 1) * safe_page_size
        end = start + safe_page_size
        payload = {
            "total": len(materialized),
            "page": safe_page,
            "page_size": safe_page_size,
            "items": materialized[start:end],
        }
    if extra:
        payload.update(extra)
    return payload
