from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

try:
    from .auth_utils import get_current_user
    from .db import (
        _get_or_create_node,
        _insert_edge_if_missing,
        _insert_node_row,
        fetch_recent_nodes,
    )
    from .tools import call_llm, parse_json_response
except (ImportError, ValueError):
    try:
        from agents.auth_utils import get_current_user
        from agents.db import (
            _get_or_create_node,
            _insert_edge_if_missing,
            _insert_node_row,
            fetch_recent_nodes,
        )
        from agents.tools import call_llm, parse_json_response
    except ImportError:
        from auth_utils import get_current_user
        from db import (
            _get_or_create_node,
            _insert_edge_if_missing,
            _insert_node_row,
            fetch_recent_nodes,
        )
        from tools import call_llm, parse_json_response

router = APIRouter(tags=["Commit Intelligence"])


class CommitAnalyzeRequest(BaseModel):
    commit_hash: str = Field(..., min_length=4, examples=["a1b2c3d4"])
    commit_message: str = Field(..., min_length=1, examples=["Refactor gateway rate limiting policy"])
    diff_text: Optional[str] = Field(default=None)
    author: Optional[str] = Field(default=None, examples=["alex-dev"])
    repo_id: Optional[str] = Field(default=None, examples=["acme/payments"])


class CommitAnalyzeResponse(BaseModel):
    commit_hash: str
    summary: str
    impact_level: str
    affected_services: List[str]
    risk_factors: List[str]
    suggested_reviewers: List[str]
    node_id: Optional[str] = None


@router.post("/commit/analyze", response_model=CommitAnalyzeResponse)
def analyze_commit(
    payload: CommitAnalyzeRequest,
    current_user: dict = Depends(get_current_user),
) -> CommitAnalyzeResponse:
    commit_hash = payload.commit_hash.strip()
    commit_msg = payload.commit_message.strip()
    diff = (payload.diff_text or "").strip()
    author = (payload.author or "").strip()
    repo = (payload.repo_id or "").strip()

    system_prompt = (
        "You are an expert Code Review & Architectural Commit Analyzer. Analyze the commit message and code diff. "
        "Return ONLY JSON with keys: "
        '{"summary": string, "impact_level": "high"|"medium"|"low", "affected_services": list[string], '
        '"risk_factors": list[string], "suggested_reviewers": list[string]}'
    )
    user_prompt = (
        f"Commit Hash: {commit_hash}\nAuthor: {author}\nRepo: {repo}\n"
        f"Message: {commit_msg}\nDiff:\n{diff[:3000] if diff else 'No diff provided.'}"
    )

    llm_output = call_llm(system_prompt, user_prompt)
    parsed = parse_json_response(llm_output)

    summary = str(parsed.get("summary") or f"Commit {commit_hash[:7]}: {commit_msg}")
    impact = str(parsed.get("impact_level") or "medium").lower()
    if impact not in {"high", "medium", "low"}:
        impact = "medium"
    services = [str(s) for s in parsed.get("affected_services", []) if str(s).strip()]
    risks = [str(r) for r in parsed.get("risk_factors", []) if str(r).strip()]
    reviewers = [str(rev) for rev in parsed.get("suggested_reviewers", []) if str(rev).strip()]

    # Insert commit node into database graph
    node_id = None
    try:
        metadata = {
            "commit_hash": commit_hash,
            "author": author,
            "repo": repo,
            "message": commit_msg,
            "impact_level": impact,
            "services": services,
            "risk_factors": risks,
            "summary": summary,
            "event": "commit",
        }
        label = f"Commit {commit_hash[:7]}: {commit_msg[:120]}"
        node_id = _insert_node_row("commit", label, metadata, f"commit://{repo}/{commit_hash}")

        if repo:
            repo_node = _get_or_create_node("repo", repo)
            _insert_edge_if_missing(node_id, repo_node, "belongs_to_repo")

        if author:
            author_node = _get_or_create_node("author", author)
            _insert_edge_if_missing(author_node, node_id, "authored_commit")

        for service in services:
            service_node = _get_or_create_node("service", service)
            _insert_edge_if_missing(node_id, service_node, "affects_service")
    except Exception:
        pass

    return CommitAnalyzeResponse(
        commit_hash=commit_hash,
        summary=summary,
        impact_level=impact,
        affected_services=services,
        risk_factors=risks,
        suggested_reviewers=reviewers,
        node_id=node_id,
    )


@router.get("/commit/history/{repo_id:path}")
def commit_history(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
) -> List[dict]:
    clean_repo = repo_id.strip().lower()
    recent = fetch_recent_nodes(limit=150)
    commits = []

    for row in recent:
        if str(row.get("type")).lower() == "commit":
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            row_repo = str(meta.get("repo") or "").lower()
            if not clean_repo or clean_repo in row_repo or row_repo in clean_repo:
                commits.append({
                    "id": row.get("id"),
                    "label": row.get("label"),
                    "commit_hash": meta.get("commit_hash"),
                    "author": meta.get("author"),
                    "repo": meta.get("repo"),
                    "impact_level": meta.get("impact_level", "medium"),
                    "summary": meta.get("summary"),
                    "created_at": row.get("created_at"),
                })

    return commits[:30]
