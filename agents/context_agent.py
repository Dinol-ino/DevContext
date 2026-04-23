from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from .prompts import CONTEXT_SYSTEM_PROMPT
    from .tools import call_llm, format_sources, retrieve_context
except ImportError:
    from prompts import CONTEXT_SYSTEM_PROMPT
    from tools import call_llm, format_sources, retrieve_context

USED_MODEL = "deepseek/deepseek-chat"
router = APIRouter(tags=["Context"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Why was gateway rate limiting introduced?"])


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
    used_model: str


def _deterministic_answer(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "Insufficient internal context to answer this question."

    top_rows = evidence[:3]
    parts: list[str] = []
    for row in top_rows:
        label = str(row.get("label") or "Unnamed decision")
        metadata = row.get("metadata") or {}
        reason = metadata.get("reason") if isinstance(metadata, dict) else None
        services = metadata.get("services") if isinstance(metadata, dict) else None

        sentence = label
        if reason:
            sentence += f": {str(reason).strip()}"
        if isinstance(services, list) and services:
            sentence += f" Services: {', '.join(str(item) for item in services)}."
        else:
            sentence += "."
        parts.append(sentence)
    return " ".join(parts)


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    try:
        context = retrieve_context(payload.question)
        evidence = context.get("evidence", [])
        sources = format_sources(evidence)
        confidence = float(context.get("confidence", 0.0))

        if not evidence:
            return AskResponse(
                answer="Insufficient internal context to answer this question.",
                confidence=0.0,
                sources=[],
                used_model=USED_MODEL,
            )

        evidence_text = "\n".join(
            f"- {row.get('label')}: {((row.get('metadata') or {}).get('reason') if isinstance(row.get('metadata'), dict) else '')}"
            for row in evidence[:5]
        )
        llm_answer = call_llm(
            CONTEXT_SYSTEM_PROMPT,
            f"Question: {payload.question}\n\nEvidence:\n{evidence_text}",
        )
        answer = llm_answer or _deterministic_answer(evidence)

        return AskResponse(
            answer=answer,
            confidence=confidence,
            sources=sources,
            used_model=USED_MODEL,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to answer question: {exc}") from exc
