from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

from .db_insert import (
    get_graph_stats,
    insert_adr_edges,
    insert_adr_node,
    insert_edges,
    insert_embedding,
    insert_lightweight_event,
    insert_node,
    node_exists,
)
from .embed import generate_embedding
from .extractor import extract_decision, parse_github_event
from .utils import clean_text, log_error, log_info, log_step, log_warning

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)

GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()

TIER1_EVENTS = {"push", "pull_request"}
TIER2_EVENTS = {"pull_request_review", "pull_request_review_comment", "commit_comment", "repository"}
TIER3_EVENTS = {"collaborator", "code_scanning_alert"}
LOW_QUALITY_DECISION_LABELS = {
    "unable to extract decision",
    "untitled decision",
    "parse fallback",
    "inferred engineering change",
}

app = FastAPI(title="DevContextIQ Ingestion API", version="1.0.0")


def _validate_signature(raw_body: bytes, signature_header: str | None) -> None:
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    secret = GITHUB_WEBHOOK_SECRET.encode()
    digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


def _ignored_event(event_name: str) -> dict[str, str]:
    return {"status": "ignored", "event": event_name or "unknown"}


def _safe_source_url(event_name: str, source_url: str, delivery_id: str) -> str:
    clean_url = clean_text(source_url)
    if clean_url:
        return clean_url
    return f"event://{event_name or 'unknown'}/{delivery_id or 'unknown'}"


def _normalize_decision_label(label: str, fallback: str) -> str:
    clean_label = clean_text(label)
    if clean_label:
        return clean_label[:200]
    return clean_text(fallback)[:200] or "Engineering change recorded"


def _is_low_quality_label(value: str) -> bool:
    lowered = clean_text(value).lower()
    return not lowered or lowered in LOW_QUALITY_DECISION_LABELS


def _adr_source_url(base_source_url: str, path: str) -> str:
    source = clean_text(base_source_url)
    clean_path = clean_text(path)
    if not source:
        return f"event://adr/{clean_path or 'unknown'}"
    if clean_path:
        return f"{source}#adr:{clean_path}"
    return source


def _normalize_adr_items(raw_items: Any, default_repo: str, default_author: str) -> list[dict[str, str]]:
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        path = clean_text(item.get("path"))
        title = clean_text(item.get("title"))
        summary = clean_text(item.get("summary"))
        repo = clean_text(item.get("repo")) or default_repo
        author = clean_text(item.get("author")) or default_author
        source_url = clean_text(item.get("source_url"))

        if not path or not title:
            continue
        normalized.append(
            {
                "path": path,
                "title": title[:200],
                "summary": summary[:500],
                "repo": repo,
                "author": author,
                "source_url": source_url,
            }
        )
    return normalized


def _insert_adr_nodes(
    event_name: str,
    delivery_id: str,
    event_data: dict[str, Any],
    default_source_url: str,
) -> list[str]:
    repo = clean_text(event_data.get("repo"))
    author = clean_text(event_data.get("author"))
    adr_items = _normalize_adr_items(event_data.get("adr_items"), repo, author)
    if not adr_items:
        return []

    inserted: list[str] = []
    for adr in adr_items:
        adr_source = _adr_source_url(adr.get("source_url") or default_source_url, adr["path"])
        adr_title = clean_text(adr["title"])
        if node_exists(adr_source, adr_title, "adr"):
            continue

        try:
            adr_node_id = insert_adr_node(
                title=adr_title,
                summary=adr.get("summary", ""),
                path=adr["path"],
                repo=adr.get("repo", ""),
                author=adr.get("author", ""),
                source_url=adr_source,
                metadata_extra={
                    "event_type": event_name,
                    "delivery_id": delivery_id,
                },
            )
            insert_adr_edges(
                adr_node_id=adr_node_id,
                repo=adr.get("repo", ""),
                author=adr.get("author", ""),
            )
            chunk = clean_text(f"{adr_title}\n{adr.get('summary', '')}\nPath: {adr.get('path', '')}")
            if chunk:
                embedding = generate_embedding(chunk)
                if embedding:
                    insert_embedding(node_id=adr_node_id, chunk=chunk, embedding=embedding)
            inserted.append(adr_node_id)
            log_step(f"adr inserted node_id={adr_node_id} path={adr['path']}")
        except Exception as exc:
            log_warning(f"adr insert skipped path={adr['path']}: {exc}")

    return inserted


@app.on_event("startup")
def startup_diagnostics() -> None:
    log_info(f"loading env from {ENV_PATH}")
    log_info(f"env file exists={ENV_PATH.exists()}")
    log_info(f"webhook secret loaded={bool(GITHUB_WEBHOOK_SECRET)}")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
def stats() -> dict[str, Any]:
    try:
        return get_graph_stats()
    except Exception as exc:
        log_error(f"stats endpoint failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to load stats: {exc}") from exc


@app.post("/github-webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> dict[str, Any]:
    event_name = clean_text(x_github_event).lower()
    delivery_id = clean_text(x_github_delivery)
    log_info(f"received event={event_name or 'unknown'} delivery={delivery_id or 'unknown'}")

    if not GITHUB_WEBHOOK_SECRET:
        log_error("webhook secret missing from environment")
        raise HTTPException(status_code=500, detail="Server webhook secret not configured")

    raw_body = await request.body()
    _validate_signature(raw_body, x_hub_signature_256)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        log_warning(f"payload parse failed for event={event_name or 'unknown'}: {exc}")
        return _ignored_event(event_name)

    if not isinstance(payload, dict):
        log_warning(f"invalid payload type for event={event_name or 'unknown'}")
        return _ignored_event(event_name)

    if event_name in TIER3_EVENTS:
        log_info(f"ignored event={event_name}")
        return _ignored_event(event_name)

    if event_name not in TIER1_EVENTS and event_name not in TIER2_EVENTS:
        log_info(f"ignored event={event_name or 'unknown'}")
        return _ignored_event(event_name)

    try:
        event_data = parse_github_event(event_name, payload)
    except Exception as exc:
        log_warning(f"event parse failure event={event_name}: {exc}")
        return _ignored_event(event_name)

    source_url = _safe_source_url(event_name, event_data.get("source_url", ""), delivery_id)
    label = clean_text(event_data.get("label"))
    metadata = event_data.get("metadata", {})
    adr_node_ids: list[str] = []

    if event_name in TIER2_EVENTS:
        try:
            if node_exists(source_url, label, event_name):
                log_info("skipped duplicate event")
                return {"duplicate": True}

            node_id = insert_lightweight_event(
                event_type=event_name,
                label=label,
                source_url=source_url,
                metadata=metadata if isinstance(metadata, dict) else {"event": event_name},
            )
            log_info(f"metadata captured event={event_name}")
            return {
                "received": True,
                "processed": True,
                "mode": "light",
                "event": event_name,
                "node_id": node_id,
            }
        except Exception as exc:
            log_warning(f"light processing failed event={event_name}: {exc}")
            return _ignored_event(event_name)

    if event_name == "push":
        try:
            adr_node_ids = _insert_adr_nodes(
                event_name=event_name,
                delivery_id=delivery_id,
                event_data=event_data,
                default_source_url=source_url,
            )
            if adr_node_ids:
                log_info(f"adr nodes processed count={len(adr_node_ids)}")
        except Exception as exc:
            log_warning(f"adr processing failed event={event_name}: {exc}")

    try:
        summary_text = clean_text(event_data.get("summary_text"))
        if not summary_text:
            summary_text = label or "Engineering change"

        decision_hint = clean_text(event_data.get("decision_hint"))
        reason_hint = clean_text(event_data.get("reason_hint"))
        decision_data = extract_decision(summary_text)
        extracted_label = clean_text(decision_data.get("decision"))
        decision_label = extracted_label
        if _is_low_quality_label(decision_label):
            decision_label = decision_hint or label
        decision_label = _normalize_decision_label(decision_label, fallback="Engineering change recorded")
        decision_data["decision"] = decision_label
        if not clean_text(decision_data.get("reason")):
            decision_data["reason"] = reason_hint or summary_text[:260]

        if node_exists(source_url, decision_label, event_name):
            log_info("skipped duplicate event")
            response: dict[str, Any] = {"duplicate": True}
            if adr_node_ids:
                response["adr_node_ids"] = adr_node_ids
            return response

        node_id = insert_node(
            data=decision_data,
            source_url=source_url,
            event_type=event_name,
            metadata_extra=metadata if isinstance(metadata, dict) else None,
        )

        try:
            insert_edges(
                node_id=node_id,
                repo=clean_text(event_data.get("repo")),
                author=clean_text(event_data.get("author")),
                services=decision_data.get("services", []),
            )
            log_step(f"edges inserted node_id={node_id}")
        except Exception as exc:
            log_warning(f"edge insert skipped node_id={node_id}: {exc}")

        try:
            embedding = generate_embedding(summary_text)
            if embedding:
                insert_embedding(node_id=node_id, chunk=summary_text, embedding=embedding)
                log_step(f"embedding inserted node_id={node_id}")
            else:
                log_warning(f"embedding skipped node_id={node_id}")
        except Exception as exc:
            log_warning(f"embedding flow failed node_id={node_id}: {exc}")

        log_info(f"processed {event_name} node inserted")
        response = {
            "received": True,
            "processed": True,
            "event": event_name,
            "node_id": node_id,
            "decision": decision_data,
        }
        if adr_node_ids:
            response["adr_node_ids"] = adr_node_ids
        return response
    except Exception as exc:
        log_warning(f"tier1 processing failed event={event_name}: {exc}")
        if adr_node_ids:
            return {
                "received": True,
                "processed": True,
                "mode": "adr_only",
                "event": event_name,
                "adr_node_ids": adr_node_ids,
            }
        return _ignored_event(event_name)
