from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

try:
    from .auth_utils import get_current_user
    from .db import (
        fetch_decisions,
        fetch_recent_nodes,
        fetch_services,
    )
    from .tools import call_llm, parse_json_response
except ImportError:
    from auth_utils import get_current_user
    from db import (
        fetch_decisions,
        fetch_recent_nodes,
        fetch_services,
    )
    from tools import call_llm, parse_json_response

router = APIRouter(tags=["Onboarding Assistant"])


class OnboardingGuideRequest(BaseModel):
    repo_id: str = Field(..., min_length=1, examples=["octocat/Spoon-Knife"])
    role: Optional[str] = Field(default="fullstack", examples=["backend", "frontend", "fullstack", "devops"])


class OnboardingSection(BaseModel):
    title: str
    content: str
    items: List[str] = Field(default_factory=list)


class OnboardingGuideResponse(BaseModel):
    repo_id: str
    role: str
    overview: str
    tech_stack: List[str]
    entry_points: List[str]
    key_decisions: List[str]
    sections: List[OnboardingSection]


@router.post("/onboarding/guide", response_model=OnboardingGuideResponse)
def generate_onboarding_guide(
    payload: OnboardingGuideRequest,
    current_user: dict = Depends(get_current_user),
) -> OnboardingGuideResponse:
    repo_id = payload.repo_id.strip()
    role = (payload.role or "fullstack").strip().lower()

    # Find repo node in database
    recent = fetch_recent_nodes(limit=200, repo_id=repo_id)
    repo_node = None
    for row in recent:
        if str(row.get("type")).lower() == "repo":
            repo_node = row
            break

    metadata = (repo_node.get("metadata") if repo_node and isinstance(repo_node.get("metadata"), dict) else {})
    tech_stack = [str(t) for t in metadata.get("technology_stack", []) if str(t)]
    entry_points = [str(e) for e in metadata.get("entry_points", []) if str(e)]
    config_files = [str(c) for c in metadata.get("config_files", []) if str(c)]
    frameworks = [str(f) for f in metadata.get("frameworks", []) if str(f)]

    # Fetch decisions & services for this repo
    decisions = fetch_decisions(limit=100, repo_id=repo_id)
    decision_titles = [str(d.get("label")) for d in decisions if str(d.get("label"))]
    services = fetch_services(limit=100, repo_id=repo_id)
    service_names = [str(s.get("name")) for s in services if str(s.get("name"))]

    system_prompt = (
        "You are an expert Engineering Lead & Developer Onboarding Assistant. "
        "Generate a tailored onboarding guide for a developer joining a codebase. "
        "Return ONLY JSON with format: "
        '{"overview": string, "architecture_summary": string, "getting_started_steps": list[string], "key_files": list[string]}'
    )
    user_prompt = (
        f"Repository: {repo_id}\nTarget Role: {role}\n"
        f"Tech Stack: {', '.join(tech_stack) if tech_stack else 'General'}\n"
        f"Frameworks: {', '.join(frameworks) if frameworks else 'Standard'}\n"
        f"Entry Points: {', '.join(entry_points) if entry_points else 'Root'}\n"
        f"Config Files: {', '.join(config_files) if config_files else 'None'}\n"
        f"Architecture Decisions: {', '.join(decision_titles[:5]) if decision_titles else 'None'}\n"
        f"Services: {', '.join(service_names[:5]) if service_names else 'None'}"
    )

    llm_output = call_llm(system_prompt, user_prompt)
    parsed = parse_json_response(llm_output)

    overview = str(
        parsed.get("overview")
        or f"Welcome to {repo_id}! This repository is built using {', '.join(tech_stack) if tech_stack else 'modern software engineering standards'}."
    )
    arch_summary = str(
        parsed.get("architecture_summary")
        or f"The project utilizes {', '.join(frameworks) if frameworks else 'a modular architecture'} with entry points at {', '.join(entry_points[:3]) if entry_points else 'the repository root'}."
    )
    steps = [str(step) for step in parsed.get("getting_started_steps", []) if str(step).strip()]
    if not steps:
        steps = [
            f"Clone the repository and select the target branch for {repo_id}.",
            f"Review project configuration files: {', '.join(config_files[:4]) if config_files else 'root configs'}.",
            f"Inspect entry points: {', '.join(entry_points[:3]) if entry_points else 'main entry file'}.",
            "Run local test suite and verify dependency installation.",
        ]

    key_files = [str(f) for f in parsed.get("key_files", []) if str(f).strip()]
    if not key_files:
        key_files = entry_points + config_files

    sections = [
        OnboardingSection(
            title="Architecture & System Design",
            content=arch_summary,
            items=service_names[:8],
        ),
        OnboardingSection(
            title="Getting Started Checklist",
            content=f"Recommended onboarding steps for a new {role} engineer:",
            items=steps,
        ),
        OnboardingSection(
            title="Key Code Files & Configs",
            content="Critical files to inspect first during your codebase walkthrough:",
            items=key_files[:10],
        ),
    ]

    return OnboardingGuideResponse(
        repo_id=repo_id,
        role=role,
        overview=overview,
        tech_stack=tech_stack,
        entry_points=entry_points,
        key_decisions=decision_titles[:10],
        sections=sections,
    )


@router.get("/onboarding/overview/{repo_id:path}")
def onboarding_overview(
    repo_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    clean_repo = repo_id.strip()
    recent = fetch_recent_nodes(limit=200, repo_id=clean_repo)

    tech_stack = []
    entry_points = []
    for row in recent:
        if str(row.get("type")).lower() == "repo":
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            tech_stack = meta.get("technology_stack", [])
            entry_points = meta.get("entry_points", [])
            break

    decisions = fetch_decisions(limit=10, repo_id=clean_repo)
    services = fetch_services(limit=10, repo_id=clean_repo)

    return {
        "repo_id": clean_repo,
        "technology_stack": tech_stack,
        "entry_points": entry_points,
        "recent_decisions_count": len(decisions),
        "services_count": len(services),
        "decisions_summary": [d.get("label") for d in decisions[:5] if d.get("label")],
    }
