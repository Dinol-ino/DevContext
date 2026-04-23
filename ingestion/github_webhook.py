<<<<<<< HEAD
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
load_dotenv(dotenv_path=ENV_PATH)

GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()

TIER1_EVENTS = {"push", "pull_request"}
TIER2_EVENTS = {"pull_request_review", "pull_request_review_comment", "commit_comment", "repository"}
TIER3_EVENTS = {"collaborator", "code_scanning_alert"}

app = FastAPI(title="DevContextIQ Ingestion API", version="1.0.0")


def _validate_signature(raw_body: bytes, signature_header: str | None) -> None:
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    secret = GITHUB_WEBHOOK_SECRET.encode()
    digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")


def _ignored_event(event_name: str) -> dict[str, str]:
    return {"status": "ignored", "event": event_name or "unknown"}


def _safe_source_url(event_name: str, source_url: str, delivery_id: str) -> str:
    clean_url = clean_text(source_url)
    if clean_url:
        return clean_url
    return f"event://{event_name}/{delivery_id or 'unknown'}"


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


@app.on_event("startup")
def startup_diagnostics() -> None:
    log_info(f"loading env from {ENV_PATH}")
    log_info(f"env file exists={ENV_PATH.exists()}")
    log_info(f"webhook secret loaded={bool(GITHUB_WEBHOOK_SECRET)}")
=======
from fastapi import FastAPI
from .extractor import extract_decision
import traceback
from .db_insert import insert_decision
app = FastAPI()
>>>>>>> feature/person-b-agents


@app.post("/github-webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> dict[str, Any]:
    event_name = clean_text(x_github_event).lower()
    delivery_id = clean_text(x_github_delivery)
    log_info(f"received event={event_name or 'unknown'}")

    if not GITHUB_WEBHOOK_SECRET:
        log_error("webhook secret missing from environment")
        raise HTTPException(status_code=500, detail="Server webhook secret not configured")

    try:
        raw_body = await request.body()
        _validate_signature(raw_body, x_hub_signature_256)
    except HTTPException:
        raise
    except Exception:
        log_warning("signature validation failed")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

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

    try:
        summary_text = clean_text(event_data.get("summary_text"))
        decision_data = extract_decision(summary_text)
        decision_label = clean_text(decision_data.get("decision"))
        if event_name == "push":
            decision_label = label or decision_label
        if not decision_label:
            decision_label = label or "Untitled decision"
        decision_data["decision"] = decision_label

        if node_exists(source_url, decision_label, event_name):
            log_info("skipped duplicate event")
            return {"duplicate": True}

        node_id = insert_node(
            data=decision_data,
            source_url=source_url,
            event_type=event_name,
            metadata_extra=metadata if isinstance(metadata, dict) else None,
        )

        if event_name == "push":
            log_info("processed push node inserted")
        else:
            log_info("processed pull_request node inserted")

        embedding = generate_embedding(summary_text)
        if embedding:
            insert_embedding(node_id=node_id, chunk=summary_text, embedding=embedding)
            log_step(f"embedding inserted node_id={node_id}")
        else:
            log_warning(f"embedding skipped node_id={node_id}")

        services = decision_data.get("services", [])
        services = services if isinstance(services, list) else []
        insert_edges(
            node_id=node_id,
            repo=clean_text(event_data.get("repo")),
            author=clean_text(event_data.get("author")),
            services=services,
        )
        log_step(f"edges inserted node_id={node_id}")

        return {
            "received": True,
            "processed": True,
            "event": event_name,
            "node_id": node_id,
            "decision": decision_data,
        }
<<<<<<< HEAD
    except Exception as exc:
        log_warning(f"tier1 processing failed event={event_name}: {exc}")
        return _ignored_event(event_name)
=======

    except Exception as e:
        return {
            "error": str(e),
            "trace": traceback.format_exc()
        }
>>>>>>> feature/person-b-agents
