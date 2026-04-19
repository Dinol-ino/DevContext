from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

try:
    from .tools import format_sources, search_nodes
except ImportError:
    from tools import format_sources, search_nodes

router = APIRouter(tags=["Context"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Why is rate limiting at gateway?"])


class AskResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    rows = search_nodes(payload.question)
    sources = format_sources(rows)

    if sources:
        top_titles = ", ".join(source["title"] for source in sources[:2])
        answer = f"Found {len(sources)} matching decision(s). Top matches: {top_titles}."
    else:
        answer = "No matching decisions found in nodes table for the given question."

    return AskResponse(answer=answer, sources=sources)
