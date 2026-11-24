from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.app.models import PublishJob


def claim_publish_job(db: Session, job_id: int, expected_status: str) -> bool:
    """Atomically move one publish job from expected_status to publishing.

    The read-then-write checks in the API/scheduler are not enough: two
    requests can both pass them before either sets ``publishing``. This
    conditional UPDATE lets exactly one caller win, including across workers
    sharing the same database.
    """
    result = db.execute(
        update(PublishJob)
        .where(
            PublishJob.id == job_id,
            PublishJob.status == expected_status,
        )
        .values(status="publishing")
    )
    db.commit()
    return (result.rowcount or 0) == 1
