"""Design Mode API: the style catalog and dimension-based style composition.

Both endpoints require an authenticated principal. Neither reads or writes
tenant data: the catalog is repository content and composition is a pure
function of the request, so no project authorization is involved. Composition
returns prompt text only; nothing here invokes a media provider. A composed
direction reaches a run through the agency brief (``CampaignBrief.style_selection``),
where it is recomposed server-side and persisted on the run's DesignBrief.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from services.langgraph.agency.design import (
    InvalidSelectionError,
    StyleSelection,
    UnknownStyleError,
    compose_style_selection,
    style_catalog_snapshot,
)
from services.langgraph.security.auth import Principal, get_principal

router = APIRouter()


class ComposeBrief(BaseModel):
    objective: str | None = Field(default=None, max_length=500)
    audience: str | None = Field(default=None, max_length=300)
    format: str | None = Field(default=None, max_length=200)

    model_config = {"extra": "forbid"}


class ComposeRequest(BaseModel):
    selections: list[StyleSelection] = Field(min_length=1, max_length=8)
    brief: ComposeBrief = Field(default_factory=ComposeBrief)

    model_config = {"extra": "forbid"}


@router.get("/styles")
def list_styles(principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return style_catalog_snapshot()


@router.post("/styles/compose")
def compose_styles(req: ComposeRequest, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    try:
        composed = compose_style_selection(req.selections, req.brief.model_dump(exclude_none=True))
    except UnknownStyleError as exc:
        raise HTTPException(status_code=422, detail=f"unknown style {exc.args[0]!r}") from exc
    except (InvalidSelectionError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return composed.model_dump(mode="json")
