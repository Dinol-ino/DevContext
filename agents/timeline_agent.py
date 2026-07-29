from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

try:
    from .auth_utils import get_current_user
    from .db import fetch_recent_nodes
except ImportError:
    from auth_utils import get_current_user
    from db import fetch_recent_nodes

router = APIRouter(tags=["Context Timeline"])


class TimelineEvent(BaseModel):
    id: str
    type: str
    title: str
    description: Optional[str] = None
    timestamp: str
    author: Optional[str] = None
    source_url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    impact_level: Optional[str] = None


class TimelineResponse(BaseModel):
    scope: str
    scope_type: str
    total_events: int
    events: List[TimelineEvent]


def _parse_timestamp(row: dict[str, Any]) -> str:
    val = row.get("created_at") or (row.get("metadata") or {}).get("timestamp") or ""
    return str(val) if val else datetime.utcnow().isoformat()


@router.get("/timeline/{repo_id:path}", response_model=TimelineResponse)
def get_repo_timeline(
    repo_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
) -> TimelineResponse:
    clean_repo = repo_id.strip()
    nodes = fetch_recent_nodes(limit=max(1, min(limit * 3, 300)), repo_id=clean_repo)

    events: List[TimelineEvent] = []
    seen: set[str] = set()

    for row in nodes:
        node_id = str(row.get("id") or "")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)

        node_type = str(row.get("type", "event")).lower()
        if node_type == "repo":
            continue

        label = str(row.get("label", "Engineering event"))
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}

        description = (
            str(meta.get("reason") or meta.get("summary") or meta.get("description") or "")
        ).strip()
        author = str(meta.get("author") or meta.get("pusher") or "") or None
        impact = str(meta.get("impact_level") or meta.get("risk") or "medium").lower()

        tags = []
        if meta.get("services"):
            tags.extend([str(s) for s in meta["services"] if str(s)])
        if meta.get("event"):
            tags.append(str(meta["event"]))

        events.append(
            TimelineEvent(
                id=node_id,
                type=node_type,
                title=label,
                description=description or None,
                timestamp=_parse_timestamp(row),
                author=author,
                source_url=str(row.get("source_url")) if row.get("source_url") else None,
                tags=list(set(tags)),
                impact_level=impact,
            )
        )

    # Sort events by timestamp descending
    events.sort(key=lambda e: e.timestamp, reverse=True)
    capped_events = events[: max(1, min(limit, 100))]

    return TimelineResponse(
        scope=clean_repo,
        scope_type="repository",
        total_events=len(capped_events),
        events=capped_events,
    )


@router.get("/timeline/service/{service_name}", response_model=TimelineResponse)
def get_service_timeline(
    service_name: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
) -> TimelineResponse:
    clean_svc = service_name.strip().lower()
    nodes = fetch_recent_nodes(limit=300)

    events: List[TimelineEvent] = []
    seen: set[str] = set()

    for row in nodes:
        node_id = str(row.get("id") or "")
        if not node_id or node_id in seen:
            continue

        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        services = [str(s).lower() for s in meta.get("services", [])] if isinstance(meta.get("services"), list) else []

        if clean_svc in services or clean_svc in str(row.get("label", "")).lower():
            seen.add(node_id)
            node_type = str(row.get("type", "event")).lower()
            label = str(row.get("label", "Service event"))
            description = str(meta.get("reason") or meta.get("summary") or "").strip()
            author = str(meta.get("author") or "") or None

            events.append(
                TimelineEvent(
                    id=node_id,
                    type=node_type,
                    title=label,
                    description=description or None,
                    timestamp=_parse_timestamp(row),
                    author=author,
                    source_url=str(row.get("source_url")) if row.get("source_url") else None,
                    tags=[clean_svc],
                    impact_level=str(meta.get("risk") or "medium"),
                )
            )

    events.sort(key=lambda e: e.timestamp, reverse=True)
    capped = events[: max(1, min(limit, 100))]

    return TimelineResponse(
        scope=clean_svc,
        scope_type="service",
        total_events=len(capped),
        events=capped,
    )
