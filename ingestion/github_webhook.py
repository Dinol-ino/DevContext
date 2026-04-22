import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from dotenv import load_dotenv

try:
    from .db_insert import _get_supabase_client, insert_edges, insert_embedding, insert_node
    from .embed import generate_embedding
    from .extractor import extract_decision
    from .utils import clean_text, log_error, log_info, log_step, log_warning, make_pr_text
except ImportError:
    from db_insert import _get_supabase_client, insert_edges, insert_embedding, insert_node
    from embed import generate_embedding
    from extractor import extract_decision
    from utils import clean_text, log_error, log_info, log_step, log_warning, make_pr_text

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()

app = FastAPI(title="DevContextIQ Ingestion API", version="1.0.0")


def _validate_signature(raw_body: bytes, signature_header: str | None) -> None:
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    secret = GITHUB_WEBHOOK_SECRET.encode()
    digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")


def _extract_pr_context(payload: dict[str, Any]) -> dict[str, Any]:
    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}
    user = pr.get("user") or {}

    action = clean_text(payload.get("action"))
    merged = bool(pr.get("merged"))
    event_type = "merged" if action == "closed" and merged else action

    return {
        "title": clean_text(pr.get("title")),
        "body": clean_text(pr.get("body")),
        "url": clean_text(pr.get("html_url")),
        "author": clean_text(user.get("login")),
        "repo": clean_text(repo.get("full_name")),
        "event_type": event_type,
    }


def _source_url_exists(source_url: str) -> bool:
    client = _get_supabase_client()
    try:
        result = (
            client.table("nodes")
            .select("id")
            .eq("source_url", source_url)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(f"Failed duplicate check for source_url '{source_url}': {exc}") from exc
    return bool(result.data)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ingestion-webhook"}


@app.get("/env-check")
def env_check() -> dict[str, bool]:
    return {
        "env_file_exists": ENV_PATH.exists(),
        "secret_loaded": bool(GITHUB_WEBHOOK_SECRET),
    }


@app.on_event("startup")
def startup_diagnostics() -> None:
    log_info(f"loading env from {ENV_PATH}")
    log_info(f"env file exists={ENV_PATH.exists()}")
    if GITHUB_WEBHOOK_SECRET:
        log_info("webhook secret loaded=True")
    else:
        log_warning("webhook secret loaded=False")


@app.post("/github-webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> dict[str, Any]:
    event_name = clean_text(x_github_event)
    delivery_id = clean_text(x_github_delivery)
    log_info(f"webhook received event={event_name or 'unknown'} delivery={delivery_id or 'unknown'}")

    if not GITHUB_WEBHOOK_SECRET:
        log_error("webhook secret missing from environment")
        raise HTTPException(status_code=500, detail="Server webhook secret not configured")

    try:
        raw_body = await request.body()
        _validate_signature(raw_body, x_hub_signature_256)
    except HTTPException:
        log_warning("webhook rejected due to invalid signature")
        raise
    except Exception:
        log_error("signature validation failed")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        log_error(f"invalid webhook payload: {exc}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload type.")

    context = _extract_pr_context(payload)
    event_type = clean_text(context["event_type"])

    if event_type != "merged":
        log_info(f"webhook ignored event={event_type or 'unknown'} repo={context['repo']}")
        return {"received": True, "processed": False, "event": event_type}

    source_url = context["url"]
    if not source_url:
        raise HTTPException(status_code=400, detail="Merged PR payload missing pull_request.html_url.")

    try:
        if _source_url_exists(source_url):
            log_info(f"duplicate pull request skipped source_url={source_url}")
            return {"duplicate": True}

        pr_text = make_pr_text(
            repo=context["repo"],
            title=context["title"],
            body=context["body"],
            url=source_url,
            author=context["author"],
            event_type=event_type,
        )

        decision_data = extract_decision(pr_text)
        node_id = insert_node(decision_data, source_url)
        log_info(f"node inserted id={node_id}")

        embedding = generate_embedding(pr_text)
        if not embedding:
            raise RuntimeError("Embedding generation returned an empty vector.")
        insert_embedding(node_id=node_id, chunk=pr_text, embedding=embedding)
        log_step(f"embedding inserted node_id={node_id}")

        services = decision_data.get("services", [])
        services = services if isinstance(services, list) else []
        insert_edges(
            node_id=node_id,
            repo=context["repo"],
            author=context["author"],
            services=services,
        )
        log_step(f"edges inserted node_id={node_id}")

        return {
            "received": True,
            "processed": True,
            "event": event_type,
            "node_id": node_id,
            "decision": decision_data,
        }
    except HTTPException:
        raise
    except Exception as exc:
        log_error(f"webhook processing failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to process merged PR webhook: {exc}") from exc
