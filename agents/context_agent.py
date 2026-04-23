import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from .prompts import CONTEXT_SYSTEM_PROMPT
    from .tools import call_llm, format_sources, retrieve_context
except ImportError:
    from prompts import CONTEXT_SYSTEM_PROMPT
    from tools import call_llm, format_sources, retrieve_context

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)

USED_MODEL = os.getenv("MODEL_NAME", "").strip() or os.getenv("OPENROUTER_MODEL", "").strip() or "deepseek/deepseek-chat"
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

    parts: list[str] = []
    for row in evidence[:3]:
        label = str(row.get("label") or "Unnamed decision")
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        reason = str(metadata.get("reason") or "").strip()
        services = metadata.get("services") if isinstance(metadata.get("services"), list) else []

        sentence = label
        if reason:
            sentence += f": {reason}"
        if services:
            sentence += f" Services: {', '.join(str(item) for item in services)}."
        else:
            sentence += "."
        parts.append(sentence)

    return " ".join(parts)


def _evidence_prompt(evidence: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in evidence[:5]:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        reason = str(metadata.get("reason") or "").strip()
        services = metadata.get("services") if isinstance(metadata.get("services"), list) else []
        lines.append(
            f"Title: {row.get('label') or 'Unknown'} | "
            f"Reason: {reason or 'n/a'} | "
            f"Services: {', '.join(str(item) for item in services) if services else 'n/a'}"
        )
    return "\n".join(lines)


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest) -> AskResponse:
    try:
        context = retrieve_context(payload.question)
        evidence = context.get("evidence", [])
        sources = context.get("sources") or format_sources(evidence)
        confidence = float(context.get("confidence", 0.0))

        if not evidence:
            return AskResponse(
                answer="Insufficient internal context to answer this question.",
                confidence=0.0,
                sources=[],
                used_model=USED_MODEL,
            )

        llm_answer = call_llm(
            CONTEXT_SYSTEM_PROMPT,
            f"Question: {payload.question}\n\nEvidence:\n{_evidence_prompt(evidence)}",
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
