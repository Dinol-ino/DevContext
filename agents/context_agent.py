from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

try:
    from .tools import format_sources, search_nodes
except ImportError:
    from tools import format_sources, search_nodes

router = APIRouter(tags=["Context"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Why rate limiting at gateway?"])


class Source(BaseModel):
    id: Any = None
    title: Optional[str] = None
    type: Optional[str] = None
    reason: Any = None
    services: Any = None
    url: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    confidence: float = Field(..., ge=0, le=1)
    sources: list[Source] = Field(default_factory=list)


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    rows = search_nodes(payload.question)
    sources = format_sources(rows)

    if sources:
        answer = "Found related engineering decisions."
        confidence = min(0.95, 0.64 + (len(sources) * 0.05))
    else:
        answer = "No related engineering decisions found."
        confidence = 0.0

    return AskResponse(answer=answer, confidence=round(confidence, 2), sources=sources)
