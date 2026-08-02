from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator

try:
    from .prompts import CONTEXT_SYSTEM_PROMPT
    from .tools import (
        _evidence_prompt,
        _trim_context_chunk,
        call_llm,
        format_sources,
        get_used_model,
        retrieve_context,
    )
    from .auth_utils import get_current_user
    from .db import add_chat_message
except ImportError:
    from prompts import CONTEXT_SYSTEM_PROMPT
    from tools import (
        _evidence_prompt,
        _trim_context_chunk,
        call_llm,
        format_sources,
        get_used_model,
        retrieve_context,
    )
    from auth_utils import get_current_user
    from db import add_chat_message

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_FILE, override=False)

router = APIRouter(tags=["Context"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, examples=["Why was gateway rate limiting introduced?"])
    repo_id: Optional[str] = Field(default=None, description="Optional repo identifier to scope context retrieval")
    thread_id: Optional[str] = Field(default=None, description="Optional chat thread identifier for persistent context memory")

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        val = v.strip()
        if not val:
            raise ValueError("question cannot be empty or only whitespace")
        return val



class Source(BaseModel):
    id: Any = None
    title: Optional[str] = None
    type: Optional[str] = None
    reason: Any = None
    services: Any = None
    url: Optional[str] = None
    node_id: Any = None
    chunk_id: Any = None
    repo_id: Optional[str] = None
    file_path: Optional[str] = None
    language: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    score: Any = None
    similarity: Any = None


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


# _trim_context_chunk and _evidence_prompt are imported from tools.py
# to avoid maintaining duplicate implementations.


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, current_user: dict = Depends(get_current_user)) -> AskResponse:

    try:
        used_model = get_used_model()
        context = retrieve_context(payload.question, repo_id=payload.repo_id)
        evidence = context.get("evidence", [])
        sources = context.get("sources") or format_sources(evidence)
        confidence = float(context.get("confidence", 0.0))

        if not evidence:
            answer = "Insufficient internal context to answer this question."
            if payload.thread_id:
                try:
                    add_chat_message(payload.thread_id, "user", payload.question)
                    add_chat_message(payload.thread_id, "assistant", answer, confidence=0.0, sources=[], used_model=used_model)
                except Exception:
                    pass

            return AskResponse(
                answer=answer,
                confidence=0.0,
                sources=[],
                used_model=used_model,
            )

        llm_answer = call_llm(
            CONTEXT_SYSTEM_PROMPT,
            f"Question: {payload.question}\n\nEvidence:\n{_evidence_prompt(evidence)}",
        )
        answer = llm_answer or _deterministic_answer(evidence)

        if payload.thread_id:
            try:
                add_chat_message(payload.thread_id, "user", payload.question)
                add_chat_message(
                    payload.thread_id,
                    "assistant",
                    answer,
                    confidence=confidence,
                    sources=sources,
                    used_model=used_model,
                )
            except Exception:
                pass

        return AskResponse(
            answer=answer,
            confidence=confidence,
            sources=sources,
            used_model=used_model,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to answer question: {exc}") from exc
