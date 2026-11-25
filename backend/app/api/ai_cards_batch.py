"""批量：一次把多篇草稿拆页 + 出图。

为什么需要
----------
单篇一条一条点，20 篇要重复 20 次「拆页→确认→生成」。这是纯体力活，
而真正的风险在别处：某一篇没配图、某一篇正文太短拆不出内容页、
某一篇拆页结果不合意。所以批量的价值不是"少点几次"，是**一次看到所有问题**。

实现取舍
--------
· 同步接口（一个请求跑完一批）。草稿数量本来就不大（一次最多 10 篇），
  而且用户需要立刻知道哪几篇失败、为什么失败。
· 单篇失败不中断整批：每篇结果单独记 status / error。
· 不在后台跑任务：后台跑的话用户还得轮询，不如直接等（每篇约 20-60 秒）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.ai import (
    ImageAiClient,
    _image_model_context,
    _materialize_image_data,
    get_image_ai_client,
)
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiDraft, AiGeneratedAsset, User
from backend.app.services.xhs_card_planner import plan_pages
from backend.app.services.xhs_card_style import (
    ALLOWED_SIZES,
    DEFAULT_SIZE,
    build_page_prompt,
    resolve_preset,
)

router = APIRouter(prefix="/ai/cards", tags=["ai-cards"])

MAX_BATCH_DRAFTS = 10
MAX_PAGES_PER_DRAFT = 6


class BatchRequest(BaseModel):
    draft_ids: list[int] = Field(min_length=1, max_length=MAX_BATCH_DRAFTS)
    preset: str | None = None
    style: str | None = None
    layout: str | None = None
    size: str = Field(default=DEFAULT_SIZE, max_length=32)
    max_pages: int = Field(default=5, ge=1, le=MAX_PAGES_PER_DRAFT)
    # 生成后是否自动挂到对应草稿（顺序即页序）
    attach_to_draft: bool = True
    # 覆盖已有配图（默认追加）
    replace_images: bool = False


@router.post("/batch")
def batch_generate(
    payload: BatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    image_ai_client: ImageAiClient = Depends(get_image_ai_client),
):
    """批量：每篇草稿 → 拆页 → 逐页出图 →（可选）挂到草稿。

    返回每一篇的独立结果，单篇失败不影响其它篇。
    """
    if payload.size not in ALLOWED_SIZES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的尺寸 {payload.size}，可用：{', '.join(ALLOWED_SIZES)}",
        )

    drafts = db.scalars(
        select(AiDraft).where(
            AiDraft.user_id == current_user.id,
            AiDraft.id.in_(payload.draft_ids),
        )
    ).all()
    found = {d.id: d for d in drafts}

    missing = [i for i in payload.draft_ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"这些草稿不存在或不属于你：{missing}",
        )

    base_style, base_layout = resolve_preset(payload.preset, payload.style, payload.layout)
    model_config, api_key = _image_model_context(db, current_user)

    results: list[dict[str, Any]] = []

    for draft_id in payload.draft_ids:
        draft = found[draft_id]
        entry: dict[str, Any] = {
            "draft_id": draft_id,
            "title": draft.title or "",
        }
        pages = plan_pages(
            title=draft.title or "",
            body=(draft.body or "").strip(),
            max_pages=payload.max_pages,
        )
        entry["page_count"] = len(pages)
        if not (draft.body or "").strip():
            entry["status"] = "skipped"
            entry["reason"] = "正文为空，没有可拆的内容"
            results.append(entry)
            continue

        generated: list[dict[str, Any]] = []
        anchor_url: str | None = None
        draft_failed = False

        for idx, page in enumerate(pages, start=1):
            prompt = build_page_prompt(
                title=page.title,
                lines=page.lines,
                page_type=page.page_type,
                style_key=base_style,
                layout_key=base_layout,
                index=idx,
                total=len(pages),
                size=payload.size,
                illustration=page.illustration,
                illustration_hint=page.illustration_hint,
            )
            refs = [anchor_url] if (anchor_url and idx > 1) else None
            try:
                outcome = image_ai_client.generate_image(
                    model_config=model_config,
                    api_key=api_key,
                    prompt=prompt,
                    reference_images=refs,
                    size=payload.size,
                )
                url = _materialize_image_data(current_user, str(outcome.get("url") or ""))
                if idx == 1 and url:
                    anchor_url = url

                asset = AiGeneratedAsset(
                    user_id=current_user.id,
                    draft_id=draft_id,
                    prompt=prompt,
                    model_name=model_config.model_name,
                    params={
                        "kind": "card",
                        "batch": True,
                        "page_index": idx,
                        "page_type": page.page_type,
                        "style": base_style,
                        "layout": base_layout,
                        "preset": payload.preset,
                        "size": payload.size,
                        "illustration": page.illustration,
                        "reference_images": refs,
                    },
                    file_path=url,
                )
                db.add(asset)
                db.flush()
                generated.append({"index": idx, "url": url, "asset_id": asset.id})
            except Exception as exc:  # noqa: BLE001 - 单页失败不中断
                draft_failed = True
                generated.append({"index": idx, "error": str(exc)[:200]})

        ok_urls = [g["url"] for g in generated if g.get("url")]
        entry["pages"] = generated
        entry["generated"] = len(ok_urls)

        if ok_urls and payload.attach_to_draft:
            from backend.app.services.draft_asset_writer import attach_card_pages

            attach_card_pages(db, draft_id, ok_urls, replace=payload.replace_images)
            entry["attached"] = len(ok_urls)

        if not ok_urls:
            entry["status"] = "failed"
            entry["reason"] = "所有页都生成失败"
        elif draft_failed:
            entry["status"] = "partial"
            entry["reason"] = f"{len(ok_urls)} 页成功，有页失败"
        else:
            entry["status"] = "ok"

        db.commit()
        results.append(entry)

    return {
        "style": base_style,
        "layout": base_layout,
        "size": payload.size,
        "drafts": results,
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "partial": sum(1 for r in results if r["status"] == "partial"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }
