"""小红书图文卡片：拆页 → 逐页生图 → 系列风格一致。

为什么不复用 /api/ai/images/generate
-----------------------------------
那个接口是「一张图一条提示词」，前端要自己拼提示词。实测拼不好的结果就是
十次出十种东西。这里把「拆页 + 提示词装配 + 系列一致性」都搬到后端：

  POST /api/ai/cards/plan         正文 → 逐页大纲（可编辑后再提交）
  GET  /api/ai/cards/presets      风格/布局/预设清单
  POST /api/ai/cards/generate     按大纲出图（首张建立风格锚点）

系列一致性的做法（和上游项目一致）：第 2 页起把第 1 页作为参考图传给网关，
而不是指望模型从文字描述里"记住"风格。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.api.ai import (
    ImageAiClient,
    _image_model_context,
    _materialize_image_data,
    get_image_ai_client,
)
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiGeneratedAsset, AiDraft, Task, User
from backend.app.services.xhs_card_planner import plan_pages
from backend.app.services.xhs_card_style import (
    ALLOWED_SIZES,
    DEFAULT_SIZE,
    build_page_prompt,
    presets_payload,
    resolve_preset,
)

router = APIRouter(prefix="/ai/cards", tags=["ai-cards"])


class PlanRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    draft_id: int | None = None
    max_pages: int = Field(default=6, ge=1, le=12)
    include_cover: bool = True
    include_summary: bool = True
    # 用文本模型拆页（语义归组 + 给每页起标题 + 生成真正的收尾）。
    # 关掉就走确定性算法；模型失败时也会自动回落。
    use_llm: bool = False


class CardPagePayload(BaseModel):
    type: str = Field(default="content", pattern="^(cover|content|summary)$")
    title: str = Field(min_length=1, max_length=120)
    lines: list[str] = Field(default_factory=list)
    # 插图：none / icon / scene
    illustration: str = Field(default="none", pattern="^(none|icon|scene)$")
    # 插画内容提示（可选）：留空让模型按标题和正文判断
    illustration_hint: str = Field(default="", max_length=200)
    # 可选：单页改风格/布局，不填跟随整套
    style: str | None = None
    layout: str | None = None


class GenerateRequest(BaseModel):
    pages: list[CardPagePayload] = Field(min_length=1, max_length=12)
    draft_id: int | None = None
    preset: str | None = None
    style: str | None = None
    layout: str | None = None
    size: str = Field(default=DEFAULT_SIZE, max_length=32)
    # 是否把结果挂到草稿配图（顺序即页序）
    attach_to_draft: bool = False
    # 只生成第 N 页（用户重抽某一页用），0 表示全部
    only_index: int = Field(default=0, ge=0, le=12)


@router.get("/presets")
def get_presets(current_user: User = Depends(get_current_user)):
    return presets_payload()


@router.post("/plan")
def plan_cards(
    payload: PlanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把正文拆成逐页大纲，返回给前端让用户先改再生成。

    `use_llm=true` 时用文本模型做语义拆页（哪几句属于同一页、每页起小标题、
    写一句真正的收尾）；模型失败会自动回落到算法，业务不会因此中断。
    """
    title = payload.title
    body = payload.body
    if payload.draft_id is not None:
        draft = db.get(AiDraft, payload.draft_id)
        if draft is None or draft.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
        title = title or (draft.title or "")
        body = body or (draft.body or "")

    used_llm = False
    pages = None
    if payload.use_llm:
        from backend.app.api.ai import _text_model_context
        from backend.app.services.xhs_card_planner_llm import plan_with_model

        try:
            model_config, api_key = _text_model_context(db, current_user)
        except HTTPException:
            # 没配文本模型不该让「拆页」整个不可用，算法那条路照走
            model_config, api_key = None, ""

        if model_config is not None:
            pages = plan_with_model(
                model_config=model_config,
                api_key=api_key,
                title=title,
                body=body,
                max_pages=payload.max_pages,
            )
            used_llm = True

    if pages is None:
        pages = plan_pages(
            title=title,
            body=body,
            max_pages=payload.max_pages,
            include_cover=payload.include_cover,
            include_summary=payload.include_summary,
        )

    return {
        "pages": [p.to_dict() for p in pages],
        "total": len(pages),
        "used_llm": used_llm,
    }


@router.post("/generate")
def generate_cards(
    payload: GenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    image_ai_client: ImageAiClient = Depends(get_image_ai_client),
):
    """按大纲逐页出图。

    返回每一项都带 index / page_type / prompt / url / asset_id / error，
    单页失败不影响其它页 —— 用户可以对失败的那一页单独重抽。
    """
    if payload.size not in ALLOWED_SIZES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的尺寸 {payload.size}，可用：{', '.join(ALLOWED_SIZES)}",
        )

    if payload.draft_id is not None:
        draft = db.get(AiDraft, payload.draft_id)
        if draft is None or draft.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    base_style, base_layout = resolve_preset(payload.preset, payload.style, payload.layout)
    model_config, api_key = _image_model_context(db, current_user)

    task = Task(
        user_id=current_user.id,
        platform="xhs",
        task_type="ai_card_generate",
        status="running",
        progress=5,
        payload={
            "draft_id": payload.draft_id,
            "preset": payload.preset,
            "style": base_style,
            "layout": base_layout,
            "size": payload.size,
            "total": len(payload.pages),
        },
    )
    db.add(task)
    db.flush()

    anchor_url: str | None = None      # 第 1 页，用作后续页的参考图
    results: list[dict[str, Any]] = []
    total = len(payload.pages)

    try:
        for i, page in enumerate(payload.pages, start=1):
            if payload.only_index and i != payload.only_index:
                results.append({"index": i, "skipped": True})
                continue

            style_key, layout_key = resolve_preset(
                payload.preset, page.style or payload.style, page.layout or payload.layout
            )
            prompt = build_page_prompt(
                title=page.title,
                lines=page.lines,
                page_type=page.type,
                style_key=style_key,
                layout_key=layout_key,
                index=i,
                total=total,
                size=payload.size,
                illustration=page.illustration,
                illustration_hint=page.illustration_hint,
            )

            refs: list[str] | None = None
            if anchor_url and i > 1:
                refs = [anchor_url]

            item: dict[str, Any] = {
                "index": i,
                "page_type": page.type,
                "title": page.title,
                "prompt": prompt,
                "style": style_key,
                "layout": layout_key,
                "illustration": page.illustration,
            }
            try:
                outcome = image_ai_client.generate_image(
                    model_config=model_config,
                    api_key=api_key,
                    prompt=prompt,
                    reference_images=refs,
                    size=payload.size,
                )
                url = _materialize_image_data(current_user, str(outcome.get("url") or ""))
                item["url"] = url
                if i == 1 and url:
                    anchor_url = url

                asset = AiGeneratedAsset(
                    user_id=current_user.id,
                    draft_id=payload.draft_id,
                    prompt=prompt,
                    model_name=model_config.model_name,
                    params={
                        "kind": "card",
                        "page_index": i,
                        "page_type": page.type,
                        "style": style_key,
                        "layout": layout_key,
                        "preset": payload.preset,
                        "size": payload.size,
                        "illustration": page.illustration,
                        "reference_images": refs,
                    },
                    file_path=url,
                )
                db.add(asset)
                db.flush()
                item["asset_id"] = asset.id
            except Exception as exc:  # noqa: BLE001 - 单页失败不该拖垮整套
                item["error"] = str(exc)[:300]

            results.append(item)
            task.progress = min(95, 5 + int(i / total * 90))
            db.commit()

        ok = [r for r in results if r.get("url")]
        failed = [r for r in results if r.get("error")]
        task.status = "completed" if ok else "failed"
        task.progress = 100
        task.payload = {
            **(task.payload or {}),
            "generated": len(ok),
            "failed": len(failed),
        }

        if payload.attach_to_draft and payload.draft_id is not None and ok:
            _attach_pages(db, payload.draft_id, [r["url"] for r in ok])

        db.commit()
    except Exception as exc:  # noqa: BLE001
        task.status = "failed"
        task.progress = 100
        task.payload = {**(task.payload or {}), "error": str(exc)[:300]}
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"卡片生成失败：{exc}",
        ) from exc

    return {
        "task_id": task.id,
        "style": base_style,
        "layout": base_layout,
        "size": payload.size,
        "pages": results,
        "generated": len([r for r in results if r.get("url")]),
        "failed": len([r for r in results if r.get("error")]),
    }


def _attach_pages(db: Session, draft_id: int, urls: list[str]) -> None:
    """把生成的图按顺序挂到草稿配图上（追加，不覆盖已有）。"""
    from backend.app.services.draft_asset_writer import attach_card_pages

    attach_card_pages(db, draft_id, urls)
