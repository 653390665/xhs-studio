"""Draft list readiness: one aggregate query, no per-draft preflight."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api.drafts import get_drafts
from backend.app.core.database import Base
from backend.app.models import AiDraft, DraftAsset, PlatformAccount, User


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'draft-readiness.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def test_draft_list_reports_media_and_account_readiness(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="draft-owner", password_hash="x")
        db.add(user)
        db.flush()
        account = PlatformAccount(
            user_id=user.id,
            platform="xhs",
            sub_type="pc",
            nickname="pc",
            status="active",
        )
        db.add(account)
        db.flush()

        with_media = AiDraft(
            user_id=user.id,
            platform="xhs",
            title="有图",
            body="正文",
            platform_account_id=account.id,
        )
        without_media = AiDraft(
            user_id=user.id,
            platform="xhs",
            title="缺图",
            body="正文",
            platform_account_id=account.id,
        )
        without_account = AiDraft(
            user_id=user.id,
            platform="xhs",
            title="缺账号",
            body="正文",
        )
        db.add_all([with_media, without_media, without_account])
        db.flush()
        db.add(
            DraftAsset(
                draft_id=with_media.id,
                asset_type="image",
                url="https://example.com/a.png",
            )
        )
        db.commit()

        result = get_drafts(
            platform="xhs",
            current_user=user,
            db=db,
            page=1,
            page_size=20,
        )
        items = {item["id"]: item for item in result["items"]}

        assert items[with_media.id]["media_ready"] is True
        assert items[with_media.id]["asset_count"] == 1
        assert items[with_media.id]["image_count"] == 1
        assert items[with_media.id]["account_ready"] is True
        assert items[without_media.id]["media_ready"] is False
        assert items[without_media.id]["asset_count"] == 0
        assert items[without_account.id]["account_ready"] is False
    finally:
        db.close()
